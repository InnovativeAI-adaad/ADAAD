"""
INNOV-103 CMCE — Constitutional Mutation Consensus Engine
API Layer — Phase 198 · v10.9.0 · InnovativeAI LLC · DUSTIN L REID (HUMAN-0)

Endpoints:
  POST /cmce/round/open
  POST /cmce/round/{round_id}/vote
  POST /cmce/round/{round_id}/human0/veto
  POST /cmce/round/{round_id}/human0/override
  POST /cmce/round/{round_id}/close
  POST /cmce/round/{round_id}/resolve_challenge
  GET  /cmce/round/{round_id}
  GET  /cmce/summary
  GET  /cmce/chain/verify
  GET  /cmce/export
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_consensus_engine import (
    ConstitutionalMutationConsensusEngine,
    VoteType,
    ConsensusOutcome,
    CMCEError,
    CMCEQuorumTampered,
    CMCEDuplicateVote,
    CMCEUnknownAgent,
    CMCEVoteMissing,
    CMCEHuman0Bypass,
    CMCEChainBroken,
    CMCELedgerTampered,
    CMCEChallengeUnresolved,
    CMCERoundNotFound,
    CMCERoundClosed,
    INNOV_CODE,
    INNOV_NUMBER,
    VERSION,
    PHASE,
    GOVERNOR,
    LEDGER_PATH,
    REGISTERED_AGENTS,
    DEFAULT_QUORUM,
)

router = APIRouter(
    prefix="/cmce",
    tags=["CMCE — Constitutional Mutation Consensus Engine"],
)

_engine = ConstitutionalMutationConsensusEngine(ledger_path=LEDGER_PATH)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class OpenRoundRequest(BaseModel):
    mutation_id: str = Field(..., description="UUID of the mutation being evaluated")
    intent_declaration_id: str = Field(..., description="CMIM intent declaration UUID")
    scope_paths: list[str] = Field(..., min_items=1)
    proposer: str = Field(..., description="Agent or HUMAN-0 proposing the mutation")


class CastVoteRequest(BaseModel):
    agent: str = Field(..., description="Registered agent casting the vote")
    vote: VoteType = Field(..., description="APPROVE | REJECT | ABSTAIN | CHALLENGE")
    rationale: str = Field(..., min_length=1)


class Human0ActionRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ResolveChallengeRequest(BaseModel):
    challenging_agent: str
    resolution: str = Field(..., description="APPROVE or REJECT")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/round/open", summary="Open a new consensus round for a mutation")
async def open_round(req: OpenRoundRequest) -> dict[str, Any]:
    try:
        r = _engine.open_round(
            mutation_id=req.mutation_id,
            intent_declaration_id=req.intent_declaration_id,
            scope_paths=req.scope_paths,
            proposer=req.proposer,
        )
        return {
            "status": "opened",
            "round_id": r.round_id,
            "mutation_id": r.mutation_id,
            "quorum_required": r.quorum_required,
            "registered_agents": sorted(REGISTERED_AGENTS),
            "governor": GOVERNOR,
            "innov": INNOV_NUMBER,
        }
    except CMCEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/round/{round_id}/vote",
    summary="Cast an agent vote on an open consensus round",
)
async def cast_vote(round_id: str, req: CastVoteRequest) -> dict[str, Any]:
    try:
        vote = _engine.cast_vote(
            round_id=round_id,
            agent=req.agent,
            vote=req.vote,
            rationale=req.rationale,
        )
        r = _engine.get_round(round_id)
        votes_received = list(r.votes.keys())
        votes_remaining = sorted(REGISTERED_AGENTS - set(votes_received))
        return {
            "status": "vote_cast",
            "vote_id": vote.vote_id,
            "round_id": round_id,
            "agent": vote.agent,
            "vote": vote.vote.value,
            "votes_received": votes_received,
            "votes_remaining": votes_remaining,
            "ready_to_close": len(votes_remaining) == 0,
            "governor": GOVERNOR,
        }
    except CMCERoundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CMCERoundClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMCEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/round/{round_id}/human0/veto",
    summary="HUMAN-0 exercises irrevocable constitutional veto",
)
async def human0_veto(round_id: str, req: Human0ActionRequest) -> dict[str, Any]:
    try:
        r = _engine.human0_veto(round_id=round_id, reason=req.reason)
        return {
            "status": "round_closed",
            "round_id": r.round_id,
            "outcome": r.outcome.value,
            "outcome_reason": r.outcome_reason,
            "human0_action": r.human0_action,
            "governor": GOVERNOR,
            "innov": INNOV_NUMBER,
        }
    except CMCERoundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CMCERoundClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMCEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/round/{round_id}/human0/override",
    summary="HUMAN-0 exercises irrevocable constitutional override",
)
async def human0_override(round_id: str, req: Human0ActionRequest) -> dict[str, Any]:
    try:
        r = _engine.human0_override(round_id=round_id, reason=req.reason)
        return {
            "status": "round_closed",
            "round_id": r.round_id,
            "outcome": r.outcome.value,
            "outcome_reason": r.outcome_reason,
            "human0_action": r.human0_action,
            "governor": GOVERNOR,
            "innov": INNOV_NUMBER,
        }
    except CMCERoundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CMCERoundClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMCEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/round/{round_id}/close",
    summary="Close a consensus round after all agents have voted",
)
async def close_round(round_id: str) -> dict[str, Any]:
    try:
        r = _engine.close_round(round_id=round_id)
        return {
            "status": "round_closed",
            "round_id": r.round_id,
            "mutation_id": r.mutation_id,
            "outcome": r.outcome.value,
            "outcome_reason": r.outcome_reason,
            "may_advance_to_cel": r.outcome in (
                ConsensusOutcome.PASSED, ConsensusOutcome.OVERRIDE
            ),
            "governor": GOVERNOR,
            "innov": INNOV_NUMBER,
        }
    except CMCERoundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CMCERoundClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (CMCEVoteMissing, CMCEChallengeUnresolved) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CMCEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/round/{round_id}/resolve_challenge",
    summary="Withdraw a CHALLENGE vote and replace with APPROVE or REJECT",
)
async def resolve_challenge(
    round_id: str, req: ResolveChallengeRequest
) -> dict[str, Any]:
    try:
        vote = _engine.resolve_challenge(
            round_id=round_id,
            challenging_agent=req.challenging_agent,
            resolution=req.resolution,
        )
        return {
            "status": "challenge_resolved",
            "round_id": round_id,
            "agent": vote.agent,
            "new_vote": vote.vote.value,
            "governor": GOVERNOR,
        }
    except CMCERoundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except CMCERoundClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMCEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/round/{round_id}", summary="Retrieve a consensus round by ID")
async def get_round(round_id: str) -> dict[str, Any]:
    try:
        r = _engine.get_round(round_id)
        return r.to_dict()
    except CMCERoundNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/summary", summary="List all consensus rounds")
async def summary() -> dict[str, Any]:
    return {
        "rounds": _engine.summary(),
        "governor": GOVERNOR,
        "innov": INNOV_NUMBER,
    }


@router.get("/chain/verify", summary="Verify HMAC chain integrity of the consensus ledger")
async def chain_verify() -> dict[str, Any]:
    try:
        result = _engine.verify_chain()
        if not result["valid"]:
            raise HTTPException(
                status_code=500,
                detail=f"CMCE-CHAIN-0: chain broken at index {result.get('broken_at_index')}",
            )
        return result
    except CMCEChainBroken as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/export", summary="Export full CMCE engine state")
async def export_state() -> dict[str, Any]:
    return _engine.export_state()
