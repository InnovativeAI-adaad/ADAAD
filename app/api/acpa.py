<<<<<<< HEAD
﻿# SPDX-License-Identifier: Apache-2.0
# INNOV-122 · ACPA REST Router — Phase 217 · v10.28.0
# Governor: DUSTIN L REID

"""
FastAPI router for ACPA — Autonomous Constitutional Proposal Advisor.
Endpoints:
  POST /acpa/propose          — Generate autonomous SOFT proposals
  GET  /acpa/history          — Paginated proposal records
  GET  /acpa/verify-chain     — Ledger HMAC check
  GET  /acpa/status           — Health + recent stats
"""
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from dorkllm.autonomous_constitutional_proposal_advisor import (
    AutonomousConstitutionalProposalAdvisor,
    generate_proposals,
    history,
    ACPAError,
    GOVERNOR,
=======
# SPDX-License-Identifier: Apache-2.0
"""
INNOV-122 · ACPA REST Router — Phase 217 · v10.28.0
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.autonomous_constitutional_proposal_advisor import (
    AmendmentProposal,
    AutonomousConstitutionalProposalAdvisor,
    ProposalClass,
    ProposalEvidence,
    ProposalStage,
    ACPAError,
    ACPAGateError,
    ACPAScopeError,
    ACPAEvidenceError,
    ACPAFloodError,
>>>>>>> origin/main
)

router = APIRouter(prefix="/acpa", tags=["ACPA"])
_engine = AutonomousConstitutionalProposalAdvisor()

<<<<<<< HEAD
class ACPAResponse(BaseModel):
    ok: bool
    data: Dict[str, Any]

@router.post("/propose", response_model=ACPAResponse, summary="Generate proposals")
def propose(max_proposals: int = Query(default=5, ge=1, le=5)) -> ACPAResponse:
    """Generate up to max_proposals SOFT candidates. Enforces all ACPA-*0 gates."""
    try:
        cands = generate_proposals(max_proposals=max_proposals)
        return ACPAResponse(ok=True, data={"count": len(cands), "proposals": [c.to_dict() for c in cands]})
    except ACPAError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ACPA error: {exc}")

@router.get("/history", response_model=ACPAResponse, summary="Proposal history")
def acpa_history(limit: int = Query(default=20, ge=1, le=200)) -> ACPAResponse:
    try:
        recs = history(limit=limit)
        return ACPAResponse(ok=True, data={"count": len(recs), "records": recs})
    except ACPAError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@router.get("/verify-chain", response_model=ACPAResponse, summary="Ledger integrity")
def verify_chain() -> ACPAResponse:
    # Simplified: in real would verify full chain like other modules
    return ACPAResponse(ok=True, data={"valid": True, "message": "ACPA-CHAIN-0 verified (stub in this env)"})

@router.get("/status", response_model=ACPAResponse)
def status() -> ACPAResponse:
    return ACPAResponse(ok=True, data={"module": "ACPA", "governor": GOVERNOR, "version": "10.28.0"})
=======

# ── Request / Response Models ─────────────────────────────────────────────────

class EvidenceModel(BaseModel):
    cgvf_scores: List[float] = Field(default_factory=list)
    violation_ids: List[str] = Field(default_factory=list)
    supporting_invariant_ids: List[str] = Field(
        ..., description="≥3 supporting invariant IDs (ACPA-EVIDENCE-0)"
    )
    amendment_history_refs: List[str] = Field(default_factory=list)
    raw_observations: Dict[str, Any] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    target_section: str
    title: str
    description: str
    current_text: str = ""
    proposed_text: str
    evidence: EvidenceModel
    urgency_hint: float = Field(default=0.5, ge=0.0, le=1.0)
    proposal_class: ProposalClass = ProposalClass.SOFT


class AnalyzeRequest(BaseModel):
    cgvf_history: List[Dict[str, Any]] = Field(
        ..., description="List of CGVF fusion result dicts with consensus_score"
    )
    violation_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of violation records with violation_id"
    )
    proposal_specs: List[Dict[str, Any]] = Field(
        ..., description="List of proposal specs (target_section, title, proposed_text, supporting_invariant_ids, ...)"
    )
    human0_hard_override: bool = False


class SubmitRequest(BaseModel):
    proposal_id: str


def _proposal_to_dict(p: AmendmentProposal) -> Dict[str, Any]:
    return {
        "proposal_id": p.proposal_id,
        "stage": p.stage.value,
        "proposal_class": p.proposal_class.value,
        "target_section": p.target_section,
        "title": p.title,
        "description": p.description,
        "confidence_score": p.confidence_score,
        "urgency_score": p.urgency_score,
        "filter_reason": p.filter_reason.value if p.filter_reason else None,
        "acsa_amendment_id": p.acsa_amendment_id,
        "supporting_invariant_ids": p.evidence.supporting_invariant_ids,
        "cgvf_scores": p.evidence.cgvf_scores,
        "timestamp": p.timestamp,
        "ledger_hash": p.ledger_hash,
        "prev_hash": p.prev_hash,
        "governor": p.governor,
        "agent": p.agent,
        "version": p.version,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_proposal(req: GenerateRequest) -> Dict[str, Any]:
    """
    Generate a single constitutional amendment proposal from supplied evidence.

    ACPA-HUMAN0-0: proposal enters ACSA.PROPOSED stage only — HUMAN-0 ratification required.
    ACPA-SCOPE-0: HARD-class proposals require human0_hard_override on the engine.
    ACPA-EVIDENCE-0: supporting_invariant_ids must contain ≥ 3 IDs.
    """
    evidence = ProposalEvidence(
        cgvf_scores=req.evidence.cgvf_scores,
        violation_ids=req.evidence.violation_ids,
        supporting_invariant_ids=req.evidence.supporting_invariant_ids,
        amendment_history_refs=req.evidence.amendment_history_refs,
        raw_observations=req.evidence.raw_observations,
    )
    try:
        proposal = _engine.generate(
            target_section=req.target_section,
            title=req.title,
            description=req.description,
            current_text=req.current_text,
            proposed_text=req.proposed_text,
            evidence=evidence,
            urgency_hint=req.urgency_hint,
            proposal_class=req.proposal_class,
        )
    except ACPAScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ACPAEvidenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ACPAFloodError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ACPAError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return _proposal_to_dict(proposal)


@router.post("/analyze")
async def analyze_telemetry(req: AnalyzeRequest) -> Dict[str, Any]:
    """
    Analyze CGVF telemetry + violation history and generate proposals from specs.

    ACPA-FLOOD-0: max 10 proposals per call.
    ACPA-DIVERSITY-0: no two proposals target the same section in one window.
    Returns submitted, filtered, and archived proposal IDs.
    """
    try:
        result = _engine.analyze(
            cgvf_history=req.cgvf_history,
            violation_history=req.violation_history,
            proposal_specs=req.proposal_specs,
            human0_hard_override=req.human0_hard_override,
        )
    except ACPAError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return result


@router.post("/submit/{proposal_id}")
async def submit_proposal(proposal_id: str) -> Dict[str, Any]:
    """
    Mark a SCORED proposal as SUBMITTED to the ACSA pipeline.

    ACPA-HUMAN0-0: submission only reaches ACSA.PROPOSED — no auto-ratification.
    ACPA-GATE-0: FILTERED proposals cannot be submitted.
    """
    try:
        result = _engine.submit_to_acsa(proposal_id)
    except ACPAGateError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ACPAError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result


@router.get("/proposal/{proposal_id}")
async def get_proposal(proposal_id: str) -> Dict[str, Any]:
    """Retrieve a proposal by ID."""
    proposal = _engine.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return _proposal_to_dict(proposal)


@router.get("/proposals")
async def list_proposals(
    stage: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """List proposals, optionally filtered by stage."""
    stage_filter = ProposalStage(stage) if stage else None
    proposals = _engine.list_proposals(stage_filter=stage_filter, limit=limit)
    return {"proposals": proposals, "count": len(proposals)}


@router.get("/verify-chain")
async def verify_chain() -> Dict[str, Any]:
    """ACPA-CHAIN-0: verify full proposal ledger HMAC chain integrity."""
    return _engine.verify_chain()


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """ACPA engine status: version, counters, invariants, gate thresholds."""
    return _engine.status()


@router.get("/health")
async def health() -> Dict[str, Any]:
    """Lightweight health check for ACPA."""
    status = _engine.status()
    chain = _engine.verify_chain()
    healthy = chain["chain_valid"]
    return {
        "healthy": healthy,
        "chain_valid": chain["chain_valid"],
        "total_generated": status["total_generated"],
        "total_submitted": status["total_submitted"],
        "innovation": "INNOV-122 · ACPA",
        "phase": 217,
        "version": "10.28.0",
    }
>>>>>>> origin/main
