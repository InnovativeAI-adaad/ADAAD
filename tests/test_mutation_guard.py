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
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

from app.mutation_executor import MutationExecutor
from app.agents.mutation_request import MutationRequest
from runtime.tools import mutation_guard
from runtime.tools.mutation_guard import apply_dna_mutation
from runtime import metrics
from security import cryovant


class MutationGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_root = Path(self.tmp.name)
        self._orig_agents_root = mutation_guard.AGENTS_ROOT
        mutation_guard.AGENTS_ROOT = self.tmp_root / "agents"
        self.addCleanup(setattr, mutation_guard, "AGENTS_ROOT", self._orig_agents_root)

    def test_apply_dna_mutation_writes_checksum(self) -> None:
        agent_fs_id = "alpha/demo"
        ops = [{"op": "set", "path": "/traits/primary", "value": "adaptive"}]
        result = apply_dna_mutation(agent_fs_id, ops)

        dna_path = self.tmp_root / "agents" / "alpha" / "demo" / "dna.json"
        self.assertTrue(dna_path.exists())
        payload = json.loads(dna_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["traits"]["primary"], "adaptive")
        self.assertGreater(len(result.get("checksum", "")), 0)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["skipped"], 0)


class MutationExecutorIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_root = Path(self.tmp.name)
        self._orig_agents_root = mutation_guard.AGENTS_ROOT
        mutation_guard.AGENTS_ROOT = self.tmp_root / "agents"
        self.addCleanup(setattr, mutation_guard, "AGENTS_ROOT", self._orig_agents_root)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = self.tmp_root / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)
        self._orig_keys_dir = cryovant.KEYS_DIR
        cryovant.KEYS_DIR = self.tmp_root / "keys"
        cryovant.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        self.addCleanup(setattr, cryovant, "KEYS_DIR", self._orig_keys_dir)

    def test_executor_applies_mutation(self) -> None:
        agents_root = self.tmp_root / "agents"
        agent_dir = agents_root / "sample"
        agent_dir.mkdir(parents=True, exist_ok=True)
        # Seed required files
        (agent_dir / "meta.json").write_text("{}", encoding="utf-8")
        (agent_dir / "dna.json").write_text("{}", encoding="utf-8")
        (agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")

        executor = MutationExecutor(agents_root=agents_root)

        request = MutationRequest(
            agent_id="sample",
            generation_ts="now",
            intent="test",
            ops=[{"op": "set", "path": "/lineage", "value": "seed"}],
            signature="cryovant-dev-seed",
            nonce="n-1",
        )

        with mock.patch.dict("os.environ", {"ADAAD_TRUST_MODE": "dev"}, clear=False), mock.patch("app.mutation_executor.verify_all", return_value=(True, [])), mock.patch("app.mutation_executor.journal.write_entry"), mock.patch(
            "app.mutation_executor.journal.append_tx"
        ), mock.patch(
            "app.mutation_executor.metrics.log"
        ), mock.patch.object(executor, "_run_tests", return_value=(True, "ok")):
            result = executor.execute(request)

        self.assertEqual(result["status"], "executed")
        dna_payload = json.loads((agent_dir / "dna.json").read_text(encoding="utf-8"))
        self.assertEqual(dna_payload["lineage"], "seed")
        manifest_path = Path(result["manifest_path"])
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["terminal_status"], "completed")
        self.assertTrue(result["manifest_hash"].startswith("sha256:"))

    def test_executor_noop_does_not_enter_execution_states(self) -> None:
        agents_root = self.tmp_root / "agents"
        agent_dir = agents_root / "sample"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text("{}", encoding="utf-8")
        (agent_dir / "dna.json").write_text("{}", encoding="utf-8")
        (agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")

        executor = MutationExecutor(agents_root=agents_root)
        request = MutationRequest(
            agent_id="sample",
            generation_ts="now",
            intent="test",
            ops=[],
            signature="cryovant-dev-seed",
            nonce="n-noop",
        )

        transitions = []

        def _record_transition(current, nxt, ctx):
            transitions.append((current, nxt))
            return nxt

        with mock.patch.dict("os.environ", {"ADAAD_TRUST_MODE": "dev"}, clear=False), mock.patch("app.mutation_executor.verify_all", return_value=(True, [])), mock.patch.object(
            executor.governor,
            "validate_bundle",
            return_value=SimpleNamespace(accepted=True, reason="ok", replay_status="ok", certificate={"bundle_id": "b-noop"}),
        ), mock.patch("app.mutation_executor.journal.write_entry"), mock.patch(
            "app.mutation_executor.journal.append_tx"
        ), mock.patch("app.mutation_executor.metrics.log"), mock.patch("app.mutation_executor.lifecycle_transition", side_effect=_record_transition):
            result = executor.execute(request)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(transitions, [("proposed", "staged")])

    def test_executor_lifecycle_dry_run_simulates_without_mutation(self) -> None:
        agents_root = self.tmp_root / "agents"
        agent_dir = agents_root / "sample"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "meta.json").write_text("{}", encoding="utf-8")
        (agent_dir / "dna.json").write_text("{}", encoding="utf-8")
        (agent_dir / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-seed"}), encoding="utf-8")

        executor = MutationExecutor(agents_root=agents_root)
        request = MutationRequest(
            agent_id="sample",
            generation_ts="now",
            intent="test",
            ops=[{"op": "set", "path": "/lineage", "value": "seed"}],
            signature="cryovant-dev-seed",
            nonce="n-dry",
        )

        with mock.patch.dict("os.environ", {"ADAAD_TRUST_MODE": "dev", "ADAAD_LIFECYCLE_DRY_RUN": "1"}, clear=False), mock.patch("app.mutation_executor.verify_all", return_value=(True, [])), mock.patch("app.mutation_executor.journal.write_entry"), mock.patch(
            "app.mutation_executor.journal.append_tx"
        ), mock.patch("app.mutation_executor.metrics.log"):
            result = executor.execute(request)

        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["simulated"])
        dna_payload = json.loads((agent_dir / "dna.json").read_text(encoding="utf-8"))
        self.assertNotIn("lineage", dna_payload)


if __name__ == "__main__":
    unittest.main()
