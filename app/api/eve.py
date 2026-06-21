# SPDX-License-Identifier: Apache-2.0
"""
app/api/eve.py
Phase 233 · INNOV-138 · EVE — External Verifiability Engine
FastAPI Router — 10 constitutional endpoints
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc IV — External Verifiability & Federation · Module 01
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.external_verifiability_engine import (
    EVEEngine,
    EVEViolation,
    BundleDigestError,
    ChainBreakError,
    ImmutabilityViolation,
    ScopeViolation,
    PublicationGateError,
    VerificationFailure,
    ExportError,
    CHIProof,
    ACICycleProof,
    InvariantRegisterProof,
    SPIEProof,
)

router = APIRouter(prefix="/eve", tags=["EVE"])
_engine = EVEEngine(instance_id="eve-api-default")


# ── Request models ─────────────────────────────────────────────────────────────

class CHIProofIn(BaseModel):
    epoch_id: str
    chi_score: float = Field(..., ge=0.0, le=1.0)
    invariant_count: int = Field(..., ge=0)
    measurement_ts: float
    source_module: str
    chain_ref: str


class ACICycleProofIn(BaseModel):
    cycle_id: str
    outcome: str = Field(..., description="PROMOTED|HELD|REJECTED|STALLED")
    stages_completed: List[str]
    cycle_started_at: float
    cycle_closed_at: float
    cacg_proof_digest: str


class InvariantRegisterProofIn(BaseModel):
    epoch_id: str
    total_invariants: int = Field(..., ge=0)
    register_digest: str
    snapshot_ts: float
    version: str


class SPIEProofIn(BaseModel):
    proposal_id: str
    epoch_id: str
    ratified_by: str
    proposal_digest: str
    chain_link: str


class CreateBundleRequest(BaseModel):
    epoch_id: str
    chi_proofs: Optional[List[CHIProofIn]] = None
    aci_cycle_proofs: Optional[List[ACICycleProofIn]] = None
    invariant_register_proofs: Optional[List[InvariantRegisterProofIn]] = None
    spie_proofs: Optional[List[SPIEProofIn]] = None


class SealBundleRequest(BaseModel):
    human0_identity: str = Field(..., description="HUMAN-0 identity (EVE-HUMAN0-0)")


class PublishBundleRequest(BaseModel):
    human0_identity: str = Field(..., description="HUMAN-0 identity (EVE-HUMAN0-0)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_chi(p: CHIProofIn) -> CHIProof:
    return CHIProof(**p.model_dump())


def _to_aci(p: ACICycleProofIn) -> ACICycleProof:
    return ACICycleProof(**p.model_dump())


def _to_inv(p: InvariantRegisterProofIn) -> InvariantRegisterProof:
    return InvariantRegisterProof(**p.model_dump())


def _to_spie(p: SPIEProofIn) -> SPIEProof:
    return SPIEProof(**p.model_dump())


def _eve_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ScopeViolation, PublicationGateError, BundleDigestError)):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ImmutabilityViolation):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, VerificationFailure):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ChainBreakError):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status() -> Dict[str, Any]:
    """EVE engine status and chain integrity report."""
    return _engine.status()


@router.post("/bundles", status_code=201)
def create_bundle(req: CreateBundleRequest) -> Dict[str, Any]:
    """
    Create a DRAFT AttestationBundle.
    EVE-SCOPE-0: at least one proof type required.
    """
    try:
        bundle = _engine.create_bundle(
            epoch_id=req.epoch_id,
            chi_proofs=[_to_chi(p) for p in req.chi_proofs] if req.chi_proofs else None,
            aci_cycle_proofs=[_to_aci(p) for p in req.aci_cycle_proofs] if req.aci_cycle_proofs else None,
            invariant_register_proofs=[_to_inv(p) for p in req.invariant_register_proofs] if req.invariant_register_proofs else None,
            spie_proofs=[_to_spie(p) for p in req.spie_proofs] if req.spie_proofs else None,
        )
        return {"bundle_id": bundle.bundle_id, "status": bundle.status.value,
                "proof_sources": bundle.proof_sources, "epoch_id": bundle.epoch_id}
    except EVEViolation as exc:
        raise _eve_error(exc)


@router.post("/bundles/{bundle_id}/seal")
def seal_bundle(bundle_id: str, req: SealBundleRequest) -> Dict[str, Any]:
    """
    Seal a DRAFT bundle. EVE-HUMAN0-0: non-empty HUMAN-0 identity required.
    EVE-BUNDLE-0 + EVE-CHAIN-0 enforced.
    """
    try:
        bundle = _engine.seal_bundle(bundle_id, req.human0_identity, time.time())
        return {
            "bundle_id": bundle.bundle_id,
            "status": bundle.status.value,
            "bundle_digest": bundle.bundle_digest,
            "chain_link": bundle.chain_link,
        }
    except (EVEViolation, KeyError) as exc:
        raise _eve_error(exc)


@router.post("/bundles/{bundle_id}/publish")
def publish_bundle(bundle_id: str, req: PublishBundleRequest) -> Dict[str, Any]:
    """
    Publish a SEALED bundle. EVE-HUMAN0-0 enforced.
    """
    try:
        bundle = _engine.publish_bundle(bundle_id, req.human0_identity, time.time())
        return {
            "bundle_id": bundle.bundle_id,
            "status": bundle.status.value,
            "published_by": bundle.published_by,
            "published_at": bundle.published_at,
        }
    except (EVEViolation, KeyError) as exc:
        raise _eve_error(exc)


@router.get("/bundles/{bundle_id}/verify")
def verify_bundle(bundle_id: str) -> Dict[str, Any]:
    """
    EVE-VERIFY-0: recompute bundle_digest and confirm match.
    Returns verification report.
    """
    try:
        return _engine.verify_bundle(bundle_id)
    except (EVEViolation, KeyError) as exc:
        raise _eve_error(exc)


@router.get("/bundles/{bundle_id}/export")
def export_bundle(bundle_id: str) -> Dict[str, Any]:
    """
    EVE-EXTERN-0: self-contained export JSON for third-party verification.
    No private secrets embedded.
    """
    try:
        return _engine.export_bundle(bundle_id)
    except (EVEViolation, KeyError) as exc:
        raise _eve_error(exc)


@router.get("/bundles/{bundle_id}")
def get_bundle(bundle_id: str) -> Dict[str, Any]:
    """Retrieve bundle metadata by ID."""
    bundle = _engine.get_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Bundle {bundle_id!r} not found.")
    return bundle.to_dict()


@router.get("/bundles")
def list_bundles() -> Dict[str, Any]:
    """List all AttestationBundles."""
    return {
        "bundles": [b.to_dict() for b in _engine.all_bundles()],
        "count": len(_engine.all_bundles()),
    }


@router.get("/ledger")
def get_ledger() -> Dict[str, Any]:
    """EVE-CHAIN-0: return all ledger entries."""
    return {
        "entries": _engine.ledger_entries(),
        "count": len(_engine.ledger_entries()),
        "chain_integrity": _engine.verify_ledger_chain(),
    }


@router.get("/audit")
def get_audit() -> Dict[str, Any]:
    """EVE-AUDIT-0: return parallel audit log."""
    records = _engine.audit_records()
    return {"records": records, "count": len(records)}
