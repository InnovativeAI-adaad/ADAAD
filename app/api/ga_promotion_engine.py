# SPDX-License-Identifier: Proprietary — All Rights Reserved
"""
REST router — INNOV-92 · GPE — GA Promotion Engine
Phase 187 · v9.120.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.ga_promotion_engine import GAPromotionEngine

router = APIRouter(prefix="/api/gpe", tags=["GPE"])

_engine: Optional[GAPromotionEngine] = None


def _get_engine() -> GAPromotionEngine:
    global _engine
    if _engine is None:
        _engine = GAPromotionEngine()
    return _engine


class AssessRequest(BaseModel):
    v10_snapshot: Optional[Dict[str, Any]] = None
    pypi_version: Optional[str] = None
    entry_id: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/assess")
def run_assess(req: AssessRequest) -> Dict[str, Any]:
    """
    Execute a full GA promotion assessment.  Returns a sealed GAManifestEntry.
    Issues HUMAN-0 advisory when PromotionStatus is READY (GPE-HUMAN0-0).
    """
    try:
        from dataclasses import asdict
        entry = _get_engine().assess(
            v10_snapshot=req.v10_snapshot,
            pypi_version=req.pypi_version,
            entry_id=req.entry_id,
        )
        return {"ok": True, "entry": asdict(entry)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"GPE assess failed: {exc}")


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """Return current engine status without triggering an assessment (GPE-READONLY-0)."""
    try:
        return {"ok": True, "status": _get_engine().status()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"GPE status failed: {exc}")


@router.get("/manifest")
def get_manifest() -> Dict[str, Any]:
    """Return all manifest entries in append-only order (GPE-PERSIST-0)."""
    try:
        return {"ok": True, "manifest": _get_engine().manifest()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"GPE manifest fetch failed: {exc}")


@router.get("/verify")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC-SHA-256 chain integrity across all manifest entries (GPE-CHAIN-0)."""
    try:
        return {"ok": True, "verification": _get_engine().verify_chain()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"GPE chain verify failed: {exc}")
