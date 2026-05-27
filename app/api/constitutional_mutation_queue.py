"""
INNOV-102 CMQ — Constitutional Mutation Queue
API Layer — Phase 197 · v10.8.0 · InnovativeAI LLC · DUSTIN L REID (HUMAN-0)

Endpoints:
  POST /cmq/enqueue
  GET  /cmq/peek
  POST /cmq/dequeue
  POST /cmq/complete/{mutation_id}
  GET  /cmq/state
  GET  /cmq/chain/verify
  GET  /cmq/export
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_queue import (
    CompletionOutcome,
    ConstitutionalMutationQueue,
    CMQChainBroken,
    CMQDeterminismViolation,
    CMQLedgerTampered,
    CMQOverlapConflict,
    CMQQueueStalled,
    CMQScopeUndeclared,
    CMQHuman0Bypass,
    CMQAuthorInvalid,
    CMQBlastTierInvalid,
    CMQIntentLinkMissing,
    CMQError,
    INNOV_CODE,
    INNOV_NUMBER,
    VERSION,
    PHASE,
    GOVERNOR,
    LEDGER_PATH,
)

router = APIRouter(prefix="/cmq", tags=["CMQ — Constitutional Mutation Queue"])

# Module-level queue instance (single queue per process)
_queue = ConstitutionalMutationQueue(ledger_path=LEDGER_PATH)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class EnqueueRequest(BaseModel):
    mutation_id: str = Field(..., description="UUID identifying the mutation")
    intent_declaration_id: str = Field(..., description="CMIM intent declaration UUID")
    author: str = Field(..., description="Submitting agent or HUMAN-0")
    blast_tier: int = Field(..., ge=0, le=2, description="0=Production, 1=Stable, 2=Sandbox")
    scope_paths: list[str] = Field(..., min_items=1, description="Non-empty scope path list")
    governance_objectives: list[str] = Field(default_factory=list)
    human0_override: bool = Field(default=False)


class CompleteRequest(BaseModel):
    outcome: str = Field(..., description="'promoted' or 'rolled_back'")


class CMQInfoResponse(BaseModel):
    innov_code: str
    innov_number: str
    version: str
    phase: int
    governor: str


# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------

@router.get("/info", response_model=CMQInfoResponse)
def cmq_info() -> CMQInfoResponse:
    return CMQInfoResponse(
        innov_code=INNOV_CODE,
        innov_number=INNOV_NUMBER,
        version=VERSION,
        phase=PHASE,
        governor=GOVERNOR,
    )


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

@router.post("/enqueue")
def enqueue(req: EnqueueRequest) -> dict[str, Any]:
    try:
        entry = _queue.enqueue(
            mutation_id=req.mutation_id,
            intent_declaration_id=req.intent_declaration_id,
            author=req.author,
            blast_tier=req.blast_tier,
            scope_paths=req.scope_paths,
            governance_objectives=req.governance_objectives,
            human0_override=req.human0_override,
        )
        return {"status": "enqueued", "entry": entry.to_dict()}
    except CMQOverlapConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CMQScopeUndeclared as e:
        raise HTTPException(status_code=422, detail=str(e))
    except CMQHuman0Bypass as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (CMQAuthorInvalid, CMQBlastTierInvalid, CMQIntentLinkMissing) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except CMQDeterminismViolation as e:
        raise HTTPException(status_code=500, detail=f"DETERMINISM_VIOLATION: {e}")
    except CMQError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Peek
# ---------------------------------------------------------------------------

@router.get("/peek")
def peek() -> dict[str, Any]:
    entry = _queue.peek()
    if entry is None:
        return {"status": "empty", "entry": None}
    return {"status": "ok", "entry": entry.to_dict()}


# ---------------------------------------------------------------------------
# Dequeue
# ---------------------------------------------------------------------------

@router.post("/dequeue")
def dequeue() -> dict[str, Any]:
    try:
        entry = _queue.dequeue()
        return {"status": "dequeued", "entry": entry.to_dict()}
    except CMQChainBroken as e:
        raise HTTPException(status_code=500, detail=f"CHAIN_BROKEN: {e}")
    except CMQQueueStalled as e:
        raise HTTPException(status_code=409, detail=f"QUEUE_STALLED: {e}")
    except CMQError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------

@router.post("/complete/{mutation_id}")
def complete(mutation_id: str, req: CompleteRequest) -> dict[str, Any]:
    try:
        outcome = CompletionOutcome(req.outcome)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid outcome '{req.outcome}'. Must be 'promoted' or 'rolled_back'.",
        )
    try:
        entry = _queue.complete(mutation_id=mutation_id, outcome=outcome)
        return {"status": "completed", "outcome": outcome.value, "entry": entry.to_dict()}
    except CMQLedgerTampered as e:
        raise HTTPException(status_code=500, detail=f"LEDGER_TAMPERED: {e}")
    except CMQError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@router.get("/state")
def get_state() -> dict[str, Any]:
    state = _queue.get_state()
    return state.to_dict()


# ---------------------------------------------------------------------------
# Chain verify
# ---------------------------------------------------------------------------

@router.get("/chain/verify")
def chain_verify() -> dict[str, Any]:
    result = _queue.verify_chain()
    if not result["valid"]:
        raise HTTPException(status_code=500, detail=f"CHAIN_BROKEN at entry {result['broken_at']}")
    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/export")
def export_ledger() -> dict[str, Any]:
    events = _queue.export_ledger()
    return {"innov_code": INNOV_CODE, "phase": PHASE, "event_count": len(events), "events": events}
