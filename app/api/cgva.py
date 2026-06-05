# SPDX-License-Identifier: Apache-2.0
# INNOV-117 · CGVA — Constitutional Governance Validation Auditor — REST API
# Phase 212 · v10.23.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
FastAPI router for the Constitutional Governance Validation Auditor (CGVA).

Endpoints
---------
POST /cgva/validate          — Execute a governance validation sweep
POST /cgva/certify/{id}      — HUMAN-0 certification of an attestation
GET  /cgva/history           — Retrieve attestation history
GET  /cgva/verify-chain      — Verify full HMAC chain integrity
GET  /cgva/health-score      — Current governance health score
GET  /cgva/status            — Engine status summary
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dorkllm.constitutional_governance_validation_auditor import (
    ConstitutionalGovernanceValidationAuditor,
)

router = APIRouter(prefix="/cgva", tags=["CGVA — Constitutional Governance Validation Auditor"])

# Singleton auditor instance
_auditor = ConstitutionalGovernanceValidationAuditor()


# ── Request / Response Models ─────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    domain: str = Field(..., description="Governance domain to validate (e.g. 'pipeline', 'mutation')")
    context: Dict[str, Any] = Field(default_factory=dict, description="Optional validation context")


class CertifyResponse(BaseModel):
    attestation_id: str
    certified: bool
    certification_ts_ns: Optional[int]
    health_score: float
    overall_status: str
    governor: str


class HealthScoreResponse(BaseModel):
    health_score: float
    domain: Optional[str]
    engine: str = "CGVA"
    governor: str = "DUSTIN L REID"


class ChainVerifyResponse(BaseModel):
    chain_valid: bool
    first_break_index: Optional[int]
    total_records: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/validate", summary="Execute a governance validation sweep")
async def validate_governance(req: ValidateRequest) -> Dict[str, Any]:
    """
    Execute a full multi-dimensional constitutional governance validation sweep.
    Returns a sealed AttestationRecord with health score, dimension results,
    drift signal, and HUMAN-0 escalation flag.
    """
    try:
        record = _auditor.validate(domain=req.domain, context=req.context)
        return {
            "attestation_id": record.attestation_id,
            "domain": record.domain,
            "ts_ns": record.ts_ns,
            "health_score": record.health_score,
            "overall_status": record.overall_status,
            "drift_signal": record.drift_signal,
            "human0_required": record.human0_required,
            "certified": record.certified,
            "governor": record.governor,
            "dimensions": record.dimensions,
            "hmac_digest_prefix": record.hmac_digest[:16],
            "prev_digest_prefix": record.prev_digest[:16] if record.prev_digest != "GENESIS" else "GENESIS",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVA validation failed: {exc}") from exc


@router.post("/certify/{attestation_id}", response_model=CertifyResponse,
             summary="HUMAN-0 certification of an attestation")
async def certify_attestation(attestation_id: str) -> CertifyResponse:
    """
    Apply HUMAN-0 certification seal to an existing attestation record.
    Once certified, the record is immutable (CGVA-CERT-0).
    """
    try:
        record = _auditor.certify(attestation_id)
        return CertifyResponse(
            attestation_id=record.attestation_id,
            certified=record.certified,
            certification_ts_ns=record.certification_ts_ns,
            health_score=record.health_score,
            overall_status=record.overall_status,
            governor=record.governor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Certification failed: {exc}") from exc


@router.get("/history", summary="Retrieve attestation history")
async def get_history(
    domain: Optional[str] = Query(None, description="Filter by governance domain"),
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
) -> Dict[str, Any]:
    """
    Return recent attestation records from the CGVA ledger,
    optionally filtered by domain.
    """
    records = _auditor.history(domain=domain, limit=limit)
    return {
        "count": len(records),
        "domain_filter": domain,
        "attestations": [
            {
                "attestation_id": r.attestation_id,
                "domain": r.domain,
                "ts_ns": r.ts_ns,
                "health_score": r.health_score,
                "overall_status": r.overall_status,
                "drift_signal": r.drift_signal,
                "human0_required": r.human0_required,
                "certified": r.certified,
            }
            for r in records
        ],
    }


@router.get("/verify-chain", response_model=ChainVerifyResponse,
            summary="Verify full HMAC chain integrity")
async def verify_chain() -> ChainVerifyResponse:
    """
    Perform a full HMAC chain integrity sweep over the CGVA attestation ledger.
    Reports the first chain break index if the ledger has been tampered with.
    """
    chain_valid, break_idx = _auditor.verify_chain()
    return ChainVerifyResponse(
        chain_valid=chain_valid,
        first_break_index=break_idx,
        total_records=len(_auditor.records),
    )


@router.get("/health-score", response_model=HealthScoreResponse,
            summary="Current governance health score")
async def get_health_score(
    domain: Optional[str] = Query(None, description="Scope to a specific domain"),
) -> HealthScoreResponse:
    """
    Return the most recent governance health score.
    Returns 1.0 if no attestations have been recorded yet.
    """
    score = _auditor.health_score(domain=domain)
    return HealthScoreResponse(health_score=score, domain=domain)


@router.get("/status", summary="CGVA engine status summary")
async def get_status() -> Dict[str, Any]:
    """
    Return a comprehensive status summary of the CGVA engine including
    invariant registry, chain validity, and current health score.
    """
    return _auditor.status()
