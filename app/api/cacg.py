# SPDX-License-Identifier: Apache-2.0
"""
app/api/cacg.py
Phase 232 · INNOV-137 · CACG — Constitutional Autonomous Cycle Governor
FastAPI Router — 10 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 08
Governance Capstone
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_autonomous_cycle_governor import (
    CACGEngine,
    CACGViolation,
    ChainBreakError,
    StageError,
    TimeoutViolation,
    ConfigError,
    StallError,
    HUMAN0EscalationError,
    ImmutabilityViolation,
)

router = APIRouter(prefix="/cacg", tags=["CACG"])

_engine = CACGEngine()


# ── Request models ─────────────────────────────────────────────────────────────

class StageCompletionRequest(BaseModel):
    stage: str = Field(..., description="ACI pipeline stage name (CACG-STAGES-0)")
    started_at: float = Field(..., description="Stage start Unix timestamp")
    completed_at: float = Field(..., description="Stage completion Unix timestamp")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Stage output payload")


class CloseCycleRequest(BaseModel):
    human0_identity: Optional[str] = Field(
        default=None,
        description="HUMAN-0 identity; required if cycle is STALLED or VIOLATED (CACG-HUMAN0-0)"
    )


class AcknowledgeEscalationRequest(BaseModel):
    acknowledged_by: str = Field(..., description="HUMAN-0 identity (CACG-HUMAN0-0)")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/cycles/start", status_code=201)
def start_cycle() -> Dict[str, Any]:
    """Start a new ACI governance cycle. Returns cycle_id."""
    cycle_id = _engine.start_cycle()
    return {"cycle_id": cycle_id, "status": "ACTIVE"}


@router.post("/cycles/{cycle_id}/stages", status_code=201)
def register_stage(cycle_id: str, body: StageCompletionRequest) -> Dict[str, Any]:
    """
    CACG-STAGES-0 / CACG-TIMEOUT-0
    Register a stage completion for an active cycle.
    Raises 422 on unknown stage; 409 on timeout violation.
    """
    try:
        receipt = _engine.register_stage_completion(
            cycle_id=cycle_id,
            stage=body.stage,
            started_at=body.started_at,
            completed_at=body.completed_at,
            payload=body.payload or {},
        )
        return receipt.to_dict()
    except StageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except TimeoutViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/cycles/{cycle_id}/close", status_code=200)
def close_cycle(cycle_id: str, body: CloseCycleRequest) -> Dict[str, Any]:
    """
    CACG-STALL-0 / CACG-HUMAN0-0 / CACG-PROOF-0
    Close active cycle; issues HUMAN-0 escalation if STALLED/VIOLATED.
    """
    try:
        record = _engine.close_cycle(
            cycle_id=cycle_id,
            human0_identity=body.human0_identity,
        )
        return record.to_dict()
    except HUMAN0EscalationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CACGViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/cycles/{cycle_id}", status_code=200)
def get_cycle(cycle_id: str) -> Dict[str, Any]:
    """Retrieve a sealed cycle governance record by cycle_id."""
    record = _engine.get_record(cycle_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id!r} not found.")
    return record


@router.get("/cycles/active/all", status_code=200)
def list_active_cycles() -> Dict[str, Any]:
    """List all currently active (open) cycle IDs."""
    return {"active_cycles": _engine.get_active_cycles()}


@router.post("/escalations/{escalation_id}/acknowledge", status_code=200)
def acknowledge_escalation(
    escalation_id: str, body: AcknowledgeEscalationRequest
) -> Dict[str, Any]:
    """
    CACG-HUMAN0-0 / CACG-IMMUT-0
    Acknowledge a HUMAN-0 escalation. acknowledged_by must be non-empty.
    """
    try:
        esc = _engine.acknowledge_escalation(escalation_id, body.acknowledged_by)
        return esc.to_dict()
    except HUMAN0EscalationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/escalations/{escalation_id}", status_code=200)
def get_escalation(escalation_id: str) -> Dict[str, Any]:
    """Retrieve a HUMAN-0 escalation record by ID."""
    esc = _engine.get_escalation(escalation_id)
    if esc is None:
        raise HTTPException(status_code=404, detail=f"Escalation {escalation_id!r} not found.")
    return esc.to_dict()


@router.get("/ledger", status_code=200)
def get_ledger() -> Dict[str, Any]:
    """Return all sealed cycle governance records from the ledger."""
    return {"ledger": _engine.get_ledger(), "count": len(_engine.get_ledger())}


@router.get("/verify-chain", status_code=200)
def verify_chain() -> Dict[str, Any]:
    """CACG-CHAIN-0: Full HMAC chain verification of the governance ledger."""
    try:
        valid = _engine.verify_chain()
        return {"chain_valid": valid}
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/audit", status_code=200)
def get_audit() -> Dict[str, Any]:
    """CACG-AUDIT-0: Return the full HMAC-chained CACG audit log."""
    return {"audit_log": _engine.get_audit_log()}


@router.get("/status", status_code=200)
def get_status() -> Dict[str, Any]:
    """CACG module status: active cycles, sealed cycles, open escalations."""
    return _engine.status()
