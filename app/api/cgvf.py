# SPDX-License-Identifier: Apache-2.0
# INNOV-120 · CGVF REST Router — Phase 215 · v10.26.0
# Governor: DUSTIN L REID

"""
FastAPI router for CGVF — Constitutional Governance Validation Fusion Engine.

Endpoints:
  POST /cgvf/fuse            — Run full governance fusion cycle
  POST /cgvf/certify/{id}    — HUMAN-0 certification gate
  GET  /cgvf/history         — Paginated FusionAttestation log
  GET  /cgvf/verify-chain    — HMAC integrity check
  GET  /cgvf/consensus-score — Live consensus score
  GET  /cgvf/status          — Module health
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from dorkllm.constitutional_governance_validation_fusion import (
    ConstitutionalGovernanceValidationFusion,
    CGVFError,
    CGVFCertError,
    GOVERNOR,
)

router = APIRouter(prefix="/cgvf", tags=["CGVF"])
_engine = ConstitutionalGovernanceValidationFusion()


# ── Request / Response models ─────────────────────────────────────────────────


class CertifyRequest(BaseModel):
    certified_by: Optional[str] = GOVERNOR


class CGVFResponse(BaseModel):
    ok:   bool
    data: Dict[str, Any]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/fuse", response_model=CGVFResponse, summary="Run governance fusion")
def fuse() -> CGVFResponse:
    """
    Execute a full CGVF governance fusion cycle.
    Queries CGVA, CGVR, CGVE, CGPR; computes weighted consensus_score;
    seals and ledger-records a FusionAttestation.
    CGVF-AUDIT-0: record is written before response is returned.
    """
    try:
        attestation = _engine.fuse()
        return CGVFResponse(ok=True, data=attestation.to_dict())
    except CGVFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVF fusion error: {exc}")


@router.post("/certify/{fusion_id}", response_model=CGVFResponse, summary="HUMAN-0 certification")
def certify(fusion_id: str, body: CertifyRequest = CertifyRequest()) -> CGVFResponse:
    """
    Apply HUMAN-0 certification to a FusionAttestation.
    CGVF-CERT-0: raises 409 if already certified.
    """
    try:
        certified = _engine.certify(fusion_id, certified_by=body.certified_by or GOVERNOR)
        return CGVFResponse(ok=True, data=certified.to_dict())
    except CGVFCertError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CGVFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVF certify error: {exc}")


@router.get("/history", response_model=CGVFResponse, summary="FusionAttestation log")
def history(limit: int = Query(default=20, ge=1, le=200)) -> CGVFResponse:
    """Return paginated FusionAttestation history from the ledger."""
    try:
        records = _engine.history(limit=limit)
        return CGVFResponse(
            ok=True,
            data={
                "count":   len(records),
                "records": [r.to_dict() for r in records],
            },
        )
    except CGVFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVF history error: {exc}")


@router.get("/verify-chain", response_model=CGVFResponse, summary="HMAC chain integrity check")
def verify_chain() -> CGVFResponse:
    """
    Walk the fusion ledger and verify HMAC chain integrity.
    CGVF-CHAIN-0.
    """
    try:
        result = _engine.verify_chain()
        return CGVFResponse(ok=result["valid"], data=result)
    except CGVFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVF chain error: {exc}")


@router.get("/consensus-score", response_model=CGVFResponse, summary="Live consensus score")
def consensus_score_endpoint() -> CGVFResponse:
    """Return the most recent governance consensus_score."""
    try:
        score = _engine.consensus_score()
        return CGVFResponse(ok=True, data={"consensus_score": score})
    except CGVFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVF score error: {exc}")


@router.get("/status", response_model=CGVFResponse, summary="Module health")
def status() -> CGVFResponse:
    """Return CGVF module status summary."""
    try:
        return CGVFResponse(ok=True, data=_engine.status())
    except CGVFError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVF status error: {exc}")
