# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution import EvolutionGovernor, LineageLedgerV2, ReplayEngine
from runtime.evolution.mutation_budget import MutationBudgetManager
from runtime.governance.foundation import SeededDeterminismProvider


class EvolutionGovernorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger_path = Path(self.tmp.name) / "lineage_v2.jsonl"
        self.ledger = LineageLedgerV2(self.ledger_path)
        self.governor = EvolutionGovernor(ledger=self.ledger, max_impact=0.99)

    def _request(self, **overrides) -> MutationRequest:
        payload = {
            "agent_id": "alpha",
            "generation_ts": "2026-01-01T00:00:00Z",
            "intent": "refactor",
            "ops": [],
            "signature": "cryovant-dev-alpha",
            "nonce": "n-1",
            "authority_level": "governor-review",
            "targets": [
                MutationTarget(
                    agent_id="alpha",
                    path="dna.json",
                    target_type="dna",
                    ops=[{"op": "set", "path": "/version", "value": 2}],
                    hash_preimage="abc",
                )
            ],
        }
        payload.update(overrides)
        return MutationRequest(**payload)

    def test_accepts_valid_bundle_and_records_certificate(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(self._request(), epoch_id="epoch-1")
        self.assertTrue(decision.accepted)
        self.assertIsNotNone(decision.certificate)
        self.assertEqual(decision.certificate.get("bundle_id_source"), "governor")
        self.assertTrue(str(decision.certificate.get("bundle_id", "")).startswith("bundle-"))
        self.assertEqual(len(decision.certificate.get("replay_seed", "")), 16)
        self.assertNotEqual(decision.certificate.get("replay_seed"), "0000000000000000")
        self.assertTrue(decision.certificate.get("strategy_hash"))
        self.assertTrue(decision.certificate.get("strategy_version_set"))
        entries = self.ledger.read_all()
        self.assertEqual(entries[-1]["type"], "MutationBundleEvent")

    def test_governor_generated_replay_seed_is_deterministic_for_same_input(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        request = self._request()
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision_one = self.governor.validate_bundle(request, epoch_id="epoch-1")
            decision_two = self.governor.validate_bundle(request, epoch_id="epoch-1")

        self.assertTrue(decision_one.accepted)
        self.assertTrue(decision_two.accepted)
        self.assertEqual(decision_one.certificate.get("bundle_id"), decision_two.certificate.get("bundle_id"))
        self.assertEqual(decision_one.certificate.get("replay_seed"), decision_two.certificate.get("replay_seed"))

    def test_strict_mode_malformed_nonce_emits_warning_metric(self) -> None:
        self.governor = EvolutionGovernor(ledger=self.ledger, max_impact=0.99, replay_mode="strict", provider=SeededDeterminismProvider(seed="strict-nonce-test"))
        self.governor.mark_epoch_start("epoch-1")
        malformed = self._request(nonce="bad-nonce")
        with mock.patch("security.cryovant.signature_valid", return_value=True), mock.patch("runtime.metrics.log") as log_metric:
            self.governor.validate_bundle(malformed, epoch_id="epoch-1")

        matching = [
            call
            for call in log_metric.call_args_list
            if call.kwargs.get("event_type") == "strict_replay_malformed_nonce"
        ]
        self.assertTrue(matching)
        payload = matching[-1].kwargs.get("payload", {})
        self.assertEqual(payload.get("epoch_id"), "epoch-1")
        self.assertEqual(payload.get("agent_id"), "alpha")
        self.assertEqual(payload.get("nonce"), "bad-nonce")

    def test_rejects_invalid_signature(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        with mock.patch("security.cryovant.signature_valid", return_value=False):
            decision = self.governor.validate_bundle(self._request(), epoch_id="epoch-1")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "invalid_signature")

    def test_rejects_when_epoch_not_started(self) -> None:
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(self._request(), epoch_id="epoch-404")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "epoch_not_started")

    def test_uses_request_bundle_id_as_hint(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        request = self._request(bundle_id="bundle-hint")
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(request, epoch_id="epoch-1")
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.certificate.get("bundle_id"), "bundle-hint")
        self.assertEqual(decision.certificate.get("bundle_id_source"), "request")

    def test_authority_level_gates_impact(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        high_risk = self._request(
            authority_level="low-impact",
            targets=[
                MutationTarget(
                    agent_id="alpha",
                    path="security/policy.py",
                    target_type="security",
                    ops=[{"op": "replace", "value": "x"}] * 20,
                    hash_preimage="abc",
                )
            ],
        )
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(high_risk, epoch_id="epoch-1")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "authority_level_exceeded")

    def test_replay_engine_deterministic_digest(self) -> None:
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            self.governor.mark_epoch_start("epoch-1", {"kind": "test"})
            self.governor.validate_bundle(self._request(), epoch_id="epoch-1")
            self.governor.mark_epoch_end("epoch-1", {"kind": "test"})
        replay = ReplayEngine(self.ledger)
        run1 = replay.deterministic_replay("epoch-1")
        run2 = replay.deterministic_replay("epoch-1")
        self.assertEqual(run1["digest"], run2["digest"])
        self.assertTrue(replay.assert_reachable("epoch-1", run1["digest"]))



    def test_budget_decision_fields_emitted_to_governance_event(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(self._request(), epoch_id="epoch-1")
        self.assertTrue(decision.accepted)
        self.assertGreaterEqual(decision.mutation_cost, 0.0)
        entries = self.ledger.read_all()
        payload = entries[-1]["payload"]
        self.assertIn("mutation_cost", payload)
        self.assertIn("fitness_gain", payload)
        self.assertIn("roi", payload)
        self.assertIn("accepted", payload)

    def test_budget_manager_can_reject_before_certificate_activation(self) -> None:
        self.governor = EvolutionGovernor(
            ledger=self.ledger,
            max_impact=0.99,
            mutation_budget_manager=MutationBudgetManager(
                per_cycle_budget=1_000.0,
                per_epoch_budget=10_000.0,
                roi_threshold=0.9,
                exploration_rate=0.0,
            ),
        )
        self.governor.mark_epoch_start("epoch-1")
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(self._request(), epoch_id="epoch-1")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "mutation_roi_below_threshold")
        self.assertIsNone(decision.certificate)


    def test_feedback_loop_adjusts_entropy_budget_from_metrics(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        history = [
            {
                "epoch_id": "epoch-0",
                "cycle_id": "c-1",
                "mutation_acceptance_rate": 0.1,
                "entropy": {"utilization": 0.9},
                "efficiency_cost_signals": {"cost_units": 100.0, "accepted_mutation_count": 1},
            }
        ]
        baseline_budget = self.governor.entropy_budget
        with mock.patch.object(self.governor.metrics_emitter, "_read_history", return_value=history), mock.patch(
            "security.cryovant.signature_valid", return_value=True
        ):
            decision = self.governor.validate_bundle(self._request(), epoch_id="epoch-1")
        self.assertIsNotNone(decision)
        self.assertLessEqual(self.governor.entropy_budget, baseline_budget)


    def test_feedback_loop_records_governor_config_events(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        history = [
            {
                "epoch_id": "epoch-0",
                "cycle_id": "c-1",
                "mutation_acceptance_rate": 0.1,
                "entropy": {"utilization": 0.95},
                "efficiency_cost_signals": {"cost_units": 100.0, "accepted_mutation_count": 1},
            }
        ]
        metrics_dir = self.governor.metrics_emitter.metrics_dir
        epoch_summary = metrics_dir / "epoch-1" / "summary.json"
        epoch_summary.parent.mkdir(parents=True, exist_ok=True)
        epoch_summary.write_text('{"local_optima_risk": true}', encoding="utf-8")

        with mock.patch.object(self.governor.metrics_emitter, "_read_history", return_value=history), mock.patch(
            "security.cryovant.signature_valid", return_value=True
        ):
            self.governor.validate_bundle(self._request(), epoch_id="epoch-1")

        entries = self.ledger.read_all()
        types = [entry.get("type") for entry in entries]
        self.assertIn("GovernorConfigEvent", types)
        config_keys = [
            (entry.get("payload") or {}).get("config_key")
            for entry in entries
            if entry.get("type") == "GovernorConfigEvent"
        ]
        self.assertIn("mutation_budget_params", config_keys)


    def test_feedback_loop_prefers_acceptance_signal_over_entropy_floor(self) -> None:
        self.governor.mark_epoch_start("epoch-1")
        history = [
            {
                "epoch_id": "epoch-0",
                "cycle_id": "c-1",
                "mutation_acceptance_rate": 0.1,
                "entropy": {"utilization": 0.1},
                "efficiency_cost_signals": {"cost_units": 5.0, "accepted_mutation_count": 1},
            }
        ]
        old_budget = self.governor.entropy_budget
        with mock.patch.object(self.governor.metrics_emitter, "_read_history", return_value=history), mock.patch(
            "security.cryovant.signature_valid", return_value=True
        ):
            self.governor.validate_bundle(self._request(), epoch_id="epoch-1")

        self.assertLessEqual(self.governor.entropy_budget, old_budget)

    def test_entropy_budget_reads_env_when_arg_omitted(self) -> None:
        with mock.patch.dict("os.environ", {"ADAAD_GOVERNOR_ENTROPY_BUDGET": "7"}, clear=False):
            governor = EvolutionGovernor(ledger=self.ledger, max_impact=0.99)
        self.assertEqual(governor.entropy_budget, 7)

    def test_entropy_budget_arg_overrides_env(self) -> None:
        with mock.patch.dict("os.environ", {"ADAAD_GOVERNOR_ENTROPY_BUDGET": "7"}, clear=False):
            governor = EvolutionGovernor(ledger=self.ledger, max_impact=0.99, entropy_budget=3)
        self.assertEqual(governor.entropy_budget, 3)

    def test_entropy_budget_invalid_env_falls_back_to_default(self) -> None:
        with mock.patch.dict("os.environ", {"ADAAD_GOVERNOR_ENTROPY_BUDGET": "not-an-int"}, clear=False):
            governor = EvolutionGovernor(ledger=self.ledger, max_impact=0.99)
        self.assertEqual(governor.entropy_budget, 100)


    def test_entropy_budget_strict_mode_requires_env_or_argument(self) -> None:
        with mock.patch.dict("os.environ", {"ADAAD_SOVEREIGN_MODE": "strict"}, clear=True):
            with self.assertRaisesRegex(ValueError, "entropy_budget_required_in_strict_sovereign_mode"):
                EvolutionGovernor(ledger=self.ledger, max_impact=0.99)

    def test_entropy_budget_strict_mode_rejects_invalid_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"ADAAD_SOVEREIGN_MODE": "strict", "ADAAD_GOVERNOR_ENTROPY_BUDGET": "not-an-int"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "invalid_entropy_budget_in_strict_sovereign_mode"):
                EvolutionGovernor(ledger=self.ledger, max_impact=0.99)


if __name__ == "__main__":
    unittest.main()
