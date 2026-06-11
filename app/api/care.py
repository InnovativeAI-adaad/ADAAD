# SPDX-License-Identifier: Apache-2.0
# INNOV-124 · CARE REST Router — Phase 219 · v10.30.0
# Governor: DUSTIN L REID

"""
FastAPI router for CARE — Constitutional Amendment Ratification Engine.
Endpoints:
  POST /care/promote            — Execute a ratified amendment promotion
  GET  /care/status/{wire_id}   — Query promotion status by Wire ID
  GET  /care/certificate/{wire_id} — Retrieve signed execution certificate
  GET  /care/registry/diff      — Return last applied constitutional diff
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path as FPath, Query
from pydantic import BaseModel, Field

from dorkllm.constitutional_amendment_ratification_engine import (
    ConstitutionalAmendmentRatificationEngine,
    RatificationPayload,
    CAREError,
    CAREIntakeError,
    CAREHuman0Error,
    CAREAtomicError,
    CAREHMACError,
    CAREReplayError,
    GOVERNOR,
    INNOV,
    VERSION,
    promote,
    get_status,
    get_certificate,
    registry_diff,
    verify_chain,
    status,
)

router = APIRouter(prefix="/care", tags=["CARE"])
_engine = ConstitutionalAmendmentRatificationEngine()


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class DiffEntryRequest(BaseModel):
    action: str = Field(..., description="ADD | REINFORCE | TOMBSTONE | STABLE")
    invariant_id: str
    new_text: Optional[str] = None
    tombstone_reason: Optional[str] = None
    successor_id: Optional[str] = None


class PromoteRequest(BaseModel):
    wire_id: str = Field(..., description="Wire ID from ACAM/ACSA amendment queue")
    amendment_id: str
    title: str
    amendment_class: str = Field("SOFT", description="SOFT | HARD")
    human0_ratification_ts: str = Field(
        ..., description="ISO-8601 timestamp of HUMAN-0 ratification (CARE-HUMAN0-0)"
    )
    human0_ratification_ref: str = Field(
        ..., description="GPG sig ref or session token (CARE-HUMAN0-0)"
    )
    proposed_by: str = "DEVADAAD"
    diff_entries: List[DiffEntryRequest]
    supporting_invariant_ids: List[str] = []
    revert_hash: str = ""
    content_hash: str = ""


class CAREResponse(BaseModel):
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    innov: str = INNOV
    version: str = VERSION
    governor: str = GOVERNOR


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/promote", response_model=CAREResponse, summary="Execute ratified amendment promotion")
async def promote_amendment(req: PromoteRequest) -> CAREResponse:
    """
    Execute a HUMAN-0-ratified constitutional amendment into the live invariant registry.

    Enforces all 10 CARE hard-class invariants (fail-closed).
    On success: registry updated atomically, HMAC ledger extended, certificate emitted.
    On failure: rollback manifest written, ledger appended with FAILED event.
    """
    payload = RatificationPayload(
        wire_id=req.wire_id,
        amendment_id=req.amendment_id,
        title=req.title,
        amendment_class=req.amendment_class,
        human0_ratification_ts=req.human0_ratification_ts,
        human0_ratification_ref=req.human0_ratification_ref,
        proposed_by=req.proposed_by,
        diff_entries=[e.model_dump() for e in req.diff_entries],
        supporting_invariant_ids=req.supporting_invariant_ids,
        revert_hash=req.revert_hash,
        content_hash=req.content_hash,
    )
    try:
        result = _engine.promote(payload)
        return CAREResponse(ok=True, data=result)
    except CAREIntakeError as e:
        raise HTTPException(status_code=400, detail=f"CARE-INTAKE-0: {e}")
    except CAREHuman0Error as e:
        raise HTTPException(status_code=403, detail=f"CARE-HUMAN0-0: {e}")
    except CAREReplayError as e:
        raise HTTPException(status_code=409, detail=f"CARE-REPLAY-0: {e}")
    except CAREAtomicError as e:
        raise HTTPException(status_code=500, detail=f"CARE-ATOMIC-0: {e}")
    except CAREHMACError as e:
        raise HTTPException(status_code=500, detail=f"CARE-HMAC-0: {e}")
    except CAREError as e:
        raise HTTPException(status_code=500, detail=f"CARE constitutional violation: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CARE internal error: {e}")


@router.get("/status/{wire_id}", response_model=CAREResponse, summary="Query promotion status by Wire ID")
async def promotion_status(
    wire_id: str = FPath(..., description="Wire ID to query"),
) -> CAREResponse:
    """
    Query the execution ledger for the latest promotion status for a given Wire ID.
    Returns NOT_FOUND if the wire_id has no ledger entries.
    """
    try:
        result = _engine.get_status(wire_id)
        return CAREResponse(ok=True, data=result)
    except CAREError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/certificate/{wire_id}", response_model=CAREResponse, summary="Retrieve signed execution certificate")
async def get_cert(
    wire_id: str = FPath(..., description="Wire ID for certificate lookup"),
) -> CAREResponse:
    """
    Retrieve the signed execution certificate for a completed amendment promotion.
    Certificate is HMAC-signed and readable by CGVE and ACAM for cross-validation (CARE-CERT-0).
    Returns 404 if no certificate exists for the given Wire ID.
    """
    try:
        cert = _engine.get_certificate(wire_id)
        if cert is None:
            raise HTTPException(status_code=404, detail=f"No certificate found for wire_id={wire_id}")
        return CAREResponse(ok=True, data=cert)
    except HTTPException:
        raise
    except CAREError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/registry/diff", response_model=CAREResponse, summary="Return last applied constitutional diff")
async def get_registry_diff(
    verify: bool = Query(False, description="If true, also verify HMAC chain integrity"),
) -> CAREResponse:
    """
    Return the last applied constitutional diff from the execution ledger.
    Provides CGVE and ACAM with a post-promotion inspection surface.
    Optionally verifies HMAC chain integrity when verify=true.
    """
    try:
        diff_data = _engine.registry_diff()
        if verify:
            chain_result = _engine.verify_chain()
            diff_data["chain_verification"] = chain_result
        return CAREResponse(ok=True, data=diff_data)
    except CAREError as e:
        raise HTTPException(status_code=500, detail=str(e))
