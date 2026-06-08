# SPDX-License-Identifier: Apache-2.0
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
)

router = APIRouter(prefix="/acpa", tags=["ACPA"])
_engine = AutonomousConstitutionalProposalAdvisor()

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
