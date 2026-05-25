"""
CPA REST API — Phase 195 · INNOV-100
Constitutional Provenance Auditor endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from dorkllm.constitutional_provenance_auditor import (
    ConstitutionalProvenanceAuditor,
    ProvenanceViolation,
    ProvenanceBundle,
)

router = APIRouter(prefix="/cpa", tags=["CPA"])
_auditor = ConstitutionalProvenanceAuditor()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class TraceRequest(BaseModel):
    artifact_id: str
    artifact_class: str
    phase_origin: int
    innovation_id: str
    ratifying_agent: str
    operation: str = "CREATE"
    ancestors: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class TraceResponse(BaseModel):
    record_id: str
    artifact_id: str
    artifact_class: str
    phase_origin: int
    innovation_id: str
    hmac_digest: str
    timestamp: float


class VerifyResponse(BaseModel):
    artifact_id: str
    artifact_class: Optional[str]
    verified: bool
    chain_length: int
    head_digest: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/trace", response_model=TraceResponse, summary="Record provenance event")
def trace(req: TraceRequest):
    """CPA-TRACE-0: Record a provenance event for an artifact."""
    try:
        record = _auditor.trace(
            artifact_id=req.artifact_id,
            artifact_class=req.artifact_class,
            phase_origin=req.phase_origin,
            innovation_id=req.innovation_id,
            ratifying_agent=req.ratifying_agent,
            operation=req.operation,
            ancestors=req.ancestors,
            metadata=req.metadata,
        )
        return TraceResponse(
            record_id=record.record_id,
            artifact_id=record.artifact_id,
            artifact_class=record.artifact_class,
            phase_origin=record.phase_origin,
            innovation_id=record.innovation_id,
            hmac_digest=record.hmac_digest,
            timestamp=record.timestamp,
        )
    except ProvenanceViolation as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/verify/{artifact_id}", response_model=VerifyResponse, summary="Verify provenance chain")
def verify(artifact_id: str):
    """CPA-VERIFY-0: Verify HMAC integrity of stored provenance chain."""
    result = _auditor.verify(artifact_id)
    return VerifyResponse(**result)


@router.get("/summary", summary="Provenance health summary")
def summary():
    """CPA-SCOPE-0: Provenance health across all artifact classes."""
    return _auditor.summary()


@router.get("/export", summary="Export provenance bundle")
def export_bundle(artifact_id: str):
    """CPA-DETERM-0: Export deterministic replay-ready provenance bundle."""
    try:
        bundle = _auditor.export_bundle(artifact_id)
        return bundle.to_dict()
    except ProvenanceViolation as e:
        raise HTTPException(status_code=422, detail=str(e))
