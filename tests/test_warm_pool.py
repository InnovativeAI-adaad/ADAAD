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

import threading
import unittest

from runtime.warm_pool import WarmPool


class WarmPoolTest(unittest.TestCase):
    def test_stop_drains_tasks(self) -> None:
        pool = WarmPool(size=1)
        pool.start()

        task_started = threading.Event()
        release_task = threading.Event()
        executed = []

        def blocking_task() -> None:
            task_started.set()
            release_task.wait(timeout=0.5)

        def quick_task() -> None:
            executed.append("ran")

        pool.submit(blocking_task)
        self.assertTrue(task_started.wait(timeout=0.5))

        for _ in range(3):
            pool.submit(quick_task)

        threading.Timer(0.05, release_task.set).start()
        pool.stop()

        self.assertEqual(executed, [])

    def test_submit_after_stop_raises(self) -> None:
        pool = WarmPool(size=1)
        pool.start()
        pool.stop()

        def task() -> None:
            return

        with self.assertRaises(RuntimeError):
            pool.submit(task)

    def test_stop_allows_inflight_to_complete_and_skips_queued(self) -> None:
        pool = WarmPool(size=1)
        pool.start()

        first_started = threading.Event()
        release_first = threading.Event()
        finished = []

        def long_task() -> None:
            first_started.set()
            release_first.wait(timeout=0.5)
            finished.append("long")

        def queued_task() -> None:
            finished.append("queued")

        pool.submit(long_task)
        self.assertTrue(first_started.wait(timeout=0.5))
        for _ in range(2):
            pool.submit(queued_task)

        threading.Timer(0.05, release_first.set).start()
        pool.stop()

        # Only the inflight long_task should have run; queued tasks should be skipped.
        self.assertEqual(finished, ["long"])

if __name__ == "__main__":
    unittest.main()
