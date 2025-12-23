# SPDX-License-Identifier: Apache-2.0
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

    def start(self) -> None:
        """
        Start warm threads and wait until they are ready.
        """
        for index in range(self.size):
            thread = threading.Thread(target=self._worker, name=f"warm-worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)
        self._ready_event.wait(timeout=2)
        metrics.log(event_type="warm_pool_ready", payload={"threads": self.size}, level="INFO", element_id=ELEMENT_ID)

    def _worker(self) -> None:
        self._ready_event.set()
        while not self._stop_event.is_set():
            try:
                task = self._tasks.get(timeout=0.1)
            except queue.Empty:
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
        self._tasks.put(task, block=True, timeout=1)
        metrics.log(
            event_type="warm_pool_queued",
            payload={"task": task.__name__, "queue_depth": self._tasks.qsize()},
            level="INFO",
            element_id=ELEMENT_ID,
        )

    def stop(self) -> None:
        self._stop_event.set()
        self._tasks.join()
        for thread in self._threads:
            thread.join(timeout=1)
        metrics.log(
            event_type="warm_pool_stopped",
            payload={"threads": len(self._threads)},
            level="INFO",
            element_id=ELEMENT_ID,
        )
