"""REST API — Constitutional Mutation Admission Controller (CMAC) — Phase 201"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from dorkllm.constitutional_mutation_admission_controller import (
    ConstitutionalMutationAdmissionController, CMACAdmissionLedger,
    AdmissionRequest, BlastRadius,
    CMACConstitutionalViolation, CMACOverrideUnauthorized, GOVERNOR,
)
import uuid

router = APIRouter(prefix="/cmac", tags=["CMAC"])
_cmac = ConstitutionalMutationAdmissionController(ledger=CMACAdmissionLedger())


class AdmitRequest(BaseModel):
    mutation_id: str
    blast_radius: str
    invariant_classes: List[str] = ["Hard"]
    proposed_by: str = "MutationAgent"
    human0_pre_auth: bool = False
    quorum_confirmed: bool = False
    metadata: Optional[Dict[str, Any]] = None


class OverrideRequest(BaseModel):
    request_id: str
    human0_identity: str


@router.post("/admit")
def admit(req: AdmitRequest) -> Dict[str, Any]:
    """Run full admission pipeline. CMAC-ORDER-0, CMAC-FAILCLOSED-0."""
    try:
        ar = AdmissionRequest(
            request_id=str(uuid.uuid4()),
            mutation_id=req.mutation_id,
            blast_radius=BlastRadius(req.blast_radius),
            invariant_classes=req.invariant_classes,
            proposed_by=req.proposed_by,
            human0_pre_auth=req.human0_pre_auth,
            quorum_confirmed=req.quorum_confirmed,
            metadata=req.metadata or {},
        )
        record = _cmac.admit(ar)
        return record.to_dict()
    except CMACConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/override")
def override(req: OverrideRequest) -> Dict[str, Any]:
    """HUMAN-0 override of DENIED admission. CMAC-OVERRIDE-0."""
    try:
        return _cmac.override(req.request_id, req.human0_identity).to_dict()
    except CMACOverrideUnauthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CMACConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/chain/verify")
def verify_chain() -> Dict[str, Any]:
    """CMAC-CHAIN-0."""
    try:
        return {"chain_valid": _cmac.verify_chain(), "governor": GOVERNOR}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/summary")
def summary() -> Dict[str, Any]:
    return _cmac.summary()


@router.get("/export")
def export() -> Dict[str, Any]:
    return _cmac.export()
