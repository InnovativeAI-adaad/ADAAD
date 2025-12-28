# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.agents.base_agent import stage_offspring
from app.beast_mode_loop import BeastModeLoop
from runtime import capability_graph, metrics
from security.ledger import journal


class BeastPromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

        self._orig_capabilities_path = capability_graph.CAPABILITIES_PATH
        capability_graph.CAPABILITIES_PATH = Path(self.tmp.name) / "capabilities.json"
        self.addCleanup(setattr, capability_graph, "CAPABILITIES_PATH", self._orig_capabilities_path)

        self._orig_ledger_root = journal.LEDGER_ROOT
        self._orig_ledger_file = journal.LEDGER_FILE
        journal.LEDGER_ROOT = Path(self.tmp.name) / "ledger"
        journal.LEDGER_FILE = journal.LEDGER_ROOT / "lineage.jsonl"
        self.addCleanup(setattr, journal, "LEDGER_ROOT", self._orig_ledger_root)
        self.addCleanup(setattr, journal, "LEDGER_FILE", self._orig_ledger_file)

        self._orig_threshold = os.environ.get("ADAAD_FITNESS_THRESHOLD")
        os.environ["ADAAD_FITNESS_THRESHOLD"] = "0.1"

        def _restore_threshold() -> None:
            if self._orig_threshold is None:
                os.environ.pop("ADAAD_FITNESS_THRESHOLD", None)
            else:
                os.environ["ADAAD_FITNESS_THRESHOLD"] = self._orig_threshold

        self.addCleanup(_restore_threshold)

    def test_beast_promotes(self) -> None:
        agents_root = Path(self.tmp.name) / "agents"
        lineage_dir = agents_root / "lineage"
        agent_dir = agents_root / "agentA"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text(json.dumps({"name": "agentA"}), encoding="utf-8")
        (agent_dir / "dna.json").write_text(json.dumps({"seq": "abc"}), encoding="utf-8")
        (agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")

        capability_graph.register_capability("orchestrator.boot", "0.1.0", 1.0, "test")
        capability_graph.register_capability("cryovant.gate", "0.1.0", 1.0, "test")

        staged = stage_offspring("agentA", "mutate-me", lineage_dir)

        journal.ensure_ledger()
        journal.write_entry(agent_id="agentA", action="seed", payload={})

        beast = BeastModeLoop(agents_root, lineage_dir)
        result = beast.run_cycle("agentA")

        self.assertEqual(result["status"], "promoted")
        promoted_path = Path(result["promoted_path"])
        self.assertTrue(promoted_path.exists())
        self.assertFalse(staged.exists())

        registry = capability_graph.get_capabilities()
        self.assertIn("agent.agentA.mutation_quality", registry)


if __name__ == "__main__":
    unittest.main()