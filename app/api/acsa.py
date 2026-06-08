# SPDX-License-Identifier: Apache-2.0
"""
INNOV-121 · ACSA REST Router — Phase 216 · v10.27.0
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.autonomous_constitutional_self_amendment import (
    AmendmentClass,
    AutonomousConstitutionalSelfAmendment,
)

router = APIRouter(prefix="/acsa", tags=["ACSA"])
_engine = AutonomousConstitutionalSelfAmendment()


class ProposeRequest(BaseModel):
    title: str = Field(..., description="Short amendment title")
    description: str = Field(..., description="Full description of the amendment")
    target_section: str = Field(..., description="Constitution section being amended")
    proposed_text: str = Field(..., description="Proposed amendment text")
    current_text: str = Field(..., description="Existing text being replaced")
    amendment_class: AmendmentClass = AmendmentClass.SOFT
    supporting_invariant_ids: List[str] = Field(
        ..., description="≥3 invariant IDs supporting this amendment (ACSA-QUORUM-0)"
    )
    justification_evidence: Dict[str, Any] = Field(default_factory=dict)
    proposed_by: str = "DEVADAAD"


class ValidateRequest(BaseModel):
    amendment_id: str
    cgvf_score: float = Field(..., ge=0.0, le=1.0)
    existing_hard_invariants: Optional[List[str]] = None


class SimulateRequest(BaseModel):
    amendment_id: str
    dry_run_passes: bool = True
    hard_invariants_affected: Optional[List[str]] = None
    soft_invariants_affected: Optional[List[str]] = None


class QueueRequest(BaseModel):
    amendment_id: str


class RatifyRequest(BaseModel):
    amendment_id: str
    human0_signature: str = Field(..., description="HUMAN-0 GPG signature — ACSA-HUMAN0-0")


class RejectRequest(BaseModel):
    amendment_id: str
    reason: str


@router.post("/propose")
def propose(req: ProposeRequest) -> Dict:
    """Propose an autonomous constitutional amendment."""
    try:
        proposal = _engine.propose(
            title=req.title,
            description=req.description,
            target_section=req.target_section,
            proposed_text=req.proposed_text,
            current_text=req.current_text,
            amendment_class=req.amendment_class,
            supporting_invariant_ids=req.supporting_invariant_ids,
            justification_evidence=req.justification_evidence,
            proposed_by=req.proposed_by,
        )
        return {
            "amendment_id": proposal.amendment_id,
            "stage": proposal.stage,
            "title": proposal.title,
            "revert_hash": proposal.revert_hash,
            "proposed_at": proposal.proposed_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/validate")
def validate(req: ValidateRequest) -> Dict:
    """Validate a proposed amendment against CGVF score and conflict checks."""
    proposal = _engine._proposals.get(req.amendment_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Amendment {req.amendment_id} not found")
    result = _engine.validate(proposal, req.cgvf_score, req.existing_hard_invariants)
    return {
        "amendment_id": req.amendment_id,
        "passed": result.passed,
        "cgvf_score": result.cgvf_score,
        "conflict_check": result.conflict_check,
        "quorum_satisfied": result.quorum_satisfied,
        "failure_reasons": result.failure_reasons,
        "stage": proposal.stage,
    }


@router.post("/simulate")
def simulate(req: SimulateRequest) -> Dict:
    """Run DAS dry-run simulation — ACSA-SIMFIRST-0."""
    proposal = _engine._proposals.get(req.amendment_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Amendment {req.amendment_id} not found")
    try:
        result = _engine.simulate(
            proposal,
            dry_run_passes=req.dry_run_passes,
            hard_invariants_affected=req.hard_invariants_affected,
            soft_invariants_affected=req.soft_invariants_affected,
        )
        return {
            "amendment_id": req.amendment_id,
            "simulation_id": result.simulation_id,
            "passed": result.passed,
            "hard_invariants_affected": result.hard_invariants_affected,
            "soft_invariants_affected": result.soft_invariants_affected,
            "breakage_detected": result.breakage_detected,
            "stage": proposal.stage,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/queue-for-ratification")
def queue_for_ratification(req: QueueRequest) -> Dict:
    """Queue a SIMULATED amendment for HUMAN-0 ratification."""
    proposal = _engine._proposals.get(req.amendment_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Amendment {req.amendment_id} not found")
    try:
        return _engine.queue_for_ratification(proposal)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/ratify")
def ratify(req: RatifyRequest) -> Dict:
    """HUMAN-0 ratification endpoint — ACSA-HUMAN0-0."""
    proposal = _engine._proposals.get(req.amendment_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Amendment {req.amendment_id} not found")
    try:
        return _engine.ratify(proposal, req.human0_signature)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/reject")
def reject(req: RejectRequest) -> Dict:
    """Explicitly reject an amendment with a sealed audit record."""
    proposal = _engine._proposals.get(req.amendment_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Amendment {req.amendment_id} not found")
    return _engine.reject(proposal, req.reason)


@router.get("/verify-chain")
def verify_chain() -> Dict:
    """Verify HMAC chain integrity — ACSA-CHAIN-0."""
    return _engine.verify_chain()


@router.get("/status")
def status() -> Dict:
    """Return ACSA engine status."""
    return _engine.status()


@router.get("/preview/{amendment_id}")
def preview(amendment_id: str) -> Dict:
    """Return human-readable amendment preview for HUMAN-0 review."""
    proposal = _engine._proposals.get(amendment_id)
    if not proposal:
        raise HTTPException(status_code=404, detail=f"Amendment {amendment_id} not found")
    return _engine.preview_amendment_report(proposal)
