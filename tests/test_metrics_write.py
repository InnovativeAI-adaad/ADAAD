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
import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path

from runtime import metrics


def _process_worker(metrics_path: str, worker_id: int, count: int) -> None:
    metrics.METRICS_PATH = Path(metrics_path)
    for idx in range(count):
        metrics.log(event_type="proc_probe", payload={"worker": worker_id, "idx": idx, "text": "こんにちは"}, level="INFO")


class MetricsWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_metrics_path = metrics.METRICS_PATH
        metrics.METRICS_PATH = Path(self.tmp.name) / "metrics.jsonl"
        self.addCleanup(setattr, metrics, "METRICS_PATH", self._orig_metrics_path)

    def test_metrics_append(self) -> None:
        metrics.log(event_type="unittest_probe", payload={"ok": True}, level="INFO")
        entries = metrics.tail(limit=5)
        self.assertTrue(any(entry.get("event") == "unittest_probe" for entry in entries))

    def test_concurrent_thread_and_process_writes_produce_valid_jsonl(self) -> None:
        thread_workers = 8
        process_workers = 4
        per_worker = 60

        def thread_worker(worker_id: int) -> None:
            for idx in range(per_worker):
                metrics.log(
                    event_type="thread_probe",
                    payload={"worker": worker_id, "idx": idx, "text": "🙂"},
                    level="INFO",
                )

        threads = [threading.Thread(target=thread_worker, args=(i,)) for i in range(thread_workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        ctx = multiprocessing.get_context("spawn")
        procs = [
            ctx.Process(target=_process_worker, args=(str(metrics.METRICS_PATH), i, per_worker)) for i in range(process_workers)
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=20)
            self.assertEqual(proc.exitcode, 0)

        raw_lines = metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines()
        expected = (thread_workers + process_workers) * per_worker
        self.assertEqual(len(raw_lines), expected)

        parsed = [json.loads(line) for line in raw_lines]
        self.assertEqual(len(parsed), expected)
        self.assertTrue(all("event" in rec and "payload" in rec for rec in parsed))


if __name__ == "__main__":
    unittest.main()
