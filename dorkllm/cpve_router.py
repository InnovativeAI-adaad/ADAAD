# SPDX-License-Identifier: Apache-2.0
"""
cpve_router.py
Phase 223 · INNOV-128 · CPVE — Constitutional Provenance Verification Engine
FastAPI Router — 8 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.constitutional_provenance_verification_engine import (
    ARTIFACT_CLASSES,
    CPVEEngine,
    CertificationDenied,
    ChainIntegrityError,
    CPVEViolation,
    OrphanArtifactError,
    ProvenanceGateError,
    ScopeViolation,
)

router = APIRouter(prefix="/cpve", tags=["CPVE"])

# ── Singleton engine (tmp ledgers for API; override in production) ────────────
_DEFAULT_ENGINE: Optional[CPVEEngine] = None


def get_engine() -> CPVEEngine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = CPVEEngine()
    return _DEFAULT_ENGINE


# ── Request / Response models ─────────────────────────────────────────────────

class TraceRequest(BaseModel):
    artifact_id:    str
    artifact_class: str
    origin_id:      str
    phase:          int
    innov_id:       str
    payload:        Dict[str, Any] = {}


class CertifyRequest(BaseModel):
    artifact_id: str
    human0_id:   str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/trace")
def trace_artifact(req: TraceRequest) -> Dict[str, Any]:
    """
    POST /cpve/trace
    Trace a constitutional artifact's provenance origin.
    CPVE-SCOPE-0, CPVE-ORIGIN-0, CPVE-CHAIN-0.
    """
    try:
        record = get_engine().trace(
            req.artifact_id, req.artifact_class,
            req.origin_id, req.phase, req.innov_id, req.payload,
        )
        return {
            "status":            "TRACED",
            "record_id":         record.record_id,
            "artifact_id":       record.artifact_id,
            "provenance_digest": record.provenance_digest,
            "timestamp":         record.timestamp,
        }
    except ScopeViolation as e:
        raise HTTPException(status_code=422, detail=str(e))
    except OrphanArtifactError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except CPVEViolation as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verify/{artifact_id}")
def verify_artifact(artifact_id: str) -> Dict[str, Any]:
    """
    GET /cpve/verify/{artifact_id}
    Verify provenance chain for a single artifact (CPVE-VERIFY-0).
    """
    report = get_engine().verify(artifact_id)
    return {
        "report_id":   report.report_id,
        "artifact_id": report.artifact_id,
        "chain_valid": report.chain_valid,
        "link_count":  report.link_count,
        "result":      report.result,
        "failures":    report.failures,
        "timestamp":   report.timestamp,
    }


@router.get("/verify-chain")
def verify_full_chain() -> Dict[str, Any]:
    """
    GET /cpve/verify-chain
    Verify the complete provenance ledger chain (CPVE-CHAIN-0).
    """
    report = get_engine().verify_chain()
    return {
        "report_id":   report.report_id,
        "chain_valid": report.chain_valid,
        "link_count":  report.link_count,
        "result":      report.result,
        "failures":    report.failures,
        "timestamp":   report.timestamp,
    }


@router.post("/certify")
def certify_artifact(req: CertifyRequest) -> Dict[str, Any]:
    """
    POST /cpve/certify
    Issue a HUMAN-0-gated provenance certificate (CPVE-CERT-0).
    """
    try:
        cert = get_engine().certify(req.artifact_id, req.human0_id)
        return {
            "status":            "ISSUED",
            "cert_id":           cert.cert_id,
            "artifact_id":       cert.artifact_id,
            "artifact_class":    cert.artifact_class,
            "provenance_digest": cert.provenance_digest,
            "human0_id":         cert.human0_id,
            "cert_digest":       cert.cert_digest,
            "issued_at":         cert.issued_at,
        }
    except CertificationDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ProvenanceGateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CPVEViolation as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/records")
def list_records() -> Dict[str, Any]:
    """
    GET /cpve/records
    List all provenance records in the ledger.
    """
    engine  = get_engine()
    records = engine.tracer.load_records()
    engine.auditor.emit("QUERY", "ALL_RECORDS", "OK", {"count": len(records)})
    return {"record_count": len(records), "records": records}


@router.get("/certificates")
def list_certificates() -> Dict[str, Any]:
    """
    GET /cpve/certificates
    List all issued provenance certificates.
    """
    engine = get_engine()
    certs  = engine.certifier.load_certificates()
    engine.auditor.emit("QUERY", "ALL_CERTS", "OK", {"count": len(certs)})
    return {"cert_count": len(certs), "certificates": certs}


@router.get("/audit")
def list_audit_entries() -> Dict[str, Any]:
    """
    GET /cpve/audit
    Return the full CPVE audit ledger (CPVE-AUDIT-0).
    """
    entries = get_engine().auditor.load_entries()
    return {"entry_count": len(entries), "entries": entries}


@router.get("/status")
def engine_status() -> Dict[str, Any]:
    """
    GET /cpve/status
    Return CPVE engine status and counters.
    """
    return get_engine().status()
