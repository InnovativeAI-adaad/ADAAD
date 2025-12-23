import json
import tempfile
import unittest
from pathlib import Path

from app.agents.base_agent import promote_offspring, stage_offspring
from runtime import metrics


class StagingPromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

    def test_stage_then_promote(self) -> None:
        lineage_dir = Path(self.tmp.name) / "lineage"
        staged = stage_offspring("parent-agent", "hello-world", lineage_dir)
        self.assertTrue((staged / "mutation.json").exists())
        payload = json.loads((staged / "mutation.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["parent"], "parent-agent")

        promoted = promote_offspring(staged, lineage_dir)
        self.assertTrue(promoted.exists())
        self.assertFalse(staged.exists())
        self.assertTrue((promoted / "mutation.json").exists())


if __name__ == "__main__":
    unittest.main()
