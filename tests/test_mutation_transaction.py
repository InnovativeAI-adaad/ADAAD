# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.agents.mutation_request import MutationTarget
from runtime.governance.foundation import SeededDeterminismProvider
from runtime.tools.mutation_fs import MutationTargetError, file_hash
from runtime.tools.mutation_tx import MutationRecord, MutationTransaction, MutationVerificationError


class MutationTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents_root = Path(self.tmp.name) / "agents"
        self.agent_dir = self.agents_root / "alpha"
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.agent_dir / "dna.json").write_text(json.dumps({"version": 0}), encoding="utf-8")
        (self.agent_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.agent_dir / "config" / "settings.json").write_text(json.dumps({"mode": "safe"}), encoding="utf-8")

    def test_transaction_commit_updates_files(self) -> None:
        dna_hash = file_hash(self.agent_dir / "dna.json")
        target = MutationTarget(
            agent_id="alpha",
            path="dna.json",
            target_type="dna",
            ops=[{"op": "set", "path": "/version", "value": 1}],
            hash_preimage=dna_hash,
        )
        with MutationTransaction("alpha", agents_root=self.agents_root) as tx:
            tx.apply(target)
            tx.commit()
        payload = json.loads((self.agent_dir / "dna.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)

    def test_deterministic_mode_with_identical_context_generates_identical_tx_ids(self) -> None:
        provider = SeededDeterminismProvider("seed-1")
        tx1 = MutationTransaction(
            "alpha",
            agents_root=self.agents_root,
            epoch_id="epoch-1",
            mutation_id="mutation-1",
            replay_seed="0000000000000001",
            replay_mode="strict",
            recovery_tier="audit",
            provider=provider,
        )
        tx2 = MutationTransaction(
            "alpha",
            agents_root=self.agents_root,
            epoch_id="epoch-1",
            mutation_id="mutation-1",
            replay_seed="0000000000000001",
            replay_mode="strict",
            recovery_tier="audit",
            provider=provider,
        )
        self.assertEqual(tx1.tx_id, tx2.tx_id)

    def test_nondeterministic_mode_allows_system_provider(self) -> None:
        tx = MutationTransaction(
            "alpha",
            agents_root=self.agents_root,
            epoch_id="epoch-1",
            mutation_id="mutation-1",
            replay_seed="0000000000000001",
            replay_mode="off",
            recovery_tier="standard",
        )
        self.assertEqual(len(tx.tx_id), 32)

    def test_verify_passes_for_valid_transaction(self) -> None:
        dna_hash = file_hash(self.agent_dir / "dna.json")
        target = MutationTarget(
            agent_id="alpha",
            path="dna.json",
            target_type="dna",
            ops=[{"op": "set", "path": "/version", "value": 3}],
            hash_preimage=dna_hash,
        )
        with MutationTransaction("alpha", agents_root=self.agents_root) as tx:
            tx.apply(target)
            verification = tx.verify()
            self.assertTrue(verification["ok"])
            self.assertTrue(verification["invariants"]["paths_resolve_under_agent_root"])
            self.assertTrue(verification["invariants"]["touched_file_set_stable"])
            self.assertTrue(verification["invariants"]["metadata_consistent"])

    def test_verify_fails_on_tampered_record_state(self) -> None:
        dna_hash = file_hash(self.agent_dir / "dna.json")
        target = MutationTarget(
            agent_id="alpha",
            path="dna.json",
            target_type="dna",
            ops=[{"op": "set", "path": "/version", "value": 4}],
            hash_preimage=dna_hash,
        )
        with MutationTransaction("alpha", agents_root=self.agents_root) as tx:
            tx.apply(target)
            tx._records[0] = MutationRecord(
                target=target,
                result=tx.records[0].result.__class__(
                    path=tx.records[0].result.path,
                    applied=0,
                    skipped=0,
                    checksum=tx.records[0].result.checksum,
                ),
            )
            with self.assertRaises(MutationVerificationError):
                tx.verify()

    @mock.patch("runtime.tools.mutation_tx.issue_rollback_certificate")
    def test_verify_failure_issues_rollback_certificate(self, issue_cert) -> None:
        dna_hash = file_hash(self.agent_dir / "dna.json")
        target = MutationTarget(
            agent_id="alpha",
            path="dna.json",
            target_type="dna",
            ops=[{"op": "set", "path": "/version", "value": 5}],
            hash_preimage=dna_hash,
        )
        with self.assertRaises(MutationVerificationError):
            with MutationTransaction("alpha", agents_root=self.agents_root) as tx:
                tx.apply(target)
                tx._records[0] = MutationRecord(
                    target=target,
                    result=tx.records[0].result.__class__(
                        path=Path("/tmp/outside.json"),
                        applied=tx.records[0].result.applied,
                        skipped=tx.records[0].result.skipped,
                        checksum=tx.records[0].result.checksum,
                    ),
                )
                tx.verify()
        issue_cert.assert_called_once()

    @mock.patch("runtime.tools.mutation_tx.issue_rollback_certificate")
    def test_transaction_rolls_back_on_error(self, issue_cert) -> None:
        dna_hash = file_hash(self.agent_dir / "dna.json")
        target = MutationTarget(
            agent_id="alpha",
            path="dna.json",
            target_type="dna",
            ops=[{"op": "set", "path": "/version", "value": 2}],
            hash_preimage=dna_hash,
        )
        with self.assertRaises(MutationTargetError):
            with MutationTransaction("alpha", agents_root=self.agents_root) as tx:
                tx.apply(target)
                raise MutationTargetError("forced")
        payload = json.loads((self.agent_dir / "dna.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 0)
        issue_cert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
