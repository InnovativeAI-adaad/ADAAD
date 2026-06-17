# SPDX-License-Identifier: Apache-2.0
"""
app/api/cade.py
Phase 225 · INNOV-130 · CADE — Constitutional Autonomous Decision Engine
FastAPI Router — 8 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 01
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_autonomous_decision_engine import (
    AttestationEngine,
    CADEEngine,
    CADEViolation,
    ChainBreakError,
    GateBlockError,
    HUMAN0VetoError,
    ImmutabilityViolation,
    OriginViolation,
    ScopeViolation,
)

router = APIRouter(prefix="/cade", tags=["CADE"])

# ── Singleton engine ──────────────────────────────────────────────────────────
_engine = CADEEngine()


# ── Request / Response models ─────────────────────────────────────────────────
class EvaluateRequest(BaseModel):
    synthesis_id: str = Field(..., description="CASL CHI synthesis_id (CADE-ORIGIN-0)")
    chi_score: float = Field(..., ge=0.0, le=1.0, description="Constitutional Health Index score")
    mutation_ref: str = Field(..., description="Caller-provided mutation identifier")


class VetoRequest(BaseModel):
    veto_by: str = Field(..., description="HUMAN-0 identifier (CADE-HUMAN0-0)")
    reason: str = Field(..., description="Reason for veto")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/evaluate", summary="Evaluate mutation against CHI")
def evaluate(req: EvaluateRequest) -> Dict[str, Any]:
    """
    POST /cade/evaluate
    Evaluate a mutation's promotion eligibility against the Constitutional Health Index.
    CADE-ORIGIN-0: synthesis_id must be a valid CASL CHI reference.
    CADE-GATE-0: CHI < 0.80 → no PROMOTE.
    CADE-DETERM-0: identical inputs → identical verdict.
    CADE-ATTEST-0: PROMOTE decisions carry HMAC-SHA-256 attestation.
    CADE-CHAIN-0: decision sealed into HMAC chain.
    """
    try:
        record = _engine.evaluate(
            synthesis_id=req.synthesis_id,
            chi_score=req.chi_score,
            mutation_ref=req.mutation_ref,
        )
    except OriginViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except GateBlockError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CADEViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "DECISION_SEALED",
        "record_id": record.record_id,
        "synthesis_id": record.synthesis_id,
        "chi_score": record.chi_score,
        "verdict": record.verdict.value,
        "mutation_ref": record.mutation_ref,
        "attested": bool(record.attestation_hmac),
        "sealed_ts": record.sealed_ts,
        "state": record.state.value,
    }


@router.get("/decision/{record_id}", summary="Retrieve a specific decision")
def get_decision(record_id: str) -> Dict[str, Any]:
    """
    GET /cade/decision/{record_id}
    Retrieve a specific decision record by ID.
    """
    record = _engine.get_decision(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Decision {record_id} not found")
    return record.to_dict()


@router.get("/decisions", summary="List all decision records")
def list_decisions() -> Dict[str, Any]:
    """
    GET /cade/decisions
    List all sealed decision records.
    """
    records = _engine.all_decisions()
    return {
        "count": len(records),
        "decisions": [r.to_dict() for r in records],
    }


@router.post("/veto/{record_id}", summary="HUMAN-0 veto a PROMOTE decision")
def veto(record_id: str, req: VetoRequest) -> Dict[str, Any]:
    """
    POST /cade/veto/{record_id}
    HUMAN-0 veto a PROMOTE decision.
    CADE-HUMAN0-0: structurally enforced — non-delegable authority.
    Only applies to PROMOTE decisions.
    """
    try:
        entry = _engine.veto(
            record_id=record_id,
            veto_by=req.veto_by,
            reason=req.reason,
        )
    except HUMAN0VetoError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CADEViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "status": "VETOED",
        "record_id": record_id,
        "veto_by": req.veto_by,
        "veto_ts": entry.record.veto_ts,
        "reason": req.reason,
    }


@router.get("/verify-chain", summary="Verify HMAC chain integrity")
def verify_chain() -> Dict[str, Any]:
    """
    GET /cade/verify-chain
    Verify the decision ledger and audit log HMAC chains.
    CADE-CHAIN-0: recomputes every entry hash from scratch.
    """
    return _engine.verify_chain()


@router.get("/attestation/{record_id}", summary="Verify PROMOTE attestation")
def verify_attestation(record_id: str) -> Dict[str, Any]:
    """
    GET /cade/attestation/{record_id}
    Verify a PROMOTE decision's HMAC-SHA-256 attestation.
    CADE-ATTEST-0: cryptographic integrity check.
    """
    try:
        valid = _engine.verify_attestation(record_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Decision {record_id} not found")
    return {
        "record_id": record_id,
        "attestation_valid": valid,
    }


@router.get("/audit", summary="Retrieve audit log")
def get_audit() -> Dict[str, Any]:
    """
    GET /cade/audit
    Retrieve the full HMAC-chained audit log.
    CADE-AUDIT-0: every operation is logged.
    """
    entries = _engine.all_audit_entries()
    return {
        "count": len(entries),
        "entries": [e.to_dict() for e in entries],
    }


@router.get("/matrix", summary="Retrieve decision matrix thresholds")
def get_matrix() -> Dict[str, Any]:
    """
    GET /cade/matrix
    Retrieve the current decision matrix thresholds and rules.
    CADE-DETERM-0: deterministic verdict mapping.
    CADE-GATE-0: PROMOTE threshold enforced.
    """
    return _engine.matrix()


@router.get("/status", summary="Engine status and invariant roster")
def get_status() -> Dict[str, Any]:
    """
    GET /cade/status
    Engine health, invariant roster, and counters.
    """
    return _engine.status()
