from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import require_audit_scope, require_gate_open

router = APIRouter()


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

    def run_epoch_task() -> None:
        env = os.environ.copy()
        env["ADAAD_ENV"] = "dev"
        env["ADAAD_CEL_ENABLED"] = "true"
        subprocess.run(
            [sys.executable, "-m", "app.main", "--verbose", "--exit-after-boot"],
            env=env,
            capture_output=True,
            text=True,
        )

    background_tasks.add_task(run_epoch_task)
    return {"ok": True, "status": "staged", "message": "Mutation cycle triggered."}
