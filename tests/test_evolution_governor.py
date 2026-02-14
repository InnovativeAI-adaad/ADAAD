# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution import EvolutionGovernor, LineageLedgerV2, ReplayEngine


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


if __name__ == "__main__":
    unittest.main()
