# SPDX-License-Identifier: Apache-2.0
"""
app/api/cave.py
Phase 230 · INNOV-135 · CAVE — Constitutional Autonomous Verdict Executor
FastAPI Router — 11 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 06
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_autonomous_verdict_executor import (
    CAVEEngine,
    CAVEViolation,
    ChainBreakError,
    ImmutabilityViolation,
    ScopeViolation,
    QuarantineError,
    ReEvalError,
    HUMAN0ReleaseError,
    OriginViolation,
)

router = APIRouter(prefix="/cave", tags=["CAVE"])

_engine = CAVEEngine()


# ── Request models ────────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    cade_record_id: str = Field(..., description="CADE decision record_id (CAVE-ORIGIN-0)")
    verdict: str = Field(..., description="HOLD | REJECT | DEFER (CAVE-SCOPE-0)")
    mutation_ref: str = Field(..., description="Mutation identifier")
    chi_score: float = Field(..., ge=0.0, le=1.0, description="CHI score from CADE")


class ReleaseRequest(BaseModel):
    released_by: str = Field(..., description="HUMAN-0 identity (CAVE-HUMAN0-0)")
    reason: str = Field(..., description="Reason for quarantine release")


class ReEvalCompleteRequest(BaseModel):
    new_chi: float = Field(..., ge=0.0, le=1.0, description="New CHI score post re-evaluation")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/execute", summary="Execute a HOLD/REJECT/DEFER verdict")
def execute(req: ExecuteRequest) -> Dict[str, Any]:
    """
    POST /cave/execute
    Route a CADE HOLD/REJECT/DEFER verdict through the enforcement pipeline.
    CAVE-ORIGIN-0: cade_record_id must be non-empty.
    CAVE-SCOPE-0: verdict must be HOLD, REJECT, or DEFER.
    CAVE-QUARANTINE-0: REJECT/DEFER sealed into quarantine ledger.
    CAVE-REEVAL-0: HOLD produces CHI re-eval trigger.
    CAVE-CHAIN-0: ledger appended with chain verification.
    """
    try:
        return _engine.execute(
            cade_record_id=req.cade_record_id,
            verdict=req.verdict,
            mutation_ref=req.mutation_ref,
            chi_score=req.chi_score,
        )
    except OriginViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ScopeViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CAVEViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/release/{record_id}", summary="HUMAN-0 release a quarantined record")
def release_quarantine(record_id: str, req: ReleaseRequest) -> Dict[str, Any]:
    """
    POST /cave/release/{record_id}
    HUMAN-0 release of a quarantined REJECT/DEFER record.
    CAVE-HUMAN0-0: released_by must be non-empty HUMAN-0 identity.
    CAVE-IMMUT-0: only SEALED records may be released.
    """
    try:
        record = _engine.release_quarantine(record_id, req.released_by, req.reason)
    except HUMAN0ReleaseError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CAVEViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return record.to_dict()


@router.post("/reeval/{trigger_id}/complete", summary="Complete a CHI re-eval trigger")
def complete_reeval(trigger_id: str, req: ReEvalCompleteRequest) -> Dict[str, Any]:
    """
    POST /cave/reeval/{trigger_id}/complete
    Mark a HOLD-originated CHI re-evaluation trigger as completed.
    CAVE-REEVAL-0: trigger must exist and be PENDING.
    """
    try:
        trigger = _engine.complete_reeval(trigger_id, req.new_chi)
    except ReEvalError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CAVEViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return trigger.to_dict()


@router.get("/record/{record_id}", summary="Retrieve a verdict record")
def get_record(record_id: str) -> Dict[str, Any]:
    record = _engine.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    return record.to_dict()


@router.get("/records", summary="List all verdict records")
def list_records() -> Dict[str, Any]:
    records = _engine.all_records()
    return {"count": len(records), "records": [r.to_dict() for r in records]}


@router.get("/quarantined", summary="List SEALED quarantine records")
def quarantined() -> Dict[str, Any]:
    records = _engine.quarantined_records()
    return {"count": len(records), "quarantined": [r.to_dict() for r in records]}


@router.get("/trigger/{trigger_id}", summary="Retrieve a re-eval trigger")
def get_trigger(trigger_id: str) -> Dict[str, Any]:
    trigger = _engine.get_trigger(trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")
    return trigger.to_dict()


@router.get("/triggers", summary="List all re-eval triggers")
def list_triggers() -> Dict[str, Any]:
    triggers = _engine.all_triggers()
    return {"count": len(triggers), "triggers": [t.to_dict() for t in triggers]}


@router.get("/triggers/pending", summary="List pending re-eval triggers")
def pending_triggers() -> Dict[str, Any]:
    triggers = _engine.pending_triggers()
    return {"count": len(triggers), "pending": [t.to_dict() for t in triggers]}


@router.get("/verify-chain", summary="Verify quarantine ledger HMAC chain")
def verify_chain() -> Dict[str, Any]:
    try:
        intact = _engine.verify_chain()
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"chain_intact": intact}


@router.get("/audit", summary="Retrieve CAVE audit log")
def audit_log() -> Dict[str, Any]:
    entries = _engine.audit_log()
    return {"count": len(entries), "audit": entries}


@router.get("/status", summary="CAVE module status")
def status() -> Dict[str, Any]:
    return _engine.status()
