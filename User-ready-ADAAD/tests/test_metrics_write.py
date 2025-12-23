# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.append(str(ROOT))

from runtime import metrics  # noqa: E402


class MetricsWriteTest(unittest.TestCase):
    def test_metrics_append(self):
        metrics.log(event_type="unittest_probe", payload={"ok": True}, level="INFO")
        entries = metrics.tail(limit=5)
        self.assertTrue(any(entry.get("event") == "unittest_probe" for entry in entries))


if __name__ == "__main__":
    unittest.main()
