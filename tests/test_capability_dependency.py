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
import threading
import unittest
from pathlib import Path
from unittest import mock

from runtime import capability_graph
from runtime.manifest.generator import generate_tool_manifest
from runtime import metrics


class CapabilityDependencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)
        self._orig_capabilities_path = capability_graph.CAPABILITIES_PATH
        capability_graph.CAPABILITIES_PATH = Path(self.tmp.name) / "capabilities.json"
        self.addCleanup(setattr, capability_graph, "CAPABILITIES_PATH", self._orig_capabilities_path)

    def test_missing_dependencies_rejected(self) -> None:
        ok, message = capability_graph.register_capability(
            name="agent.sample",
            version="1.0.0",
            score=0.5,
            owner_element="test",
            requires=["missing.capability"],
            identity=generate_tool_manifest(__name__, "agent.sample", "1.0.0"),
        )
        self.assertFalse(ok)
        self.assertIn("missing dependencies", message)

    def test_concurrent_register_capability_has_no_lost_records(self) -> None:
        start_barrier = threading.Barrier(2)
        original_load = capability_graph._load
        calls_by_thread: dict[int, int] = {}
        calls_lock = threading.Lock()

        def synchronized_load() -> dict[str, dict[str, object]]:
            thread_id = threading.get_ident()
            with calls_lock:
                calls_by_thread[thread_id] = calls_by_thread.get(thread_id, 0) + 1
                first_call = calls_by_thread[thread_id] == 1
            if first_call:
                start_barrier.wait(timeout=2)
            return original_load()

        results: list[tuple[bool, str]] = []

        def register(name: str) -> None:
            outcome = capability_graph.register_capability(name, "1.0.0", 1.0, "thread-test", identity=generate_tool_manifest(__name__, name, "1.0.0"))
            results.append(outcome)

        with mock.patch.object(capability_graph, "_load", side_effect=synchronized_load):
            thread_a = threading.Thread(target=register, args=("cap.alpha",))
            thread_b = threading.Thread(target=register, args=("cap.beta",))
            thread_a.start()
            thread_b.start()
            thread_a.join(timeout=3)
            thread_b.join(timeout=3)

        self.assertFalse(thread_a.is_alive())
        self.assertFalse(thread_b.is_alive())
        self.assertEqual(len(results), 2)
        self.assertTrue(all(ok for ok, _ in results))

        registry = capability_graph.get_capabilities()
        self.assertIn("cap.alpha", registry)
        self.assertIn("cap.beta", registry)

        metric_entries = [json.loads(line) for line in metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines()]
        conflict_events = [entry for entry in metric_entries if entry.get("event") == "capability_graph_conflict"]
        self.assertTrue(conflict_events)
        outcomes = {entry.get("payload", {}).get("outcome") for entry in conflict_events}
        self.assertIn("commit_success", outcomes)
        self.assertIn("conflict_detected", outcomes)


if __name__ == "__main__":
    unittest.main()
