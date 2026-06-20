# SPDX-License-Identifier: Apache-2.0
"""
app/api/cams.py
Phase 231 · INNOV-136 · CAMS — Constitutional Autonomous Monitoring Sentinel
FastAPI Router — 9 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 07
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_autonomous_monitoring_sentinel import (
    CAMSEngine,
    CAMSViolation,
    ChainBreakError,
    SampleError,
    AlertError,
    HUMAN0AckError,
    ImmutabilityViolation,
)

router = APIRouter(prefix="/cams", tags=["CAMS"])

_engine = CAMSEngine()


# ── Request models ────────────────────────────────────────────────────────────
class SampleRequest(BaseModel):
    chi_score: float = Field(..., ge=0.0, le=1.0, description="CHI score from CASL (CAMS-SAMPLE-0)")
    source_ref: str = Field(..., description="Upstream CASL record reference (CAMS-SAMPLE-0)")


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str = Field(..., description="HUMAN-0 identity (CAMS-HUMAN0-0)")
    note: str = Field(default="", description="Acknowledgement note")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/sample", summary="Ingest a CHI sample and classify trend")
def sample(req: SampleRequest) -> Dict[str, Any]:
    """
    POST /cams/sample
    Ingest a CHI sample end-to-end: validate -> classify -> (maybe) alert ->
    ledger append -> audit.
    CAMS-SAMPLE-0: chi_score in [0,1], source_ref non-empty.
    CAMS-DETERM-0 / CAMS-WINDOW-0: deterministic trend classification.
    CAMS-ALERT-0: CRITICAL trend raises exactly one alert.
    CAMS-CHAIN-0: ledger appended with chain verification.
    """
    try:
        return _engine.sample(chi_score=req.chi_score, source_ref=req.source_ref)
    except SampleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CAMSViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/alerts/{alert_id}/acknowledge", summary="HUMAN-0 acknowledge a CRITICAL alert")
def acknowledge_alert(alert_id: str, req: AcknowledgeRequest) -> Dict[str, Any]:
    """
    POST /cams/alerts/{alert_id}/acknowledge
    HUMAN-0 acknowledgement of an OPEN CRITICAL alert.
    CAMS-HUMAN0-0: acknowledged_by must be non-empty HUMAN-0 identity.
    CAMS-IMMUT-0: only OPEN alerts may be acknowledged.
    """
    try:
        alert = _engine.acknowledge_alert(alert_id, req.acknowledged_by, req.note)
    except HUMAN0AckError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ImmutabilityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CAMSViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return alert.to_dict()


@router.get("/alerts/{alert_id}", summary="Retrieve an alert")
def get_alert(alert_id: str) -> Dict[str, Any]:
    alert = _engine.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return alert.to_dict()


@router.get("/alerts", summary="List all alerts")
def list_alerts() -> Dict[str, Any]:
    alerts = _engine.all_alerts()
    return {"count": len(alerts), "alerts": [a.to_dict() for a in alerts]}


@router.get("/alerts/open/all", summary="List OPEN (unacknowledged) alerts")
def open_alerts() -> Dict[str, Any]:
    alerts = _engine.open_alerts()
    return {"count": len(alerts), "open": [a.to_dict() for a in alerts]}


@router.get("/ledger", summary="List monitoring ledger entries")
def ledger() -> Dict[str, Any]:
    entries = _engine.ledger_entries()
    return {
        "count": len(entries),
        "entries": [
            {
                "entry_id": e.entry_id,
                "sequence": e.sequence,
                "prev_hash": e.prev_hash,
                "entry_hash": e.entry_hash,
                "sample": e.sample.to_dict(),
                "classification": e.classification.to_dict() if e.classification else None,
                "ts": e.ts,
            }
            for e in entries
        ],
    }


@router.get("/verify-chain", summary="Verify monitoring ledger HMAC chain")
def verify_chain() -> Dict[str, Any]:
    try:
        intact = _engine.verify_chain()
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"chain_intact": intact}


@router.get("/audit", summary="Retrieve CAMS audit log")
def audit_log() -> Dict[str, Any]:
    entries = _engine.audit_log()
    return {"count": len(entries), "audit": entries}


@router.get("/status", summary="CAMS module status")
def status() -> Dict[str, Any]:
    return _engine.status()
