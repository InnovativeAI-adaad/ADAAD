# SPDX-License-Identifier: Apache-2.0
# INNOV-123 · ACAM REST Router — Phase 218 · v10.29.0
# Governor: DUSTIN L REID

"""
FastAPI router for ACAM — Autonomous Constitutional Amendment Monitor.
Endpoints:
  POST /acam/scan             — Full amendment health scan
  GET  /acam/coverage         — Coverage score + section breakdown
  GET  /acam/verify-chain     — Monitor ledger HMAC integrity check
  GET  /acam/status           — Module health + ledger stats
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from dorkllm.autonomous_constitutional_amendment_monitor import (
    AutonomousConstitutionalAmendmentMonitor,
    scan,
    verify_chain,
    coverage_report,
    status,
    update_config,
    ACAMError,
    ACAMHuman0Error,
    ACAMIntegrityError,
    ACAMScopeError,
    GOVERNOR,
    INNOV,
    VERSION,
)

router = APIRouter(prefix="/acam", tags=["ACAM"])
_engine = AutonomousConstitutionalAmendmentMonitor()


class ACAMResponse(BaseModel):
    ok: bool
    data: Dict[str, Any]


@router.post(
    "/scan",
    response_model=ACAMResponse,
    summary="Full amendment health scan",
)
def post_scan() -> ACAMResponse:
    """
    Trigger a full ACAM scan:
    - Reads ACSA + ACPA ledgers
    - Detects stale proposals (ACAM-STALE-0)
    - Detects section conflicts (ACAM-CONFLICT-0)
    - Computes coverage score (ACAM-COVERAGE-0)
    - Appends monitor record to HMAC-chained ledger (ACAM-CHAIN-0)
    """
    try:
        result = scan()
        return ACAMResponse(ok=True, data=result)
    except ACAMError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ACAM scan failed: {exc}")


@router.get(
    "/coverage",
    response_model=ACAMResponse,
    summary="Amendment coverage report",
)
def get_coverage() -> ACAMResponse:
    """
    Return current amendment coverage score and per-state breakdown.
    ACAM-COVERAGE-0: computed from live ledger data — never hardcoded.
    """
    try:
        result = coverage_report()
        return ACAMResponse(ok=True, data=result)
    except ACAMError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ACAM coverage failed: {exc}")


@router.get(
    "/verify-chain",
    response_model=ACAMResponse,
    summary="Monitor ledger HMAC integrity check",
)
def get_verify_chain() -> ACAMResponse:
    """
    ACAM-INTEGRITY-0: walk the monitor ledger HMAC chain.
    Returns chain_valid=true on success; raises 422 on integrity failure.
    """
    try:
        result = verify_chain()
        return ACAMResponse(ok=True, data=result)
    except ACAMIntegrityError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ACAMError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ACAM chain verify failed: {exc}")


@router.get(
    "/status",
    response_model=ACAMResponse,
    summary="Module health and ledger statistics",
)
def get_status() -> ACAMResponse:
    """
    Return ACAM module health, ledger record count, and invariant manifest.
    Does not trigger a full scan.
    """
    try:
        result = status()
        return ACAMResponse(ok=True, data=result)
    except ACAMError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ACAM status failed: {exc}")


@router.get(
    "/health",
    summary="Liveness probe",
)
def get_health() -> Dict[str, Any]:
    """Liveness probe — returns 200 with module identifier."""
    return {
        "ok": True,
        "module": "ACAM",
        "innov": INNOV,
        "version": VERSION,
        "governor": GOVERNOR,
    }
