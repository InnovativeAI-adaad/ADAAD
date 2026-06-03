# SPDX-License-Identifier: Apache-2.0
"""FastAPI router for INNOV-109 · AMPS — Autonomous Mutation Proposal Synthesizer.

Endpoints:
  POST /amps/synthesize           — synthesize ranked mutation proposals
  GET  /amps/proposals            — list all proposals (optional status filter)
  GET  /amps/proposals/{id}       — retrieve single proposal
  POST /amps/ratify/{id}          — HUMAN-0 ratification gate
  GET  /amps/verify-chain         — verify ProposalLedger HMAC chain
  GET  /amps/status               — AMPS system status

Governor: DUSTIN L REID · InnovativeAI LLC · Phase 204
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dorkllm.autonomous_mutation_proposal_synthesizer import (
    AutonomousMutationProposalSynthesizer,
    AMPSHuman0Error,
    AMPSCGDRGateError,
    AMPSImmutabilityError,
    AMPSViolation,
)

router = APIRouter(prefix="/amps", tags=["AMPS"])
_engine = AutonomousMutationProposalSynthesizer()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SynthesizeRequest(BaseModel):
    max_proposals: int = Field(default=3, ge=1, le=5, description="Number of proposals to synthesize (1-5)")
    requester: str = Field(default="SYSTEM", description="Requesting agent or user ID")


class RatifyRequest(BaseModel):
    human_id: str = Field(..., description="HUMAN-0 authority identifier for ratification")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/synthesize")
def synthesize_proposals(req: SynthesizeRequest) -> dict:
    """POST /amps/synthesize — Synthesize ranked mutation proposals.

    Analyzes innovation history, CGDR health, and invariant gap patterns
    to produce a constitutional fitness-ranked ProposalManifest.
    """
    try:
        result = _engine.synthesize(
            max_proposals=req.max_proposals,
            requester=req.requester,
        )
        return result
    except AMPSViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        # AMPS-FAILCLOSED-0: unexpected errors return NO_PROPOSAL, not 500
        return {"outcome": "NO_PROPOSAL", "error": str(exc)}


@router.get("/proposals")
def list_proposals(
    status: Optional[str] = Query(default=None, description="Filter by status: PENDING, RATIFIED, REJECTED, EXPIRED"),
) -> dict:
    """GET /amps/proposals — List all proposals, ranked by constitutional_fitness."""
    proposals = _engine.get_proposals(status_filter=status)
    return {
        "proposals": proposals,
        "count": len(proposals),
        "filter": status,
    }


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str) -> dict:
    """GET /amps/proposals/{id} — Retrieve a single proposal by deterministic ID."""
    try:
        return _engine.get_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/ratify/{proposal_id}")
def ratify_proposal(proposal_id: str, req: RatifyRequest) -> dict:
    """POST /amps/ratify/{id} — HUMAN-0 ratification gate.

    Enforces AMPS-HUMAN0-0 (authority check) and AMPS-CGDR-0 (drift gate).
    Sealed proposals cannot be re-ratified (AMPS-IMMUT-0).
    """
    try:
        return _engine.ratify_proposal(
            proposal_id=proposal_id,
            human_id=req.human_id,
        )
    except AMPSHuman0Error as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except AMPSCGDRGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AMPSImmutabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/verify-chain")
def verify_chain() -> dict:
    """GET /amps/verify-chain — Verify ProposalLedger HMAC chain integrity (AMPS-CHAIN-0)."""
    return _engine.verify_chain()


@router.get("/status")
def get_status() -> dict:
    """GET /amps/status — AMPS system status: CGDR gate, proposal counts, invariants."""
    return _engine.get_status()
