# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
import pytest
pytestmark = pytest.mark.regression_standard

import json
from pathlib import Path
from unittest import mock

from app.orchestration import MutationOrchestrationService
from runtime.boot.preflight import BootPreflightService
from runtime.evolution.replay_mode import ReplayMode
from runtime.evolution.replay_service import ReplayVerificationService


def test_boot_preflight_returns_typed_envelope() -> None:
    service = BootPreflightService()
    with mock.patch("runtime.boot.preflight.run_gatekeeper", return_value={"ok": False, "missing": ["ledger"]}):
        envelope = service.validate_gatekeeper()
    assert envelope.status == "error"
    assert envelope.reason == "gatekeeper_failed:ledger"
    assert envelope.evidence_refs


def test_replay_service_contract_envelope_and_manifest(tmp_path: Path) -> None:
    runtime = mock.Mock()
    runtime.replay_preflight.return_value = {
        "verify_target": "epoch-1",
        "decision": "continue",
        "has_divergence": False,
        "results": [{"replay_score": 1.0}],
    }
    service = ReplayVerificationService(manifests_dir=tmp_path / "adaad" / "replay" / "manifests")
    with mock.patch("runtime.evolution.replay_service.journal.write_entry"):
        envelope, preflight = service.run_preflight(
            evolution_runtime=runtime,
            replay_mode=ReplayMode.AUDIT,
            replay_epoch="epoch-1",
        )
    assert envelope.status == "ok"
    assert envelope.reason == "replay_verified"
    assert Path(envelope.evidence_refs[0]).exists()
    assert preflight["verify_target"] == "epoch-1"
    manifest_payload = json.loads(Path(envelope.evidence_refs[0]).read_text(encoding="utf-8"))
    assert "replay_started_at" in manifest_payload
    assert "replay_finished_at" in manifest_payload
    assert "evidence_items_consumed" in manifest_payload
    assert "lineage_chain" in manifest_payload
    assert "reconstructed_state_hash" in manifest_payload
    assert "divergence" in manifest_payload
    assert "algorithm" in manifest_payload
    assert "key_id" in manifest_payload
    assert "signature" in manifest_payload


def test_mutation_orchestration_transition_contract() -> None:
    service = MutationOrchestrationService()
    blocked = service.choose_transition(
        mutation_enabled=True,
        fail_closed=True,
        governance_gate_passed=True,
        exit_after_boot=False,
    )
    assert blocked.reason == "mutation_blocked_fail_closed"
    assert blocked.payload["run_cycle"] is False


def test_mutation_orchestration_normalizes_empty_and_duplicate_tasks() -> None:
    service = MutationOrchestrationService()
    envelope = service.evaluate_dream_tasks(["", "  ", "task-a", "task-a", " task-b "])

    assert envelope.status == "ok"
    assert envelope.payload["safe_boot"] is False
    assert envelope.payload["task_count"] == 2


def test_mutation_orchestration_warns_when_tasks_collapse_to_empty() -> None:
    service = MutationOrchestrationService()
    envelope = service.evaluate_dream_tasks(["  ", "", "\n"])

    assert envelope.status == "warn"
    assert envelope.reason == "no_tasks"
    assert envelope.payload == {"safe_boot": True}


def test_mutation_orchestration_warns_on_none_payload() -> None:
    service = MutationOrchestrationService()

    envelope = service.evaluate_dream_tasks(None)

    assert envelope.status == "warn"
    assert envelope.reason == "invalid_tasks_payload"
    assert envelope.evidence_refs == ("dream.discover_tasks",)
    assert envelope.payload == {"safe_boot": True}


def test_mutation_orchestration_warns_on_non_iterable_payload() -> None:
    service = MutationOrchestrationService()

    envelope = service.evaluate_dream_tasks(42)  # type: ignore[arg-type]

    assert envelope.status == "warn"
    assert envelope.reason == "invalid_tasks_payload"
    assert envelope.evidence_refs == ("dream.discover_tasks",)
    assert envelope.payload == {"safe_boot": True}


def test_mutation_orchestration_accepts_iterator_payload_deterministically() -> None:
    service = MutationOrchestrationService()

    envelope = service.evaluate_dream_tasks(iter([" task-a ", "task-b", "task-a", ""]))

    assert envelope.status == "ok"
    assert envelope.reason == "tasks_ready"
    assert envelope.payload == {"safe_boot": False, "task_count": 2}



def test_mutation_orchestration_ignores_non_string_tasks_deterministically() -> None:
    service = MutationOrchestrationService()
    envelope = service.evaluate_dream_tasks(["task-a", 7, None, " task-b "])  # type: ignore[list-item]

    assert envelope.status == "ok"
    assert envelope.payload["safe_boot"] is False
    assert envelope.payload["task_count"] == 2



def test_mutation_orchestration_preserves_first_seen_order_for_large_input() -> None:
    service = MutationOrchestrationService()
    tasks = [f"task-{idx % 10}" for idx in range(200)]

    envelope = service.evaluate_dream_tasks(tasks)

    assert envelope.status == "ok"
    assert envelope.payload["task_count"] == 10


def test_mutation_orchestration_supports_unicode_labels_deterministically() -> None:
    service = MutationOrchestrationService()
    envelope = service.evaluate_dream_tasks([" α ", "β", "α", "β", "γ"])

    assert envelope.status == "ok"
    assert envelope.payload["safe_boot"] is False
    assert envelope.payload["task_count"] == 3



def test_mutation_orchestration_blocked_payload_isolation() -> None:
    service = MutationOrchestrationService()

    first = service.choose_transition(
        mutation_enabled=False,
        fail_closed=False,
        governance_gate_passed=True,
        exit_after_boot=False,
    )
    first.payload["run_cycle"] = True

    second = service.choose_transition(
        mutation_enabled=False,
        fail_closed=False,
        governance_gate_passed=True,
        exit_after_boot=False,
    )
    assert second.payload == {"run_cycle": False}


def test_mutation_orchestration_enqueue_and_dispatch_idempotent(tmp_path: Path) -> None:
    from runtime.state.mutation_job_queue import MutationJobQueueStore
    from runtime.sandbox.container_orchestrator import ContainerOrchestrator

    queue = MutationJobQueueStore(tmp_path / "jobs.json", backend="json")
    orchestrator = ContainerOrchestrator(job_queue=queue)
    service = MutationOrchestrationService(queue_store=queue, orchestrator=orchestrator)

    payload = {"mutation": "m-9", "epoch": "e-9"}
    first = service.enqueue_mutation_job(payload, dedupe_key="demo", now_ts=1.0)
    second = service.enqueue_mutation_job(payload, dedupe_key="demo", now_ts=2.0)
    dispatched = service.dispatch_next_job(worker_id="worker-1", now_ts=3.0)
    duplicate_dispatch = service.dispatch_next_job(worker_id="worker-2", now_ts=3.1)

    assert first.payload["job_id"] == second.payload["job_id"]
    assert dispatched.reason == "job_dispatched"
    assert duplicate_dispatch.reason == "no_queued_jobs"


def test_mutation_orchestration_worker_crash_recovery_retry(tmp_path: Path) -> None:
    from runtime.state.mutation_job_queue import MutationJobQueueStore
    from runtime.sandbox.container_orchestrator import ContainerOrchestrator

    queue = MutationJobQueueStore(tmp_path / "jobs.json", backend="json", lease_timeout_s=5)
    orchestrator = ContainerOrchestrator(job_queue=queue)
    service = MutationOrchestrationService(queue_store=queue, orchestrator=orchestrator)

    enqueued = service.enqueue_mutation_job({"mutation": "m-crash"}, now_ts=10.0)
    job_id = enqueued.payload["job_id"]
    service.dispatch_next_job(worker_id="worker-a", now_ts=11.0)

    recovered = queue.recover_orphans(now_ts=20.0)
    assert job_id in recovered
    assert queue.get(job_id)["state"] == "queued"


def test_orchestrator_heartbeat_updates_explicit_lease_fields(tmp_path: Path) -> None:
    from runtime.state.mutation_job_queue import MutationJobQueueStore
    from runtime.sandbox.container_orchestrator import ContainerOrchestrator

    events: list[tuple[str, dict[str, object]]] = []
    queue = MutationJobQueueStore(tmp_path / "jobs.json", backend="json", lease_timeout_s=10)
    queue.enqueue({"mutation": "m-heartbeat"}, now_ts=1.0)
    orchestrator = ContainerOrchestrator(job_queue=queue, journal_fn=lambda t, p: events.append((t, p)))

    leased = orchestrator.lease_next_job(worker_id="worker-a", now_ts=2.0)
    assert leased is not None
    assert orchestrator.heartbeat_job(job_id=leased["job_id"], worker_id="worker-a", now_ts=5.0)

    heartbeat_events = [payload for et, payload in events if et == "mutation_job_heartbeat.v1"]
    assert heartbeat_events
    assert heartbeat_events[-1]["lease_expires_at"] == 15.0
    assert heartbeat_events[-1]["heartbeat_at"] == 5.0


def test_mutation_orchestration_exactly_once_completion(tmp_path: Path) -> None:
    from runtime.state.mutation_job_queue import MutationJobQueueStore
    from runtime.sandbox.container_orchestrator import ContainerOrchestrator

    queue = MutationJobQueueStore(tmp_path / "jobs.json", backend="json", lease_timeout_s=5)
    orchestrator = ContainerOrchestrator(job_queue=queue)
    service = MutationOrchestrationService(queue_store=queue, orchestrator=orchestrator)

    enqueued = service.enqueue_mutation_job({"mutation": "m-once"}, now_ts=1.0)
    job_id = enqueued.payload["job_id"]
    service.dispatch_next_job(worker_id="worker-a", now_ts=2.0)

    assert orchestrator.complete_job(job_id=job_id, succeeded=True, worker_id="worker-a", now_ts=3.0)
    assert not orchestrator.complete_job(job_id=job_id, succeeded=False, worker_id="worker-b", now_ts=3.5)
    assert queue.get(job_id)["state"] == "succeeded"
