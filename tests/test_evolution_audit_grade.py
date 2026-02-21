# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution import EvolutionGovernor, LineageLedgerV2, ReplayEngine, RecoveryTier
from security.ledger import journal


class EvolutionAuditGradeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = LineageLedgerV2(Path(self.tmp.name) / "lineage_v2.jsonl")
        self.governor = EvolutionGovernor(ledger=self.ledger, max_impact=1.0)
        self.governor.mark_epoch_start("epoch-1")

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

    def test_authority_matrix_enforcement(self) -> None:
        request = self._request(authority_level="low-impact", targets=[MutationTarget(agent_id="alpha", path="runtime/core.py", target_type="runtime", ops=[{"op": "replace", "value": "x"}] * 20, hash_preimage="a")])
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            decision = self.governor.validate_bundle(request, "epoch-1")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "authority_level_exceeded")

    def test_cumulative_digest_chain(self) -> None:
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            first = self.governor.validate_bundle(self._request(bundle_id="b1"), "epoch-1")
            second = self.governor.validate_bundle(self._request(bundle_id="b2"), "epoch-1")
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        digest = self.ledger.get_epoch_digest("epoch-1")
        self.assertTrue(isinstance(digest, str) and digest.startswith("sha256:"))

    def test_strategy_hash_drift_fails_replay(self) -> None:
        with mock.patch("security.cryovant.signature_valid", return_value=True):
            self.governor.validate_bundle(self._request(bundle_id="b1"), "epoch-1")
        original_digest = self.ledger.get_epoch_digest("epoch-1")
        entries = self.ledger.read_all()
        for entry in entries:
            if entry.get("type") == "MutationBundleEvent":
                entry["payload"]["certificate"]["strategy_snapshot_hash"] = "tampered"
        Path(self.ledger.ledger_path).write_text("\n".join(__import__("json").dumps(e) for e in entries) + "\n", encoding="utf-8")
        reloaded = LineageLedgerV2(Path(self.tmp.name) / "lineage_v2.jsonl")
        replay = ReplayEngine(reloaded)
        self.assertNotEqual(original_digest, replay.compute_incremental_digest_unverified("epoch-1"))

    def test_journal_projection_matches_lineage(self) -> None:
        event = {"type": "GovernanceDecisionEvent", "payload": {"agent_id": "alpha", "epoch_id": "epoch-1"}}
        projection = journal.project_from_lineage(event)
        self.assertEqual(projection["action"], "GovernanceDecisionEvent")
        self.assertEqual(projection["payload"]["epoch_id"], "epoch-1")

    def test_recovery_tier_escalation(self) -> None:
        self.governor.enter_fail_closed("replay_divergence", "epoch-1", tier=RecoveryTier.SOFT)
        reopened = self.governor.apply_recovery_event("epoch-1", "human-recovery-1", RecoveryTier.AUDIT)
        self.assertFalse(reopened)
        reopened = self.governor.apply_recovery_event("epoch-1", "human-recovery-2", RecoveryTier.CONSTITUTIONAL_RESET)
        self.assertTrue(reopened)
        self.assertFalse(self.governor.fail_closed)


if __name__ == "__main__":
    unittest.main()
