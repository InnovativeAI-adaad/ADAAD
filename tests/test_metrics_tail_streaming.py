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
from pathlib import Path

from runtime import metrics


class MetricsTailStreamingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

    def test_tail_reads_only_last_entries(self) -> None:
        metrics.METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with metrics.METRICS_PATH.open("w", encoding="utf-8") as handle:
            for idx in range(5000):
                handle.write(json.dumps({"event": f"e{idx}", "idx": idx}) + "\n")

        lines, bytes_read = metrics._read_last_lines(metrics.METRICS_PATH, limit=5, chunk_size=256)
        self.assertEqual(len(lines), 5)
        self.assertLess(bytes_read, metrics.METRICS_PATH.stat().st_size)
        self.assertEqual([json.loads(line)["idx"] for line in lines], [4995, 4996, 4997, 4998, 4999])

        entries = metrics.tail(limit=5)
        self.assertEqual([entry["idx"] for entry in entries], [4995, 4996, 4997, 4998, 4999])


if __name__ == "__main__":
    unittest.main()
