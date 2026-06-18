# SPDX-License-Identifier: Apache-2.0
"""
app/api/cacp.py
Phase 229 · INNOV-134 · CACP — Constitutional Autonomous Convergence Prover
FastAPI router — 11 endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.constitutional_autonomous_convergence_prover import (
    CACPEngine, CACPViolation,
    ChainBreakError, ImmutabilityViolation, HUMAN0NotificationError,
    ScopeError, OriginError, CycleError, TrendError, ProofError,
)

router = APIRouter(prefix="/cacp", tags=["CACP"])
_engine = CACPEngine()


class AggregateRequest(BaseModel):
    stage_records: Dict[str, Any]

class ProveRequest(BaseModel):
    cycle_ids: Optional[List[str]] = None

class AcknowledgeRequest(BaseModel):
    notified_by: str


def _err(exc: Exception) -> HTTPException:
    m = {
        HUMAN0NotificationError: 403,
        ImmutabilityViolation:   409,
        CycleError:              422,
        ScopeError:              422,
        OriginError:             422,
        TrendError:              422,
        ProofError:              422,
        ChainBreakError:         500,
        CACPViolation:           400,
    }
    for cls, code in m.items():
        if isinstance(exc, cls):
            return HTTPException(status_code=code, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/aggregate")
def aggregate_cycle(req: AggregateRequest) -> Dict[str, Any]:
    """Aggregate a complete ACI cycle from all 5 pipeline stage records — CACP-CYCLE-0."""
    try:
        return _engine.aggregate_cycle(req.stage_records).to_dict()
    except CACPViolation as e:
        raise _err(e)

@router.post("/prove")
def prove(req: ProveRequest) -> Dict[str, Any]:
    """Compute and register a ConvergenceProof — CACP-DETERM-0, CACP-PROOF-0."""
    try:
        return _engine.prove(req.cycle_ids).to_dict()
    except CACPViolation as e:
        raise _err(e)

@router.post("/acknowledge/{proof_id}")
def acknowledge(proof_id: str, req: AcknowledgeRequest) -> Dict[str, Any]:
    """HUMAN-0 acknowledges a DEGRADING convergence proof — CACP-HUMAN0-0."""
    try:
        return _engine.acknowledge(proof_id, req.notified_by).to_dict()
    except CACPViolation as e:
        raise _err(e)

@router.get("/cycle/{cycle_id}")
def get_cycle(cycle_id: str) -> Dict[str, Any]:
    c = _engine.get_cycle(cycle_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Cycle '{cycle_id}' not found")
    return c.to_dict()

@router.get("/cycles")
def list_cycles() -> List[Dict[str, Any]]:
    return [c.to_dict() for c in _engine.list_cycles()]

@router.get("/proof/{proof_id}")
def get_proof(proof_id: str) -> Dict[str, Any]:
    p = _engine.get_proof(proof_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Proof '{proof_id}' not found")
    return p.to_dict()

@router.get("/proofs")
def list_proofs(trend: Optional[str] = None) -> List[Dict[str, Any]]:
    return [p.to_dict() for p in _engine.list_proofs(trend)]

@router.get("/degrading")
def degrading_unacknowledged() -> List[Dict[str, Any]]:
    """List DEGRADING proofs not yet acknowledged by HUMAN-0 — CACP-HUMAN0-0."""
    return [p.to_dict() for p in _engine.degrading_unacknowledged()]

@router.get("/verify-chain")
def verify_chain() -> Dict[str, Any]:
    """Verify ConvergenceLedger HMAC chain integrity — CACP-CHAIN-0."""
    try:
        return _engine.verify_chain()
    except ChainBreakError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/audit")
def audit_log() -> List[Dict[str, Any]]:
    return _engine.audit_log()

@router.get("/status")
def status() -> Dict[str, Any]:
    return _engine.status()
