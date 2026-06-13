"""
app/api/cgml.py
Phase 221 · INNOV-126 · CGML — Constitutional Governance Meta-Ledger
FastAPI Router — 5 endpoints

Endpoints:
  POST /cgml/event              — Append an Arc II governance event
  GET  /cgml/lineage            — Build and return the full lineage matrix
  GET  /cgml/chain/verify       — Verify HMAC chain integrity
  GET  /cgml/domain/summary     — Per-domain event counts & phase coverage
  POST /cgml/attest             — Issue a HUMAN-0-authorized meta-attestation
  GET  /cgml/status             — Engine status snapshot
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from dorkllm.constitutional_governance_meta_ledger import (
    ConstitutionalGovernanceMetaLedger,
    ConstitutionalViolation,
    EntryKind,
    AttestationDenied,
    XPhaseViolation,
)

router = APIRouter(prefix="/cgml", tags=["CGML"])

_engine: Optional[ConstitutionalGovernanceMetaLedger] = None


def _get_engine() -> ConstitutionalGovernanceMetaLedger:
    global _engine
    if _engine is None:
        _engine = ConstitutionalGovernanceMetaLedger()
    return _engine


# ── Request / Response schemas ───────────────────────────────────────────────

class AppendEventRequest(BaseModel):
    kind: str
    domain: str
    phase: int
    proposal_id: Optional[str] = None
    invariant_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class AttestRequest(BaseModel):
    human0_token: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/event")
def append_event(req: AppendEventRequest) -> Dict[str, Any]:
    """
    Append a governance event from any registered Arc II domain.
    Enforces CGML-ARC2-0 (domain must be registered) and
    CGML-XPHASE-0 (phase ordering).
    """
    engine = _get_engine()
    try:
        kind_enum = EntryKind(req.kind)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown EntryKind '{req.kind}'. "
                   f"Valid: {[k.value for k in EntryKind]}",
        )
    try:
        entry = engine.append_event(
            kind=kind_enum,
            domain=req.domain,
            phase=req.phase,
            proposal_id=req.proposal_id,
            invariant_id=req.invariant_id,
            payload=req.payload or {},
        )
    except XPhaseViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "status": "APPENDED",
        "entry_id": entry.entry_id,
        "entry_hash": entry.entry_hash[:24],
        "xphase_status": entry.xphase_status,
        "lineage_status": entry.lineage_status,
    }


@router.get("/lineage")
def get_lineage_matrix() -> Dict[str, Any]:
    """
    Build and return the full invariant lineage matrix across Arc II.
    Enforces CGML-LINEAGE-0: orphan invariants are surfaced.
    """
    engine = _get_engine()
    matrices = engine.build_lineage_matrix()
    return {
        "status": "OK",
        "matrix_count": len(matrices),
        "matrices": [
            {
                "invariant_id": m.invariant_id,
                "proposal_id": m.proposal_id,
                "domains_traversed": m.domains_traversed,
                "phase_sequence": m.phase_sequence,
                "lineage_status": m.lineage_status,
                "attestation_ready": m.attestation_ready,
                "trace_entry_count": len(m.trace_entries),
            }
            for m in matrices
        ],
    }


@router.get("/chain/verify")
def verify_chain() -> Dict[str, Any]:
    """
    Verify HMAC-SHA-256 chain integrity across all meta-ledger entries.
    Enforces CGML-CHAIN-0 and CGML-REPLAY-0.
    """
    engine = _get_engine()
    result = engine.verify_chain()
    if not result["valid"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"status": "CHAIN-VALID", **result}


@router.get("/domain/summary")
def get_domain_summary() -> Dict[str, Any]:
    """
    Per-domain event count and phase coverage across all Arc II domains.
    """
    engine = _get_engine()
    summary = engine.get_domain_summary()
    return {"status": "OK", "domain_summary": summary}


@router.post("/attest")
def issue_attestation(req: AttestRequest) -> Dict[str, Any]:
    """
    Issue a HUMAN-0-authorized Meta-Ledger attestation.
    Enforces CGML-HUMAN0-0: token must be non-empty.
    """
    engine = _get_engine()
    try:
        attest = engine.issue_attestation(human0_token=req.human0_token)
    except AttestationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {
        "status": "ATTESTED" if attest.valid else "ATTESTED-WITH-BROKEN-LINEAGES",
        "attestation_id": attest.attestation_id,
        "governor": attest.governor,
        "total_entries": attest.total_entries,
        "arc2_domains_present": attest.arc2_domains_present,
        "lineage_matrix_count": attest.lineage_matrix_count,
        "broken_lineages": attest.broken_lineages,
        "chain_root_hash": attest.chain_root_hash,
        "chain_tip_hash": attest.chain_tip_hash,
        "issued_at": attest.issued_at,
        "valid": attest.valid,
    }


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """CGML engine status — phase, version, invariants, ledger path."""
    engine = _get_engine()
    return engine.get_status()
