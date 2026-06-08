# SPDX-License-Identifier: Apache-2.0
"""REST router for INNOV-116 · CIVR — Constitutional Invariant Violation Reporter."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional

from dorkllm.constitutional_invariant_violation_reporter import (
    ConstitutionalInvariantViolationReporter,
    ViolationSeverity,
)

router = APIRouter(prefix="/civr", tags=["civr"])
_reporter = ConstitutionalInvariantViolationReporter(phase=211)


class ReportRequest(BaseModel):
    invariant_code: str = Field(..., description="Dotted invariant identifier, e.g. CGPR-BUNDLE-0")
    severity: str = Field(..., description="CRITICAL / HIGH / MEDIUM / LOW")
    description: str = Field(..., description="Human-readable violation description")
    context: Optional[dict[str, Any]] = Field(default=None, description="Bounded key-value context (≤2 KB)")
    remediation_hint: Optional[str] = Field(default=None, description="Optional resolution guidance")


class WaiveRequest(BaseModel):
    violation_id: str = Field(..., description="violation_id of the record to waive")
    reason: str = Field(..., description="HUMAN-0 waiver justification")


@router.post("/report")
def report_violation(req: ReportRequest) -> dict:
    """Capture and seal a constitutional invariant violation event."""
    try:
        return _reporter.report(
            invariant_code=req.invariant_code,
            severity=req.severity,
            description=req.description,
            context=req.context or {},
            remediation_hint=req.remediation_hint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/waive")
def waive_violation(req: WaiveRequest) -> dict:
    """Record a HUMAN-0-authorised waiver for an existing violation record."""
    try:
        return _reporter.waive(violation_id=req.violation_id, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/history")
def violation_history(limit: int = 50) -> dict:
    """Return recent violation ledger entries (most-recent first)."""
    entries = _reporter.history(limit=min(limit, 200))
    return {"entries": entries, "count": len(entries)}


@router.get("/verify-chain")
def verify_chain() -> dict:
    """Verify HMAC chain integrity of the violation ledger."""
    return _reporter.verify_chain()


@router.get("/status")
def civr_status() -> dict:
    """Return CIVR subsystem status summary."""
    return _reporter.status()
