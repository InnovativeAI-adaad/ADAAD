# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from adaad.orchestrator.contracts import StatusEnvelope


class MutationOrchestrationService:
    """Owns mutation enablement, queueing, and worker dispatch decisions."""

    _RUN_CYCLE_FALSE = {"run_cycle": False}

    def __init__(self, *, queue_store: Any = None, orchestrator: Any = None) -> None:
        self._queue = queue_store
        self._orchestrator = orchestrator

    @classmethod
    def _blocked_payload(cls) -> dict[str, bool]:
        return cls._RUN_CYCLE_FALSE.copy()

    @staticmethod
    def _normalize_tasks(tasks: Sequence[str] | Iterable[object]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for task in tasks:
            if not isinstance(task, str):
                continue
            candidate = task.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return tuple(normalized)

    def evaluate_dream_tasks(self, tasks: Sequence[str] | Iterable[object] | None) -> StatusEnvelope:
        if tasks is None or isinstance(tasks, (str, bytes)):
            return StatusEnvelope(
                status="warn",
                reason="invalid_tasks_payload",
                evidence_refs=("dream.discover_tasks",),
                payload={"safe_boot": True},
            )

        try:
            iterator = iter(tasks)
        except TypeError:
            return StatusEnvelope(
                status="warn",
                reason="invalid_tasks_payload",
                evidence_refs=("dream.discover_tasks",),
                payload={"safe_boot": True},
            )

        normalized_tasks = self._normalize_tasks(iterator)
        if not normalized_tasks:
            return StatusEnvelope(status="warn", reason="no_tasks", evidence_refs=("dream.discover_tasks",), payload={"safe_boot": True})
        return StatusEnvelope(
            status="ok",
            reason="tasks_ready",
            evidence_refs=("dream.discover_tasks",),
            payload={"safe_boot": False, "task_count": len(normalized_tasks)},
        )

    def choose_transition(
        self,
        *,
        mutation_enabled: bool,
        fail_closed: bool,
        governance_gate_passed: bool,
        exit_after_boot: bool,
    ) -> StatusEnvelope:
        if not mutation_enabled:
            return StatusEnvelope(status="ok", reason="mutation_disabled", payload=self._blocked_payload())
        if fail_closed:
            return StatusEnvelope(status="warn", reason="mutation_blocked_fail_closed", payload=self._blocked_payload())
        if not governance_gate_passed:
            return StatusEnvelope(status="warn", reason="governance_gate_failed", payload=self._blocked_payload())
        if exit_after_boot:
            return StatusEnvelope(status="ok", reason="exit_after_boot", payload={"run_cycle": False, "mutation_cycle_skipped": "exit_after_boot"})
        return StatusEnvelope(status="ok", reason="run_mutation_cycle", payload={"run_cycle": True})

    def enqueue_mutation_job(
        self,
        payload: dict[str, Any],
        *,
        dedupe_key: str = "",
        max_attempts: int = 3,
        now_ts: float | None = None,
    ) -> StatusEnvelope:
        if self._queue is None:
            return StatusEnvelope(status="warn", reason="job_queue_unavailable", payload={"enqueued": False})
        job = self._queue.enqueue(payload, dedupe_key=dedupe_key, max_attempts=max_attempts, now_ts=now_ts)
        return StatusEnvelope(status="ok", reason="job_enqueued", payload={"enqueued": True, "job_id": job["job_id"], "state": job["state"]})

    def dispatch_next_job(self, *, worker_id: str, now_ts: float | None = None) -> StatusEnvelope:
        if self._orchestrator is None:
            return StatusEnvelope(status="warn", reason="orchestrator_unavailable", payload={"dispatched": False})
        leased = self._orchestrator.lease_next_job(worker_id=worker_id, now_ts=now_ts)
        if leased is None:
            return StatusEnvelope(status="ok", reason="no_queued_jobs", payload={"dispatched": False})
        marked = self._queue.mark_running(job_id=leased["job_id"], worker_id=worker_id, now_ts=now_ts)
        if not marked:
            return StatusEnvelope(
                status="warn",
                reason="job_dispatch_conflict",
                payload={"dispatched": False, "job_id": leased["job_id"], "worker_id": worker_id},
            )
        return StatusEnvelope(
            status="ok",
            reason="job_dispatched",
            payload={
                "dispatched": True,
                "job_id": leased["job_id"],
                "state": "running",
                "worker_id": worker_id,
                "lease_id": leased.get("lease_id", ""),
                "lease_expires_at": leased.get("lease_expires_at"),
            },
        )

    def retry_job(self, *, job_id: str, now_ts: float | None = None) -> StatusEnvelope:
        if self._queue is None:
            return StatusEnvelope(status="warn", reason="job_queue_unavailable", payload={"retried": False})
        job = self._queue.retry(job_id, now_ts=now_ts)
        if job is None:
            return StatusEnvelope(status="warn", reason="job_not_found", payload={"retried": False})
        return StatusEnvelope(status="ok", reason="job_retry_evaluated", payload={"retried": job["state"] == "queued", "state": job["state"]})
