# SPDX-License-Identifier: Apache-2.0
"""
app/api/cape.py
Phase 226 · INNOV-131 · CAPE — Constitutional Autonomous Promotion Executor
FastAPI Router — 9 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 02
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_autonomous_promotion_executor import (
    CAPEEngine,
    CAPEViolation,
    ChainBreakError,
    ExecutionError,
    GateBlockError,
    HUMAN0ApprovalError,
    ImmutabilityViolation,
    OrderViolation,
    ScopeViolation,
)

router = APIRouter(prefix="/cape", tags=["CAPE"])

# ── Singleton engine ──────────────────────────────────────────────────────────
_engine = CAPEEngine()


# ── Request models ────────────────────────────────────────────────────────────

class EnqueueRequest(BaseModel):
    decision_id: str = Field(..., description="CADE decision_id (CAPE-SCOPE-0)")
    synthesis_id: str = Field(..., description="CASL synthesis_id (CAPE-SCOPE-0)")
    chi_score: float = Field(..., ge=0.0, le=1.0, description="Constitutional Health Index (CAPE-GATE-0 ≥ 0.80)")
    mutation_ref: str = Field(..., description="Mutation identifier")
    verdict: str = Field(..., description="Must be PROMOTE (CAPE-SCOPE-0)")


class ApproveRequest(BaseModel):
    approved_by: str = Field(..., description="HUMAN-0 identifier (CAPE-HUMAN0-0)")


class RejectRequest(BaseModel):
    rejected_by: str = Field(..., description="HUMAN-0 identifier rejecting the entry")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/enqueue", summary="Enqueue a CADE PROMOTE verdict for execution")
def enqueue_verdict(req: EnqueueRequest) -> Dict[str, Any]:
    """
    CAPE-SCOPE-0 / CAPE-GATE-0: Enqueue a PROMOTE verdict from CADE.
    Only PROMOTE verdicts with CHI ≥ 0.80 are accepted.
    """
    try:
        return _engine.enqueue(
            decision_id=req.decision_id,
            synthesis_id=req.synthesis_id,
            chi_score=req.chi_score,
            mutation_ref=req.mutation_ref,
            verdict=req.verdict,
        )
    except GateBlockError as exc:
        raise HTTPException(status_code=422, detail=f"CAPE-GATE-0: {exc}") from exc
    except ScopeViolation as exc:
        raise HTTPException(status_code=422, detail=f"CAPE-SCOPE-0: {exc}") from exc
    except CAPEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve/{entry_id}", summary="HUMAN-0 approval of a queued entry")
def approve_entry(entry_id: str, req: ApproveRequest) -> Dict[str, Any]:
    """
    CAPE-HUMAN0-0: HUMAN-0 must approve a queue entry before execution.
    approved_by must be a non-empty HUMAN-0 identifier.
    """
    try:
        return _engine.approve(entry_id=entry_id, approved_by=req.approved_by)
    except HUMAN0ApprovalError as exc:
        raise HTTPException(status_code=403, detail=f"CAPE-HUMAN0-0: {exc}") from exc
    except CAPEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reject/{entry_id}", summary="HUMAN-0 rejection of a queued entry")
def reject_entry(entry_id: str, req: RejectRequest) -> Dict[str, Any]:
    """Reject a PENDING or APPROVED queue entry."""
    try:
        return _engine.reject(entry_id=entry_id, rejected_by=req.rejected_by)
    except CAPEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/execute/{entry_id}", summary="Execute an APPROVED queue entry through 5-stage pipeline")
def execute_entry(entry_id: str) -> Dict[str, Any]:
    """
    CAPE-EXEC-0 / CAPE-ORDER-0: Execute the next APPROVED FIFO entry.
    Returns a sealed ExecutionRecord with SHA-256 proof and HMAC chain.
    """
    try:
        return _engine.execute(entry_id=entry_id)
    except HUMAN0ApprovalError as exc:
        raise HTTPException(status_code=403, detail=f"CAPE-HUMAN0-0: {exc}") from exc
    except OrderViolation as exc:
        raise HTTPException(status_code=409, detail=f"CAPE-ORDER-0: {exc}") from exc
    except ExecutionError as exc:
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=f"CAPE-CHAIN-0: {exc}") from exc
    except CAPEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/entry/{entry_id}", summary="Get a specific queue entry")
def get_queue_entry(entry_id: str) -> Dict[str, Any]:
    result = _engine.get_queue_entry(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Queue entry not found: {entry_id}")
    return result


@router.get("/queue", summary="List all promotion queue entries")
def list_queue() -> List[Dict[str, Any]]:
    """CAPE-QUEUE-0: list all entries in FIFO order."""
    return _engine.list_queue()


@router.get("/execution/{record_id}", summary="Get a specific execution record")
def get_execution(record_id: str) -> Dict[str, Any]:
    result = _engine.get_execution(record_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Execution record not found: {record_id}")
    return result


@router.get("/executions", summary="List all execution records")
def list_executions() -> List[Dict[str, Any]]:
    """CAPE-APPEND-0: return the full append-only execution ledger."""
    return _engine.list_executions()


@router.get("/verify-chain", summary="Verify HMAC chain integrity")
def verify_chain() -> Dict[str, Any]:
    """CAPE-CHAIN-0: verify the full ExecutionLedger HMAC chain."""
    return _engine.verify_chain()


@router.get("/audit", summary="Return full CAPE audit log")
def get_audit() -> List[Dict[str, Any]]:
    """CAPE-AUDIT-0: append-only HMAC-chained audit log."""
    return _engine.get_audit()


@router.get("/status", summary="CAPE engine status")
def get_status() -> Dict[str, Any]:
    """Full CAPE engine status: queue counts, ledger stats, invariant list."""
    return _engine.status()
