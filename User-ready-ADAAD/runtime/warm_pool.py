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

"""
Lightweight warm-pool implementation for pre-initializing threads.
Termux-safe and avoids heavy dependencies.
"""

import queue
import threading
import time
from typing import Callable, List

from runtime import metrics

ELEMENT_ID = "Earth"


class WarmPool:
    """
    Maintain a pool of warm threads ready to execute work.
    """

    def __init__(self, size: int = 2):
        self.size = max(1, size)
        self._threads: List[threading.Thread] = []
        self._ready_event = threading.Event()
        self._stop_event = threading.Event()
        self._tasks: "queue.Queue[Callable[[], None]]" = queue.Queue(maxsize=size * 4)
        self._started = False

    def start(self) -> None:
        """
        Start warm threads and wait until they are ready.
        """
        if self._started:
            return
        for index in range(self.size):
            thread = threading.Thread(target=self._worker, name=f"warm-worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)
        self._ready_event.wait(timeout=2)
        metrics.log(event_type="warm_pool_ready", payload={"threads": self.size}, level="INFO", element_id=ELEMENT_ID)
        self._started = True

    def _worker(self) -> None:
        self._ready_event.set()
        while not self._stop_event.is_set():
            try:
                task = self._tasks.get(timeout=0.1)
            except queue.Empty:
                continue
            if self._stop_event.is_set():
                metrics.log(
                    event_type="warm_pool_task_skipped",
                    payload={"task": getattr(task, "__name__", "unknown"), "queue_depth": self._tasks.qsize()},
                    level="INFO",
                    element_id=ELEMENT_ID,
                )
                self._tasks.task_done()
                continue
            metrics.log(
                event_type="warm_pool_task_start",
                payload={"task": task.__name__, "queue_depth": self._tasks.qsize()},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            task()
            metrics.log(
                event_type="warm_pool_task_end",
                payload={"task": task.__name__, "queue_depth": self._tasks.qsize()},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            self._tasks.task_done()

    def submit(self, task: Callable[[], None]) -> None:
        if self._stop_event.is_set():
            raise RuntimeError("WarmPool is stopped")
        self._tasks.put(task, block=True, timeout=1)
        # Warn when approaching queue capacity.
        if self._tasks.qsize() > (self._tasks.maxsize * 0.75):
            metrics.log(
                event_type="warm_pool_queue_pressure",
                payload={"queue_depth": self._tasks.qsize(), "queue_max": self._tasks.maxsize},
                level="WARN",
                element_id=ELEMENT_ID,
            )
        metrics.log(
            event_type="warm_pool_queued",
            payload={"task": task.__name__, "queue_depth": self._tasks.qsize()},
            level="INFO",
            element_id=ELEMENT_ID,
        )

    def stop(self) -> None:
        self._stop_event.set()
        while True:
            try:
                pending = self._tasks.get_nowait()
            except queue.Empty:
                break
            metrics.log(
                event_type="warm_pool_task_skipped",
                payload={"task": getattr(pending, "__name__", "unknown"), "queue_depth": self._tasks.qsize()},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            self._tasks.task_done()
        self._tasks.join()
        for thread in self._threads:
            thread.join(timeout=1)
        metrics.log(
            event_type="warm_pool_stopped",
            payload={"threads": len(self._threads)},
            level="INFO",
            element_id=ELEMENT_ID,
        )

    def __enter__(self) -> "WarmPool":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
