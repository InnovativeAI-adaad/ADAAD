# SPDX-License-Identifier: Apache-2.0
"""
app/api/casl.py
Phase 224 · INNOV-129 · CASL — Constitutional Arc Synthesis Layer
FastAPI Router — 8 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.constitutional_arc_synthesis_layer import (
    ARC_II_DOMAINS,
    ArcSynthesisCollector,
    CASLEngine,
    CASLViolation,
    ChainBreakError,
    CHIComputationError,
    DomainSignal,
    DomainSignalStatus,
    OriginViolation,
    ScopeViolation,
    SynthesisGateError,
    VerificationFailure,
)

router = APIRouter(prefix="/casl", tags=["CASL"])

# ── Singleton engine ──────────────────────────────────────────────────────────
_engine = CASLEngine()


# ── Request / Response models ─────────────────────────────────────────────────
class IngestSignalRequest(BaseModel):
    domain: str
    status: str = "HEALTHY"
    health_score: float = 1.0
    invariant_count: int = 0
    last_event_ts: Optional[float] = None


class SynthesizeRequest(BaseModel):
    provenance_ref: str = "CASL-SELF-ORIGIN"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/ingest", summary="Ingest Arc II domain signal")
def ingest_signal(req: IngestSignalRequest) -> Dict[str, Any]:
    """
    POST /casl/ingest
    Ingest a governance signal from an Arc II domain.
    CASL-SCOPE-0: domain must be one of the 9 registered Arc II domains.
    CASL-VERIFY-0: signal HMAC verified via hmac.compare_digest.
    """
    try:
        status = DomainSignalStatus(req.status)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid status '{req.status}'. Valid: {[s.value for s in DomainSignalStatus]}")

    try:
        signal = ArcSynthesisCollector.make_signal(
            domain=req.domain,
            status=status,
            health_score=req.health_score,
            invariant_count=req.invariant_count,
            last_event_ts=req.last_event_ts,
        )
        audit_entry = _engine.ingest_signal(signal)
        return {
            "status": "INGESTED",
            "domain": req.domain,
            "health_score": req.health_score,
            "signal_verified": signal.verified,
            "audit_entry_id": audit_entry.entry_id,
        }
    except (ScopeViolation, VerificationFailure) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except CASLViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/synthesize", summary="Execute constitutional arc synthesis")
def synthesize(req: SynthesizeRequest) -> Dict[str, Any]:
    """
    POST /casl/synthesize
    Execute a full constitutional synthesis cycle over all 9 Arc II domains.
    Computes CHI, appends to ledger, audits operation.
    CASL-GATE-0: blocked if any domain signal unverified.
    CASL-ORIGIN-0: provenance_ref must be non-empty.
    """
    try:
        record = _engine.synthesize(provenance_ref=req.provenance_ref)
        return {
            "status": "SYNTHESIZED",
            "synthesis_id": record.synthesis_id,
            "chi": record.chi,
            "arc_health_matrix": record.arc_health_matrix,
            "provenance_ref": record.provenance_ref,
            "ledger_hmac": record.ledger_hmac[:24],
            "sealed": record.sealed,
        }
    except (SynthesisGateError, OriginViolation, CHIComputationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CASLViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/verify-chain", summary="Verify synthesis ledger chain integrity")
def verify_chain() -> Dict[str, Any]:
    """
    GET /casl/verify-chain
    Verify HMAC-SHA-256 chain integrity across all synthesis records.
    CASL-CHAIN-0: raises ChainBreakError on any breach.
    """
    try:
        result = _engine.verify_chain()
        return {"status": "CHAIN_INTACT", **result}
    except ChainBreakError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except CASLViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/records", summary="List all synthesis records")
def list_records() -> Dict[str, Any]:
    """
    GET /casl/records
    Return all synthesis records in the ledger.
    """
    records = _engine.get_synthesis_records()
    return {"count": len(records), "records": records}


@router.get("/audit", summary="Return CASL audit log")
def get_audit() -> Dict[str, Any]:
    """
    GET /casl/audit
    Return all CASL audit log entries (CASL-AUDIT-0).
    """
    entries = _engine.get_audit_log()
    return {"count": len(entries), "entries": entries}


@router.get("/status", summary="CASL engine status")
def get_status() -> Dict[str, Any]:
    """
    GET /casl/status
    Return CASL engine status, CHI for latest synthesis, and invariant registry.
    """
    return _engine.get_status()


@router.get("/domains", summary="List registered Arc II domains")
def list_domains() -> Dict[str, Any]:
    """
    GET /casl/domains
    List all 9 registered Arc II domains (CASL-SCOPE-0).
    """
    return {
        "domain_count": len(ARC_II_DOMAINS),
        "domains": list(ARC_II_DOMAINS),
        "casl_scope_invariant": "CASL-SCOPE-0",
    }


@router.get("/chi/{synthesis_id}", summary="Retrieve CHI for a specific synthesis")
def get_chi(synthesis_id: str) -> Dict[str, Any]:
    """
    GET /casl/chi/{synthesis_id}
    Retrieve the Constitutional Health Index for a specific synthesis record.
    """
    records = _engine.get_synthesis_records()
    match = next((r for r in records if r["synthesis_id"] == synthesis_id), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Synthesis record '{synthesis_id}' not found")
    return {
        "synthesis_id": synthesis_id,
        "chi": match["chi"],
        "arc_health_matrix": match["arc_health_matrix"],
        "provenance_ref": match["provenance_ref"],
        "ledger_hmac": match["ledger_hmac"],
        "sealed": match["sealed"],
    }
