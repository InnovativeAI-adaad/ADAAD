# SPDX-License-Identifier: Apache-2.0
"""
INNOV-97 · ILV — Invariant Lineage Verifier REST API
Phase 192 · v10.3.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from dorkllm.invariant_lineage_verifier import (
    INNOVATION_CODE,
    INNOVATION_NAME,
    JOURNAL_FILE,
    PHASE,
    VERSION,
    InvariantLineageVerifier,
    ILVHuman0Escalation,
    ILVScopeViolation,
    LineageStatus,
    RuntimeDeterminismProvider,
    _build_invariant_registry,
)

router = APIRouter(prefix="/ilv", tags=["ILV — Invariant Lineage Verifier"])

_engine = InvariantLineageVerifier(journal_path=JOURNAL_FILE)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    fixed_ts: Optional[str] = None


class ClearHuman0Request(BaseModel):
    authority: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/verify")
async def verify_all(req: VerifyRequest) -> Dict[str, Any]:
    """
    Execute a full invariant lineage verification run (ILV-SCOPE-0).
    Returns a sealed LineageAttestation.
    Raises 409 if any chain is broken (ILV-HUMAN0-0).
    """
    det = RuntimeDeterminismProvider(fixed_ts=req.fixed_ts) if req.fixed_ts else None
    engine = InvariantLineageVerifier(
        determinism=det, journal_path=JOURNAL_FILE
    )
    try:
        attestation = engine.verify_all()
        return {
            "status": "ATTESTED",
            "attestation_id": attestation.attestation_id,
            "phase": attestation.phase,
            "version": attestation.version,
            "total_invariants": attestation.total_invariants,
            "verified_count": attestation.verified_count,
            "broken_count": attestation.broken_count,
            "escalated": attestation.escalated,
            "constitutional_seal": attestation.constitutional_seal,
            "verification_ts": attestation.verification_ts,
            "human0_required": attestation.human0_required,
            "run_hmac": attestation.run_hmac,
            "innovation": INNOVATION_CODE,
        }
    except ILVHuman0Escalation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ILVScopeViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/verify/{invariant_id}")
async def verify_single(invariant_id: str) -> Dict[str, Any]:
    """
    Inspect lineage for a single invariant by ID (non-scope-complete, read-only).
    """
    record = _engine.verify_single(invariant_id)
    return {
        "record_id": record.record_id,
        "invariant_id": record.invariant_id,
        "innovation_code": record.innovation_code,
        "introduction_phase": record.introduction_phase,
        "introduction_version": record.introduction_version,
        "status": record.status.value,
        "verification_ts": record.verification_ts,
        "chain_hmac": record.chain_hmac,
        "seal": record.seal,
        "escalation_reason": record.escalation_reason,
    }


@router.get("/history")
async def history(limit: int = Query(default=20, ge=1, le=200)) -> Dict[str, Any]:
    """Return the last N entries from the ILV lineage journal."""
    entries = _engine.get_journal_entries(limit=limit)
    return {
        "entries": entries,
        "count": len(entries),
        "journal": JOURNAL_FILE,
        "innovation": INNOVATION_CODE,
    }


@router.get("/chain-status")
async def chain_status() -> Dict[str, Any]:
    """Return current HUMAN-0 flag state and registry size."""
    registry = _build_invariant_registry()
    return {
        "human0_flagged": _engine.is_human0_flagged(),
        "registry_size": len(registry),
        "journal_exists": os.path.exists(JOURNAL_FILE),
        "innovation": INNOVATION_CODE,
        "phase": PHASE,
        "version": VERSION,
    }


@router.post("/clear-human0")
async def clear_human0(req: ClearHuman0Request) -> Dict[str, Any]:
    """
    Clear the HUMAN-0 escalation flag (ILV-HUMAN0-0).
    Only the GOVERNOR may invoke this endpoint.
    """
    try:
        _engine.clear_human0_flag(req.authority)
        return {"status": "CLEARED", "authority": req.authority, "innovation": INNOVATION_CODE}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/advisory")
async def advisory() -> Dict[str, Any]:
    """Return ILV module metadata and constitutional advisory."""
    return {
        "innovation": INNOVATION_CODE,
        "name": INNOVATION_NAME,
        "phase": PHASE,
        "version": VERSION,
        "invariants": [
            "ILV-CHAIN-0", "ILV-HUMAN0-0", "ILV-IMMUT-0", "ILV-DETERM-0",
            "ILV-SCOPE-0", "ILV-ATOMIC-0", "ILV-AUDIT-0", "ILV-REPLAY-0",
            "ILV-SEAL-0", "ILV-COMPLETE-0",
        ],
        "world_first": (
            "First constitutionally-governed, cryptographically-sealed "
            "invariant lineage verification engine to produce HMAC-chained "
            "provenance attestations for every Hard-class invariant in a "
            "governed AI system at scale."
        ),
        "endpoints": [
            "POST /ilv/verify",
            "GET  /ilv/verify/{invariant_id}",
            "GET  /ilv/history",
            "GET  /ilv/chain-status",
            "POST /ilv/clear-human0",
            "GET  /ilv/advisory",
        ],
    }
