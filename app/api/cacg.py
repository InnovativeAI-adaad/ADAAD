# SPDX-License-Identifier: Apache-2.0
"""
app/api/cacg.py
Phase 232 · INNOV-137 · CACG — Constitutional Autonomous Cycle Governor
FastAPI Router — 12 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 08 (capstone)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_autonomous_cycle_governor import (
    CACGEngine,
    CACGViolation,
    ChainBreakError,
    StageError,
    TimeoutStateError,
    EscalationError,
    HUMAN0ResolveError,
    ImmutabilityViolation,
)

router = APIRouter(prefix="/cacg", tags=["CACG"])

_engine = CACGEngine()


# ── Request models ────────────────────────────────────────────────────────────
class OpenCycleRequest(BaseModel):
    cycle_ref: str = Field(..., description="External mutation/cycle reference")


class AdvanceRequest(BaseModel):
    stage: str = Field(..., description="Next stage in fixed order (CACG-STAGE-0)")


class CheckTimeoutRequest(BaseModel):
    now: Optional[float] = Field(default=None, description="Injected timestamp for deterministic testing")


class ResolveRequest(BaseModel):
    resolved_by: str = Field(..., description="HUMAN-0 identity (CACG-HUMAN0-0)")
    note: str = Field(default="", description="Resolution note")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/cycle/open", summary="Open a new ACI cycle")
def open_cycle(req: OpenCycleRequest) -> Dict[str, Any]:
    """
    POST /cacg/cycle/open
    Open a new cycle at stage 0 (CASL). CACG-STAGE-0: cycle_ref non-empty.
    """
    try:
        return _engine.open_cycle(req.cycle_ref)
    except StageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CACGViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cycle/{cycle_id}/advance", summary="Advance a cycle to the next stage")
def advance(cycle_id: str, req: AdvanceRequest) -> Dict[str, Any]:
    """
    POST /cacg/cycle/{cycle_id}/advance
    CACG-STAGE-0: stage must be the next stage in fixed order.
    CACG-IMMUT-0: only OPEN cycles may advance.
    """
    try:
        return _engine.advance(cycle_id, req.stage)
    except StageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CACGViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cycle/{cycle_id}/complete", summary="Seal a cycle as COMPLETED")
def complete(cycle_id: str) -> Dict[str, Any]:
    """
    POST /cacg/cycle/{cycle_id}/complete
    Seal a cycle as COMPLETED once it has reached the final (CAMS) stage.
    """
    try:
        return _engine.complete(cycle_id)
    except StageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CACGViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/cycle/{cycle_id}/check-timeout", summary="Check a cycle for stage timeout")
def check_timeout(cycle_id: str, req: CheckTimeoutRequest) -> Dict[str, Any]:
    """
    POST /cacg/cycle/{cycle_id}/check-timeout
    CACG-TIMEOUT-0 / CACG-DETERM-0: deterministic stall detection.
    CACG-ESCALATE-0: TIMED_OUT raises exactly one escalation.
    """
    try:
        return _engine.check_timeout(cycle_id, now=req.now)
    except TimeoutStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except EscalationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except CACGViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/escalation/{escalation_id}/resolve", summary="HUMAN-0 resolve an escalation")
def resolve_escalation(escalation_id: str, req: ResolveRequest) -> Dict[str, Any]:
    """
    POST /cacg/escalation/{escalation_id}/resolve
    CACG-HUMAN0-0: resolved_by must be non-empty HUMAN-0 identity.
    CACG-IMMUT-0: only OPEN escalations may be resolved.
    """
    try:
        escalation = _engine.resolve_escalation(escalation_id, req.resolved_by, req.note)
    except HUMAN0ResolveError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CACGViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return escalation.to_dict()


@router.get("/cycle/{cycle_id}", summary="Retrieve a cycle record")
def get_cycle(cycle_id: str) -> Dict[str, Any]:
    record = _engine.get_cycle(cycle_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    return record.to_dict()


@router.get("/cycles", summary="List all cycles")
def list_cycles() -> Dict[str, Any]:
    cycles = _engine.all_cycles()
    return {"count": len(cycles), "cycles": [c.to_dict() for c in cycles]}


@router.get("/cycles/open", summary="List OPEN cycles")
def open_cycles() -> Dict[str, Any]:
    cycles = _engine.open_cycles()
    return {"count": len(cycles), "open": [c.to_dict() for c in cycles]}


@router.get("/escalations", summary="List all escalations")
def list_escalations() -> Dict[str, Any]:
    escalations = _engine.all_escalations()
    return {"count": len(escalations), "escalations": [e.to_dict() for e in escalations]}


@router.get("/verify-chain", summary="Verify cycle ledger HMAC chain")
def verify_chain() -> Dict[str, Any]:
    try:
        intact = _engine.verify_chain()
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"chain_intact": intact}


@router.get("/audit", summary="Retrieve CACG audit log")
def audit_log() -> Dict[str, Any]:
    entries = _engine.audit_log()
    return {"count": len(entries), "audit": entries}


@router.get("/status", summary="CACG module status")
def status() -> Dict[str, Any]:
    return _engine.status()
