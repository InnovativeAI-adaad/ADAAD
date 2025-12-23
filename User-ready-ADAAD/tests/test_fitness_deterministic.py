# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path

from runtime import metrics
from runtime.fitness import score_mutation


class FitnessDeterministicTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

    def test_repeatable_score(self) -> None:
        payload = {"parent": "agent-1", "content": "mutation-data"}
        first = score_mutation("agent-1", payload)
        second = score_mutation("agent-1", payload)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
