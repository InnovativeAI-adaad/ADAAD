# SPDX-License-Identifier: Apache-2.0
"""
REST router — INNOV-89 · CCA — Convergence Certification Auditor
Phase 184 · v9.117.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor

router = APIRouter(prefix="/api/cca", tags=["CCA"])

_engine: Optional[ConvergenceCertificationAuditor] = None


def _get_engine() -> ConvergenceCertificationAuditor:
    global _engine
    if _engine is None:
        _engine = ConvergenceCertificationAuditor()
    return _engine


class AuditRequest(BaseModel):
    audit_id: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/audit")
def run_audit(req: AuditRequest) -> Dict[str, Any]:
    """
    Run a full V10 convergence audit.
    Issues a Convergence Certificate (CC) if score ≥ CCA_THRESHOLD.
    Emits a HUMAN-0 advisory before issuing V10 certificates.
    """
    try:
        cert = _get_engine().audit(audit_id=req.audit_id)
        from dataclasses import asdict
        return {"ok": True, "certificate": asdict(cert)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCA audit failed: {exc}")


@router.get("/preview")
def preview_criteria() -> Dict[str, Any]:
    """
    Preview V10 criteria scoring WITHOUT writing to the ledger.
    Safe for dashboard polling.
    """
    try:
        return _get_engine().preview_criteria()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCA preview failed: {exc}")


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """Return CCA engine state and criteria registry."""
    try:
        return _get_engine().get_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCA status failed: {exc}")


@router.get("/verify-chain")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC chain integrity across the certification ledger."""
    try:
        valid, count, error = _get_engine().verify_chain()
        return {"valid": valid, "records_checked": count, "error": error}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCA chain verification failed: {exc}")
