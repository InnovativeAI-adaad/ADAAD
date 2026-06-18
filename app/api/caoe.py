# SPDX-License-Identifier: Apache-2.0
"""
app/api/caoe.py
Phase 227 · INNOV-132 · CAOE — Constitutional Autonomous Outcome Evaluator
FastAPI router — 9 endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.constitutional_autonomous_outcome_evaluator import (
    CAOEEngine,
    CAOEViolation,
    ChainBreakError,
    CollectionError,
    EvaluationRecord,
    HUMAN0NotificationError,
    ImmutabilityViolation,
    OriginError,
    ScopeError,
)

router = APIRouter(prefix="/caoe", tags=["CAOE"])
_engine = CAOEEngine()


# ── Request/Response models ───────────────────────────────────────────────────

class CollectRequest(BaseModel):
    execution_record: Dict[str, Any]


class EvaluateRequest(BaseModel):
    execution_record: Dict[str, Any]
    post_chi: float


class AcknowledgeRequest(BaseModel):
    notified_by: str


def _record_out(rec: EvaluationRecord) -> Dict[str, Any]:
    return rec.to_dict()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/collect")
def collect_record(req: CollectRequest) -> Dict[str, Any]:
    """
    POST /caoe/collect
    Validate a CAPE ExecutionRecord for evaluation.
    CAOE-COLLECT-0, CAOE-SCOPE-0, CAOE-ORIGIN-0 enforced.
    """
    try:
        record = _engine.collect(req.execution_record)
        return {"status": "ok", "record_id": record.get("record_id")}
    except (CollectionError, ScopeError, OriginError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CAOEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/evaluate")
def evaluate_outcome(req: EvaluateRequest) -> Dict[str, Any]:
    """
    POST /caoe/evaluate
    Evaluate promotion outcome: compute delta_chi, classify, seal to ledger.
    """
    try:
        rec = _engine.evaluate(req.execution_record, req.post_chi)
        return _record_out(rec)
    except (CollectionError, ScopeError, OriginError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except CAOEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/acknowledge/{eval_id}")
def acknowledge_evaluation(eval_id: str, req: AcknowledgeRequest) -> Dict[str, Any]:
    """
    POST /caoe/acknowledge/{eval_id}
    Acknowledge a FLAGGED DEGRADED evaluation. CAOE-HUMAN0-0 enforced.
    """
    try:
        rec = _engine.acknowledge(eval_id, req.notified_by)
        return _record_out(rec)
    except HUMAN0NotificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CAOEViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/evaluation/{eval_id}")
def get_evaluation(eval_id: str) -> Dict[str, Any]:
    """GET /caoe/evaluation/{eval_id} — Retrieve a single EvaluationRecord."""
    rec = _engine.get_evaluation(eval_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"eval_id '{eval_id}' not found")
    return _record_out(rec)


@router.get("/evaluations")
def list_evaluations() -> List[Dict[str, Any]]:
    """GET /caoe/evaluations — List all EvaluationRecords."""
    return [_record_out(r) for r in _engine.list_evaluations()]


@router.get("/verify-chain")
def verify_chain() -> Dict[str, Any]:
    """GET /caoe/verify-chain — Verify OutcomeLedger HMAC chain integrity."""
    try:
        ok = _engine.verify_chain()
        return {"chain_intact": ok}
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/flagged")
def list_flagged() -> List[Dict[str, Any]]:
    """GET /caoe/flagged — List all DEGRADED evaluations awaiting HUMAN-0 notification."""
    from dorkllm.constitutional_autonomous_outcome_evaluator import AcknowledgementStatus
    return [
        _record_out(r)
        for r in _engine.list_evaluations()
        if r.ack_status == AcknowledgementStatus.FLAGGED
    ]


@router.get("/audit")
def get_audit() -> List[Dict[str, Any]]:
    """GET /caoe/audit — Return full CAOE audit log (CAOE-AUDIT-0)."""
    return [e.to_dict() for e in _engine.audit_log()]


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """GET /caoe/status — CAOE engine status summary."""
    return _engine.status()
