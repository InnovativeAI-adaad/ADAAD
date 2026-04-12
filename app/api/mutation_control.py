from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import require_audit_scope, require_gate_open

router = APIRouter()


def _server_module() -> Any:
    return importlib.import_module("server")


@router.get("/api/governance/approvals/pending")
async def get_pending_approvals(
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    _ = auth_ctx
    from runtime.governance.human_approval_gate import HumanApprovalGate

    gate = HumanApprovalGate()
    return {"ok": True, "pending": gate.pending_queue()}


@router.get("/api/governance/merges")
async def get_recent_merges(
    limit: int = 20,
) -> dict[str, Any]:
    _ = limit
    mock_merges = [
        {
            "event_type": "merge_attestation.v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "pr_id": "PR-PHASE108-01",
                "merge_sha": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
                "tier_0_digest": "sha256:1234567890abcdef",
                "tier_1_tests_passed": 1050,
                "tier_1_tests_failed": 0,
                "tier_3_evidence_complete": True,
                "tier_m_working_code": True,
                "triggered_by": "DEVADAAD",
            },
        }
    ]
    return {"ok": True, "merges": mock_merges, "count": len(mock_merges)}


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    operator_id: str
    notes: str = ""


@router.post("/api/governance/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    auth_ctx: dict[str, Any] = Depends(require_audit_scope),
) -> dict[str, Any]:
    _ = auth_ctx
    from runtime.governance.human_approval_gate import HumanApprovalGate

    gate = HumanApprovalGate()
    try:
        decision = gate.record_decision(
            approval_id=approval_id,
            approved=body.approved,
            operator_id=body.operator_id,
            notes=body.notes,
        )
        return {"ok": True, "decision": decision.to_payload()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/mutations/trigger-epoch")
async def trigger_mutation_cycle(
    background_tasks: BackgroundTasks,
    auth_ctx: dict[str, Any] = Depends(require_gate_open),
) -> dict[str, Any]:
    _ = auth_ctx
    srv = _server_module()

    operation_id = f"epoch-op-{uuid.uuid4().hex[:16]}"
    srv.MUTATION_EPOCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = srv.MUTATION_EPOCH_LOG_DIR / f"{operation_id}.stdout.log"
    stderr_path = srv.MUTATION_EPOCH_LOG_DIR / f"{operation_id}.stderr.log"
    queued_at = datetime.now(timezone.utc).isoformat()
    srv._record_mutation_epoch_status(
        operation_id,
        {
            "status": "queued",
            "queued_at": queued_at,
            "completed_at": None,
            "timeout_seconds": srv._MUTATION_EPOCH_TIMEOUT_SECONDS,
            "timed_out": False,
            "return_code": None,
            "stdout_log_path": str(stdout_path),
            "stderr_log_path": str(stderr_path),
            "stdout_digest_sha256": "",
            "stderr_digest_sha256": "",
            "stdout_truncated_bytes": 0,
            "stderr_truncated_bytes": 0,
            "error_type": None,
        },
    )

    def run_epoch_task(epoch_operation_id: str, task_stdout_path: Path, task_stderr_path: Path) -> None:
        env = os.environ.copy()
        env["ADAAD_ENV"] = "dev"
        env["ADAAD_CEL_ENABLED"] = "true"
        started_at = datetime.now(timezone.utc).isoformat()
        srv._record_mutation_epoch_status(
            epoch_operation_id,
            {
                "status": "running",
                "queued_at": queued_at,
                "started_at": started_at,
                "completed_at": None,
                "timeout_seconds": srv._MUTATION_EPOCH_TIMEOUT_SECONDS,
                "timed_out": False,
                "return_code": None,
                "stdout_log_path": str(task_stdout_path),
                "stderr_log_path": str(task_stderr_path),
                "stdout_digest_sha256": "",
                "stderr_digest_sha256": "",
                "stdout_truncated_bytes": 0,
                "stderr_truncated_bytes": 0,
                "error_type": None,
            },
        )

        with task_stdout_path.open("w", encoding="utf-8") as stdout_handle, task_stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_handle:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "app.main", "--verbose", "--exit-after-boot"],
                    env=env,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    check=True,
                    timeout=srv._MUTATION_EPOCH_TIMEOUT_SECONDS,
                )
                status = "succeeded"
                timed_out = False
                error_type = None
                return_code = result.returncode
            except subprocess.TimeoutExpired as exc:
                status = "failed"
                timed_out = True
                error_type = "TimeoutExpired"
                return_code = exc.returncode if exc.returncode is not None else -1
            except subprocess.CalledProcessError as exc:
                status = "failed"
                timed_out = False
                error_type = "CalledProcessError"
                return_code = exc.returncode

        stdout_truncated_bytes = srv._truncate_log_file_in_place(task_stdout_path, srv._MUTATION_STDIO_LOG_LIMIT_BYTES)
        stderr_truncated_bytes = srv._truncate_log_file_in_place(task_stderr_path, srv._MUTATION_STDIO_LOG_LIMIT_BYTES)
        stdout_digest = srv._digest_for_path(task_stdout_path)
        stderr_digest = srv._digest_for_path(task_stderr_path)
        completed_at = datetime.now(timezone.utc).isoformat()

        payload = {
            "operation_id": epoch_operation_id,
            "status": status,
            "queued_at": queued_at,
            "started_at": started_at,
            "completed_at": completed_at,
            "timeout_seconds": srv._MUTATION_EPOCH_TIMEOUT_SECONDS,
            "timed_out": timed_out,
            "return_code": return_code,
            "stdout_log_path": str(task_stdout_path),
            "stderr_log_path": str(task_stderr_path),
            "stdout_digest_sha256": stdout_digest,
            "stderr_digest_sha256": stderr_digest,
            "stdout_truncated_bytes": stdout_truncated_bytes,
            "stderr_truncated_bytes": stderr_truncated_bytes,
            "error_type": error_type,
        }

        srv.metrics.log(
            event_type="mutation_epoch_task_completed",
            payload=payload,
            level="INFO" if status == "succeeded" else "ERROR",
        )
        srv.journal.append_tx(
            tx_type="mutation_epoch_task_completed.v1",
            payload=payload,
        )
        srv._record_mutation_epoch_status(epoch_operation_id, payload)

    background_tasks.add_task(run_epoch_task, operation_id, stdout_path, stderr_path)
    return {
        "ok": True,
        "status": "staged",
        "operation_id": operation_id,
        "message": "Mutation cycle triggered.",
        "status_endpoint": f"/api/mutations/epoch-status/{operation_id}",
    }
