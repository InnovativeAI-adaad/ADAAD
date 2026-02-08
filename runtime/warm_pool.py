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
from runtime.timeutils import now_iso
from security.ledger import journal

ELEMENT_ID = "Earth"
LEDGER_AGENT_ID = "warm_pool"


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
        self._active_tasks: dict[str, str | None] = {}
        self._active_lock = threading.Lock()

    def _emit_event(
        self,
        event_type: str,
        payload: dict[str, object] | None = None,
        level: str = "INFO",
    ) -> None:
        enriched = dict(payload or {})
        enriched.setdefault("queue_depth", self._tasks.qsize())
        enriched.setdefault("timestamp", now_iso())
        metrics.log(event_type=event_type, payload=enriched, level=level, element_id=ELEMENT_ID)
        journal.write_entry(agent_id=LEDGER_AGENT_ID, action=event_type, payload=enriched)

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
        if not self._ready_event.wait(timeout=2):
            self._emit_event(
                event_type="warm_pool_ready_timeout",
                payload={"task": None},
                level="WARN",
            )
        metrics.log(event_type="warm_pool_ready", payload={"threads": self.size}, level="INFO", element_id=ELEMENT_ID)
        self._started = True

    def _worker(self) -> None:
        self._emit_event(
            event_type="warm_pool_thread_start",
            payload={"task": None, "thread": threading.current_thread().name},
        )
        self._ready_event.set()
        try:
            while not self._stop_event.is_set():
                try:
                    task = self._tasks.get(timeout=0.1)
                except queue.Empty:
                    continue
                if self._stop_event.is_set():
                    self._emit_event(
                        event_type="warm_pool_task_skipped",
                        payload={"task": getattr(task, "__name__", "unknown")},
                    )
                    self._tasks.task_done()
                    continue
                task_name = getattr(task, "__name__", "unknown")
                with self._active_lock:
                    self._active_tasks[threading.current_thread().name] = task_name
                metrics.log(
                    event_type="warm_pool_task_start",
                    payload={"task": task_name, "queue_depth": self._tasks.qsize()},
                    level="INFO",
                    element_id=ELEMENT_ID,
                )
                task()
                metrics.log(
                    event_type="warm_pool_task_end",
                    payload={"task": task_name, "queue_depth": self._tasks.qsize()},
                    level="INFO",
                    element_id=ELEMENT_ID,
                )
                with self._active_lock:
                    self._active_tasks.pop(threading.current_thread().name, None)
                self._tasks.task_done()
        finally:
            self._emit_event(
                event_type="warm_pool_thread_stop",
                payload={"task": None, "thread": threading.current_thread().name},
            )

    def submit(self, task: Callable[[], None]) -> None:
        if self._stop_event.is_set():
            raise RuntimeError("WarmPool is stopped")
        try:
            self._tasks.put(task, block=True, timeout=1)
        except queue.Full:
            self._emit_event(
                event_type="warm_pool_submit_timeout",
                payload={"task": getattr(task, "__name__", "unknown")},
                level="WARN",
            )
            raise
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
        with self._active_lock:
            active_snapshot = dict(self._active_tasks)
        for task_name in active_snapshot.values():
            self._emit_event(
                event_type="warm_pool_task_unfinished",
                payload={"task": task_name},
                level="WARN",
            )
        while True:
            try:
                pending = self._tasks.get_nowait()
            except queue.Empty:
                break
            self._emit_event(
                event_type="warm_pool_task_skipped",
                payload={"task": getattr(pending, "__name__", "unknown")},
            )
            self._tasks.task_done()
        self._tasks.join()
        for thread in self._threads:
            thread.join(timeout=1)
            if thread.is_alive():
                with self._active_lock:
                    task_name = self._active_tasks.get(thread.name)
                self._emit_event(
                    event_type="warm_pool_thread_join_timeout",
                    payload={"task": task_name, "thread": thread.name},
                    level="WARN",
                )
                if task_name is not None:
                    self._emit_event(
                        event_type="warm_pool_task_unfinished",
                        payload={"task": task_name, "thread": thread.name},
                        level="WARN",
                    )
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
