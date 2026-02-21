# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from app.agents.mutation_request import MutationTarget
from runtime.tools.mutation_fs import MutationTargetError, file_hash
from runtime.tools.mutation_tx import MutationTransaction


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
