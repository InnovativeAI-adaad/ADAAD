# SPDX-License-Identifier: Apache-2.0

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.agents.mutation_engine import MutationEngine
from app.architect_agent import ArchitectAgent
from app.mutation_executor import MutationExecutor
from runtime import metrics
from runtime.tools import mutation_guard


class RealMutationCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

        self._orig_dev_mode = os.environ.get("CRYOVANT_DEV_MODE")
        os.environ["CRYOVANT_DEV_MODE"] = "1"
        self.addCleanup(self._restore_dev_mode)

        self.agents_root = Path(self.tmp.name) / "agents"
        self._orig_agents_root = mutation_guard.AGENTS_ROOT
        mutation_guard.AGENTS_ROOT = self.agents_root
        self.addCleanup(self._restore_agents_root)
        self._create_test_agent("test_subject")
        self._create_test_agent("sandbox_alpha")

    def _restore_agents_root(self) -> None:
        mutation_guard.AGENTS_ROOT = self._orig_agents_root

    def _restore_dev_mode(self) -> None:
        if self._orig_dev_mode is None:
            os.environ.pop("CRYOVANT_DEV_MODE", None)
        else:
            os.environ["CRYOVANT_DEV_MODE"] = self._orig_dev_mode

    def _create_test_agent(self, agent_id: str) -> None:
        agent_dir = self.agents_root / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        (agent_dir / "meta.json").write_text(
            json.dumps({"id": agent_id, "name": "Test"}),
            encoding="utf-8",
        )
        (agent_dir / "dna.json").write_text(
            json.dumps({"lineage": "test", "traits": [], "version": 0}),
            encoding="utf-8",
        )
        (agent_dir / "certificate.json").write_text(
            json.dumps({"signature": "cryovant-dev-test"}),
            encoding="utf-8",
        )

    def test_full_mutation_cycle(self) -> None:
        architect = ArchitectAgent(self.agents_root)
        proposals = architect.propose_mutations()

        self.assertGreater(len(proposals), 0, "Architect should propose mutations")
        self.assertNotEqual(proposals[0].intent, "noop", "Should not be no-op")
        self.assertGreater(len(proposals[0].targets), 0, "Should have targets")
        self.assertGreater(len(proposals[0].targets[0].ops), 0, "Targets should include ops")

        engine = MutationEngine(metrics.METRICS_PATH, state_path=Path(self.tmp.name) / "mutation_engine_state.json")
        selected, _ = engine.select(proposals)

        self.assertIsNotNone(selected, "Engine should select a proposal")

        executor = MutationExecutor(self.agents_root)
        executor._run_tests = lambda: (True, "skipped")  # type: ignore[method-assign]
        result = executor.execute(selected)

        self.assertIn("status", result)
        self.assertIn("mutation_id", result)

        dna_paths = [
            self.agents_root / "test_subject" / "dna.json",
            self.agents_root / "sandbox_alpha" / "dna.json",
        ]
        dna_blobs = [json.loads(path.read_text(encoding="utf-8")) for path in dna_paths]

        self.assertTrue(
            any(
                dna.get("version", 0) > 0
                or len(dna.get("traits", [])) > 0
                or "last_mutation" in dna
                for dna in dna_blobs
            ),
            "DNA should be modified",
        )


if __name__ == "__main__":
    unittest.main()
