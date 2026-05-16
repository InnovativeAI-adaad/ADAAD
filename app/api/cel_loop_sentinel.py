# SPDX-License-Identifier: Apache-2.0
"""
REST router — INNOV-91 · CLS — CEL Loop Sentinel
Phase 186 · v9.119.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.cel_loop_sentinel import CELLoopSentinel

router = APIRouter(prefix="/api/cls", tags=["CLS"])

_engine: Optional[CELLoopSentinel] = None


def _get_engine() -> CELLoopSentinel:
    global _engine
    if _engine is None:
        _engine = CELLoopSentinel()
    return _engine


class ScanRequest(BaseModel):
    snapshot_id: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/scan")
def run_scan(req: ScanRequest) -> Dict[str, Any]:
    """
    Execute a full CEL gate scan. Returns a sealed CLSSnapshot.
    Issues HUMAN-0 advisory when closure_score < 1.0 (CLS-ADVISORY-0).
    """
    try:
        from dataclasses import asdict
        snapshot = _get_engine().scan(snapshot_id=req.snapshot_id)
        return {"ok": True, "snapshot": asdict(snapshot)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CLS scan failed: {exc}")


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """Return current sentinel status without executing a scan (CLS-READONLY-0)."""
    try:
        return {"ok": True, "status": _get_engine().status()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CLS status failed: {exc}")


@router.get("/ledger")
def get_ledger() -> Dict[str, Any]:
    """Return all ledger entries in append-only order (CLS-PERSIST-0)."""
    try:
        return {"ok": True, "ledger": _get_engine().ledger()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CLS ledger fetch failed: {exc}")


@router.get("/verify")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC-SHA-256 chain integrity across all ledger entries (CLS-CHAIN-0)."""
    try:
        return {"ok": True, "verification": _get_engine().verify_chain()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CLS chain verify failed: {exc}")
