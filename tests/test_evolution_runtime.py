import pytest
pytestmark = pytest.mark.regression_standard
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adaad.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution.epoch import EpochManager
from runtime.evolution.governor import EvolutionGovernor
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.evolution.replay_verifier import ReplayVerifier
from runtime.evolution.runtime import EvolutionRuntime


class EvolutionRuntimeComponentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = LineageLedgerV2(Path(self.tmp.name) / "lineage_v2.jsonl")
        self.governor = EvolutionGovernor(ledger=self.ledger)

    def test_epoch_manager_persists_active_epoch(self) -> None:
        state_path = Path(self.tmp.name) / "state" / "current_epoch.json"
        manager = EpochManager(self.governor, self.ledger, max_mutations=1, state_path=state_path)
        state = manager.load_or_create()
        self.assertTrue(state.epoch_id.startswith("epoch-"))
        self.assertTrue(state_path.exists())
        payload = __import__("json").loads(state_path.read_text(encoding="utf-8"))
        self.assertNotIn("digest", payload)
        self.assertNotIn("epoch_digest", payload)
        manager.increment_mutation_count()
        rotated = manager.maybe_rotate(reason="mutation_threshold")
        self.assertNotEqual(state.epoch_id, rotated.epoch_id)

    def test_replay_verifier_records_event(self) -> None:
        self.ledger.append_event("EpochStartEvent", {"epoch_id": "epoch-1"})
        verifier = ReplayVerifier(self.ledger, ReplayEngine(self.ledger), verify_every_n_mutations=1)
        checkpoint = ReplayEngine(self.ledger).deterministic_replay("epoch-1")["digest"]
        result = verifier.verify_epoch("epoch-1", checkpoint)
        self.assertTrue(result["replay_passed"])
        self.assertEqual(result["checkpoint_digest"], checkpoint)

    def test_governor_enters_fail_closed_on_demand(self) -> None:
        request = MutationRequest(
            agent_id="alpha",
            generation_ts="2026-01-01T00:00:00Z",
            intent="refactor",
            ops=[],
            signature="cryovant-dev-alpha",
            nonce="n-1",
            targets=[
                MutationTarget(
                    agent_id="alpha",
                    path="dna.json",
                    target_type="dna",
                    ops=[{"op": "set", "path": "/version", "value": 2}],
                    hash_preimage="abc",
                )
            ],
        )
        self.governor.enter_fail_closed("replay_divergence", "epoch-1")
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(request, epoch_id="epoch-1")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "governor_fail_closed")


    def test_before_mutation_cycle_emits_forecast_and_scan_events(self) -> None:
        runtime = EvolutionRuntime(ledger_path=Path(self.tmp.name) / "ledger_forecast.jsonl")
        runtime.boot()

        result = runtime.before_mutation_cycle()

        self.assertIn("entropy_forecast", result)
        self.assertIn("threat_scan", result)
        entries = runtime.ledger.read_all()
        event_types = [item.get("type") for item in entries]
        self.assertIn("EntropyForecastEvent", event_types)
        self.assertIn("ThreatScanEvent", event_types)

    def test_before_mutation_cycle_blocks_on_entropy_forecast(self) -> None:
        runtime = EvolutionRuntime(ledger_path=Path(self.tmp.name) / "ledger_entropy.jsonl")
        runtime.boot()
        runtime.epoch_cumulative_entropy_bits = 4096

        with mock.patch.dict("os.environ", {"ADAAD_MAX_EPOCH_ENTROPY_BITS": "4096", "ADAAD_MAX_MUTATION_ENTROPY_BITS": "128"}):
            result = runtime.before_mutation_cycle()

        self.assertTrue(result.get("blocked"))
        self.assertEqual(result.get("reason"), "entropy_forecast_block")

    def test_before_mutation_cycle_escalates_on_threat_scan(self) -> None:
        runtime = EvolutionRuntime(ledger_path=Path(self.tmp.name) / "ledger_threat.jsonl")
        runtime.boot()
        runtime.ledger.append_event("SyntheticMutationOutcome", {"epoch_id": runtime.current_epoch_id, "status": "failed"})
        runtime.ledger.append_event("SyntheticMutationOutcome", {"epoch_id": runtime.current_epoch_id, "status": "failed"})

        result = runtime.before_mutation_cycle()

        self.assertTrue(result.get("escalated"))
        self.assertEqual(result.get("reason"), "threat_scan_escalate")
    def test_replay_preflight_reports_explicit_divergence_fields(self) -> None:
        runtime = EvolutionRuntime()
        runtime.verify_epoch = mock.Mock(return_value={
            "epoch_id": "epoch-1",
            "baseline_epoch": "epoch-1",
            "baseline_source": "lineage_epoch_digest",
            "expected_digest": "sha256:expected",
            "actual_digest": "sha256:actual",
            "passed": False,
            "decision": "diverge",
            "replay_score": 0.4,
            "cause_buckets": {"digest_mismatch": True},
        })
        runtime.ledger.list_epoch_ids = mock.Mock(return_value=["epoch-1"])
        runtime.governor.enter_fail_closed = mock.Mock()

        result = runtime.replay_preflight("strict")

        self.assertTrue(result["has_divergence"])
        self.assertEqual(result["decision"], "fail_closed")
        detail = result["results"][0]
        self.assertEqual(detail["baseline_epoch"], "epoch-1")
        self.assertEqual(detail["expected_digest"], "sha256:expected")
        self.assertEqual(detail["actual_digest"], "sha256:actual")
        self.assertEqual(detail["decision"], "diverge")
        self.assertLess(detail["replay_score"], 1.0)
        self.assertTrue(detail["cause_buckets"]["digest_mismatch"])
        self.assertEqual(result["fail_closed_payload"]["reason_code"], "hash_mismatch")

    def test_replay_preflight_strict_halts_on_first_divergence(self) -> None:
        runtime = EvolutionRuntime()
        runtime.verify_epoch = mock.Mock(
            side_effect=[
                {
                    "epoch_id": "epoch-1",
                    "expected_digest": "sha256:a",
                    "actual_digest": "sha256:b",
                    "passed": False,
                    "decision": "diverge",
                    "cause_buckets": {"digest_mismatch": True},
                },
                {
                    "epoch_id": "epoch-2",
                    "expected_digest": "sha256:c",
                    "actual_digest": "sha256:c",
                    "passed": True,
                    "decision": "match",
                    "cause_buckets": {"digest_mismatch": False},
                },
            ]
        )
        runtime.ledger.list_epoch_ids = mock.Mock(return_value=["epoch-1", "epoch-2"])

        result = runtime.replay_preflight("strict")

        self.assertEqual(runtime.verify_epoch.call_count, 1)
        self.assertEqual(result["decision"], "fail_closed")
        self.assertEqual(result["fail_closed_payload"]["reason_code"], "hash_mismatch")

    def test_boot_fail_closes_on_federation_split_brain(self) -> None:
        runtime = EvolutionRuntime()
        runtime.coherence_validator = mock.Mock()
        runtime.coherence_validator.validate = mock.Mock(return_value=mock.Mock(
            recommendation="halt",
            report_hash="sha256:" + ("a" * 64),
            to_dict=lambda: {"recommendation": "halt"},
        ))
        runtime.governor.enter_fail_closed = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "federation_split_brain"):
            runtime.boot()

        runtime.governor.enter_fail_closed.assert_called_once()

    def test_boot_journals_federation_coherence_event(self) -> None:
        runtime = EvolutionRuntime()
        runtime.coherence_validator = mock.Mock()
        runtime.coherence_validator.validate = mock.Mock(return_value=mock.Mock(
            recommendation="proceed",
            report_hash="sha256:" + ("b" * 64),
            to_dict=lambda: {"recommendation": "proceed", "report_hash": "sha256:" + ("b" * 64)},
        ))
        runtime.ledger.append_event = mock.Mock()
        with mock.patch("runtime.evolution.runtime.constitution.VALIDATOR_REGISTRY", {"lineage_continuity": lambda _req: {"ok": True, "reason": "ok"}}):
            runtime.epoch_manager.load_or_create = mock.Mock(return_value=mock.Mock(
                epoch_id="epoch-1",
                to_dict=lambda: {
                    "epoch_id": "epoch-1",
                    "metadata": {},
                    "mutation_count": 0,
                    "start_ts": "",
                    "baseline_id": "",
                    "baseline_hash": "",
                    "cumulative_entropy_bits": 0,
                },
            ))
            runtime.boot()

        first_call = runtime.ledger.append_event.call_args_list[0]
        self.assertEqual(first_call.args[0], "FederationCoherenceEvent")


    def test_after_mutation_cycle_emits_regression_signal_and_forces_rotation_on_severe_decline(self) -> None:
        runtime = EvolutionRuntime()
        runtime.boot()

        for index, score in enumerate([0.95, 0.91, 0.86, 0.80, 0.73, 0.66, 0.59, 0.52], start=1):
            runtime.ledger.append_event(
                "GovernanceDecisionEvent",
                {"epoch_id": runtime.current_epoch_id, "accepted": True, "impact_score": 0.1},
            )
            result = runtime.after_mutation_cycle(
                {
                    "cycle_id": f"cycle-{index:03d}",
                    "mutation_id": f"m-{index:03d}",
                    "fitness_score": score,
                    "status": "ok",
                }
            )

        assert result["fitness_regression"]["severity"] == "severe"
        assert runtime.epoch_manager.should_rotate() is True
        assert runtime.epoch_manager.rotation_reason() == "severe_fitness_regression"


if __name__ == "__main__":
    unittest.main()
