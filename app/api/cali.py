# SPDX-License-Identifier: Apache-2.0
"""
app/api/cali.py
Phase 228 · INNOV-133 · CALI — Constitutional Autonomous Learning Intelligence
FastAPI router — 10 endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.constitutional_autonomous_learning_intelligence import (
    CALIEngine,
    CALIViolation,
    BoundError,
    ChainBreakError,
    HUMAN0RatificationError,
    IngestionError,
    ImmutabilityViolation,
    OriginError,
    ScopeError,
)

router = APIRouter(prefix="/cali", tags=["CALI"])
_engine = CALIEngine()


# ── Request/Response models ───────────────────────────────────────────────────

class IngestRequest(BaseModel):
    evaluation_record: Dict[str, Any]


class ComputeSignalRequest(BaseModel):
    ingestion_id: str


class RecommendRequest(BaseModel):
    chi_band: str


class RatifyRequest(BaseModel):
    ratified_by: str


class RejectRequest(BaseModel):
    reason: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _caoe_error(exc: Exception) -> HTTPException:
    mapping = {
        HUMAN0RatificationError: 403,
        ImmutabilityViolation: 409,
        BoundError: 422,
        ScopeError: 422,
        OriginError: 422,
        IngestionError: 422,
        ChainBreakError: 500,
        CALIViolation: 400,
    }
    for cls, code in mapping.items():
        if isinstance(exc, cls):
            return HTTPException(status_code=code, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/ingest")
def ingest_outcome(req: IngestRequest) -> Dict[str, Any]:
    """Ingest a CAOE EvaluationRecord — CALI-INGEST-0, CALI-SCOPE-0, CALI-ORIGIN-0."""
    try:
        outcome = _engine.ingest(req.evaluation_record)
        return outcome.to_dict()
    except CALIViolation as e:
        raise _caoe_error(e)


@router.post("/compute-signal")
def compute_signal(req: ComputeSignalRequest) -> Dict[str, Any]:
    """Compute bounded adaptation signal for an ingested outcome — CALI-ADAPT-0."""
    try:
        sig = _engine.compute_signal(req.ingestion_id)
        return sig.to_dict()
    except CALIViolation as e:
        raise _caoe_error(e)


@router.post("/recommend")
def recommend(req: RecommendRequest) -> Dict[str, Any]:
    """Produce a PENDING threshold recommendation for CADE — CALI-THRESH-0."""
    try:
        rec = _engine.recommend(req.chi_band)
        return rec.to_dict()
    except CALIViolation as e:
        raise _caoe_error(e)


@router.post("/ratify/{recommendation_id}")
def ratify(recommendation_id: str, req: RatifyRequest) -> Dict[str, Any]:
    """HUMAN-0 ratifies a threshold recommendation — CALI-HUMAN0-0."""
    try:
        rec = _engine.ratify(recommendation_id, req.ratified_by)
        return rec.to_dict()
    except CALIViolation as e:
        raise _caoe_error(e)


@router.post("/reject/{recommendation_id}")
def reject(recommendation_id: str, req: RejectRequest) -> Dict[str, Any]:
    """HUMAN-0 rejects a threshold recommendation."""
    try:
        rec = _engine.reject(recommendation_id, req.reason)
        return rec.to_dict()
    except CALIViolation as e:
        raise _caoe_error(e)


@router.get("/outcome/{ingestion_id}")
def get_outcome(ingestion_id: str) -> Dict[str, Any]:
    """Retrieve an ingested CAOE outcome by ingestion_id."""
    outcome = _engine.get_outcome(ingestion_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail=f"Ingestion '{ingestion_id}' not found")
    return outcome.to_dict()


@router.get("/outcomes")
def list_outcomes() -> List[Dict[str, Any]]:
    """List all ingested CAOE outcomes."""
    return [o.to_dict() for o in _engine.list_outcomes()]


@router.get("/signals")
def list_signals(chi_band: Optional[str] = None) -> List[Dict[str, Any]]:
    """List adaptation signals, optionally filtered by CHI band."""
    return [s.to_dict() for s in _engine.list_signals(chi_band)]


@router.get("/recommendations")
def list_recommendations(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List threshold recommendations, optionally filtered by status."""
    return [r.to_dict() for r in _engine.list_recommendations(status)]


@router.get("/verify-chain")
def verify_chain() -> Dict[str, Any]:
    """Verify LearningLedger HMAC chain integrity — CALI-CHAIN-0."""
    try:
        return _engine.verify_chain()
    except ChainBreakError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thresholds")
def live_thresholds() -> Dict[str, Any]:
    """Return live CADE thresholds (reflects ratified recommendations only — CALI-HUMAN0-0)."""
    return {
        "thresholds": _engine.live_thresholds(),
        "band_cumulative": _engine.band_cumulative(),
        "note": "Only RATIFIED recommendations update live thresholds (CALI-HUMAN0-0)",
    }


@router.get("/audit")
def audit_log() -> List[Dict[str, Any]]:
    """Return CALI audit log — CALI-AUDIT-0."""
    return _engine.audit_log()


@router.get("/status")
def status() -> Dict[str, Any]:
    """Return CALI engine status."""
    return _engine.status()
