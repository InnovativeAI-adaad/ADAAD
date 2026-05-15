# SPDX-License-Identifier: Apache-2.0
"""
REST router — INNOV-88 · CPE — Convergence Plan Executor
Phase 183 · v9.116.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.convergence_plan_executor import (
    ConvergencePlanExecutor,
    DEFAULT_EXECUTE_N,
    _STATUS_SUCCESS,
    _STATUS_PARTIAL,
    _STATUS_FAILED,
    _STATUS_REJECTED,
)

router = APIRouter(prefix="/api/cpe", tags=["CPE"])

_engine: Optional[ConvergencePlanExecutor] = None


def _get_engine() -> ConvergencePlanExecutor:
    global _engine
    if _engine is None:
        _engine = ConvergencePlanExecutor()
    return _engine


class ExecuteRequest(BaseModel):
    top_n: int = DEFAULT_EXECUTE_N
    severity_filter: Optional[str] = None


@router.post("/execute")
async def execute_plans(req: ExecuteRequest) -> Dict[str, Any]:
    """
    Execute top-N approved Gap Resolution Plans from the CGR ledger.
    Validates governance seals, dispatches actions, records outcomes.
    """
    try:
        engine = _get_engine()
        records = engine.execute(
            top_n=max(1, min(req.top_n, 10)),
            severity_filter=req.severity_filter,
        )
        return {
            "status": "ok",
            "plans_executed": len(records),
            "results": [asdict(r) for r in records],
            "innov_code": "INNOV-88",
            "governor": "DUSTIN L REID",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/snapshot")
async def get_snapshot() -> Dict[str, Any]:
    """Return current CPE execution snapshot."""
    try:
        engine = _get_engine()
        snap = engine.get_snapshot()
        return asdict(snap)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/verify-chain")
async def verify_chain() -> Dict[str, Any]:
    """Verify HMAC chain integrity of the CPE execution ledger."""
    try:
        engine = _get_engine()
        valid, detail = engine.verify_chain()
        return {
            "chain_valid": valid,
            "detail": detail,
            "innov_code": "INNOV-88",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history")
async def get_history(last_n: int = 20) -> Dict[str, Any]:
    """Return execution history (last N records)."""
    try:
        engine = _get_engine()
        history = engine.get_execution_history(last_n=min(last_n, 100))
        return {
            "records": history,
            "count": len(history),
            "innov_code": "INNOV-88",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
async def health() -> Dict[str, Any]:
    """CPE health check."""
    return {
        "module": "CPE",
        "innov_code": "INNOV-88",
        "phase": 183,
        "version": "9.116.0",
        "status": "operational",
        "governor": "DUSTIN L REID",
    }
