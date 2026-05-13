# SPDX-License-Identifier: Apache-2.0
"""
REST router — INNOV-87 · CGR — Convergence Gap Resolver
Phase 182 · v9.115.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.convergence_gap_resolver import (
    ConvergenceGapResolver,
    DEFAULT_TOP_N,
    _CRITICAL_GAP_THRESHOLD,
    _WARNING_GAP_THRESHOLD,
)

router = APIRouter(prefix="/api/cgr", tags=["CGR"])

_engine: Optional[ConvergenceGapResolver] = None


def _get_engine() -> ConvergenceGapResolver:
    global _engine
    if _engine is None:
        _engine = ConvergenceGapResolver()
    return _engine


class ResolveRequest(BaseModel):
    plan_id: Optional[str] = None
    top_n: int = DEFAULT_TOP_N
    version: str = "9.115.0"


@router.post("/resolve")
def resolve(body: ResolveRequest) -> Dict[str, Any]:
    """
    Execute a convergence gap resolution cycle. Returns top-N Gap Resolution
    Plans ranked by score, overall convergence score, and HUMAN-0 advisory
    payload if any CRITICAL gaps are present.
    """
    engine = _get_engine()
    try:
        result = engine.resolve(
            plan_id=body.plan_id,
            top_n=body.top_n,
            version=body.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    payload = asdict(result)
    payload["thresholds"] = {
        "warning": _WARNING_GAP_THRESHOLD,
        "critical": _CRITICAL_GAP_THRESHOLD,
    }
    return payload


@router.get("/snapshot")
def snapshot() -> Dict[str, Any]:
    """Return the latest persisted CGR snapshot."""
    engine = _get_engine()
    snap = engine.get_snapshot()
    if snap is None:
        raise HTTPException(status_code=404, detail="No CGR snapshot found. Run /resolve first.")
    return snap


@router.get("/verify-chain")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC integrity of the GRP ledger."""
    engine = _get_engine()
    valid, reason = engine.verify_chain()
    return {"chain_valid": valid, "reason": reason}


@router.get("/health")
def health() -> Dict[str, Any]:
    """Return CGR engine health summary."""
    engine = _get_engine()
    snap = engine.get_snapshot()
    return {
        "module": "CGR",
        "innov": "INNOV-87",
        "phase": 182,
        "version": "9.115.0",
        "governor": "DUSTIN L REID",
        "plan_count": engine.get_plan_count(),
        "latest_gir_cri": snap.get("last_gir_cri") if snap else None,
        "latest_convergence": snap.get("last_overall_convergence") if snap else None,
        "top_gap_dimensions": snap.get("top_gap_dimensions") if snap else None,
    }
