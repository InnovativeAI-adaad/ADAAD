# SPDX-License-Identifier: Apache-2.0
"""REST router — INNOV-111 · CMSE — Constitutional Mutation Scheduling Engine.

Endpoints:
  POST /api/cmse/schedule   — register a new ScheduleWindow
  POST /api/cmse/promote    — promote PENDING → ACTIVE
  POST /api/cmse/expire     — expire an ACTIVE/PENDING window
  POST /api/cmse/drain      — enable/disable drain mode (HUMAN-0)
  GET  /api/cmse/windows    — list all windows (optionally filtered by status)
  GET  /api/cmse/verify     — verify ScheduleLedger chain integrity
  GET  /api/cmse/health     — liveness check
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_scheduling_engine import (
    ConstitutionalMutationSchedulingEngine,
    CMSEAuthError,
    CMSEBlastError,
    CMSECapacityError,
    CMSEChainError,
    CMSEError,
    CMSEImmutError,
    CMSEOverlapError,
    CMSEScopeError,
    CMSEVelocityError,
    INNOV_CODE,
    INNOV_NUMBER,
    VERSION,
    PHASE,
)

router = APIRouter(prefix="/api/cmse", tags=["CMSE"])

_engine = ConstitutionalMutationSchedulingEngine()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    proposal_id: str = Field(..., description="AMPS proposal ID being scheduled")
    blast_tier: int = Field(..., ge=0, le=2, description="Blast radius tier (0/1/2)")
    mutation_scope: list[str] = Field(..., description="Non-empty list of scope tokens")
    constitutional_fitness: float = Field(default=1.0, ge=0.0, le=1.0)
    velocity_rate: float = Field(default=1.0, ge=0.0, description="Current CMVG velocity rate")
    metadata: dict = Field(default_factory=dict)


class PromoteRequest(BaseModel):
    window_id: str
    velocity_rate: float = Field(default=1.0, ge=0.0)
    human0_identity: Optional[str] = Field(default=None)


class ExpireRequest(BaseModel):
    window_id: str


class DrainRequest(BaseModel):
    human0_identity: str
    drain: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/schedule")
def schedule_window(req: ScheduleRequest):
    try:
        window = _engine.schedule(
            proposal_id=req.proposal_id,
            blast_tier=req.blast_tier,
            mutation_scope=set(req.mutation_scope),
            constitutional_fitness=req.constitutional_fitness,
            velocity_rate=req.velocity_rate,
            metadata=req.metadata,
        )
        return {"status": "SCHEDULED", "window_id": window.window_id,
                "slot_index": window.slot_index, "blast_tier": window.blast_tier,
                "mutation_scope": window.mutation_scope,
                "constitutional_fitness": window.constitutional_fitness,
                "innov_code": INNOV_CODE, "phase": PHASE}
    except (CMSEScopeError, CMSEBlastError, CMSECapacityError, CMSEVelocityError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CMSEError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/promote")
def promote_window(req: PromoteRequest):
    try:
        window = _engine.promote(
            window_id=req.window_id,
            velocity_rate=req.velocity_rate,
            human0_identity=req.human0_identity,
        )
        return {"status": "PROMOTED", "window_id": window.window_id,
                "promoted_by": window.promoted_by, "slot_index": window.slot_index,
                "blast_tier": window.blast_tier, "innov_code": INNOV_CODE}
    except CMSEAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (CMSEImmutError, CMSEOverlapError, CMSEVelocityError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CMSEError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/expire")
def expire_window(req: ExpireRequest):
    try:
        window = _engine.expire(window_id=req.window_id)
        return {"status": "EXPIRED", "window_id": window.window_id,
                "innov_code": INNOV_CODE}
    except CMSEImmutError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CMSEError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/drain")
def set_drain(req: DrainRequest):
    try:
        _engine.set_drain(human0_identity=req.human0_identity, drain=req.drain)
        return {"status": "OK", "drain_mode": _engine.drain_mode,
                "innov_code": INNOV_CODE}
    except CMSEAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/windows")
def list_windows(status: Optional[str] = None):
    windows = list(_engine._windows.values())
    if status:
        windows = [w for w in windows if w.status == status.upper()]
    return {
        "windows": [
            {"window_id": w.window_id, "status": w.status, "blast_tier": w.blast_tier,
             "mutation_scope": w.mutation_scope, "slot_index": w.slot_index,
             "constitutional_fitness": w.constitutional_fitness, "promoted_by": w.promoted_by}
            for w in windows
        ],
        "total": len(windows),
        "drain_mode": _engine.drain_mode,
        "innov_code": INNOV_CODE,
    }


@router.get("/verify")
def verify_ledger():
    try:
        ok = _engine.verify_ledger()
        return {"chain_valid": ok, "innov_code": INNOV_CODE, "phase": PHASE}
    except CMSEChainError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
def health():
    return {
        "status": "operational",
        "innov_code": INNOV_CODE,
        "innov_number": INNOV_NUMBER,
        "version": VERSION,
        "phase": PHASE,
        "drain_mode": _engine.drain_mode,
        "active_windows": len(_engine.active_windows()),
        "pending_windows": len(_engine.pending_windows()),
        "governor": "DUSTIN L REID",
    }
