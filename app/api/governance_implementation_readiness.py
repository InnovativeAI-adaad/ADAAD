# SPDX-License-Identifier: Apache-2.0
"""
REST router — INNOV-86 · GIR — Governance Implementation Readiness
Phase 181 · v9.114.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.governance_implementation_readiness import (
    GovernanceImplementationReadiness,
    CRITICAL_THRESHOLD,
    WARNING_THRESHOLD,
)

router = APIRouter(prefix="/api/gir", tags=["GIR"])

_engine: Optional[GovernanceImplementationReadiness] = None


def _get_engine() -> GovernanceImplementationReadiness:
    global _engine
    if _engine is None:
        _engine = GovernanceImplementationReadiness()
    return _engine


class AssessRequest(BaseModel):
    assessment_id: Optional[str] = None
    version: str = "9.114.0"


@router.post("/assess")
def assess(body: AssessRequest) -> Dict[str, Any]:
    """
    Execute a full governance implementation readiness assessment.
    Returns CRI, per-dimension GIRS scores, V10 criteria confidence,
    and HUMAN-0 advisory payload if CRI < CRITICAL_THRESHOLD.
    """
    engine = _get_engine()
    try:
        result = engine.assess(
            assessment_id=body.assessment_id,
            version=body.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    payload = asdict(result)
    payload["thresholds"] = {
        "warning": WARNING_THRESHOLD,
        "critical": CRITICAL_THRESHOLD,
    }
    return payload


@router.get("/snapshot")
def snapshot() -> Dict[str, Any]:
    """Return the latest persisted GIR snapshot."""
    engine = _get_engine()
    snap = engine.get_snapshot()
    if snap is None:
        raise HTTPException(status_code=404, detail="No GIR snapshot found. Run /assess first.")
    return snap


@router.get("/verify-chain")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC integrity of the readiness assessment ledger."""
    engine = _get_engine()
    valid, reason = engine.verify_chain()
    return {"chain_valid": valid, "reason": reason}


@router.get("/health")
def health() -> Dict[str, Any]:
    """Return GIR engine health summary."""
    engine = _get_engine()
    snap = engine.get_snapshot()
    return {
        "module": "GIR",
        "innov": "INNOV-86",
        "phase": 181,
        "version": "9.114.0",
        "governor": "DUSTIN L REID",
        "assessment_count": engine.get_assessment_count(),
        "latest_cri": snap.get("cri") if snap else None,
        "latest_status": snap.get("cri_status") if snap else None,
    }
