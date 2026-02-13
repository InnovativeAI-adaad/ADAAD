# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationRequest, MutationTarget
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


if __name__ == "__main__":
    unittest.main()
