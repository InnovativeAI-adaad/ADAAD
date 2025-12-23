# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path

from runtime import metrics
from runtime import capability_graph


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
        )
        self.assertFalse(ok)
        self.assertIn("missing dependencies", message)


if __name__ == "__main__":
    unittest.main()
