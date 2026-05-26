"""
INNOV-101 CMIM API Router - Constitutional Mutation Intent Model
Phase 196 - v10.7.0 - InnovativeAI LLC - DUSTIN L REID (HUMAN-0)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
import time, uuid

from dorkllm.constitutional_mutation_intent_model import (
    ConstitutionalMutationIntentModel, MutationIntentDeclaration,
    CMIMError, CMIMRollbackTriggered, CMIMChainBroken, LEDGER_PATH
)

router = APIRouter(prefix="/cmim", tags=["cmim"])
_engine = ConstitutionalMutationIntentModel()

class IntentDeclareRequest(BaseModel):
    mutation_id: str
    goal_statement: str
    expected_invariants_touched: List[str]
    blast_radius_tier: int
    ratification_scope: str
    author_agent: str
    target_cel_stages: List[int]
    governance_objectives: List[str]
    human0_countersig: Optional[str] = None

class IntentVerifyRequest(BaseModel):
    declaration_id: str
    actual_invariants_triggered: List[str]
    actual_blast_tier: int

@router.post("/declare")
def declare_intent(req: IntentDeclareRequest) -> Dict[str, Any]:
    """Gate 1: Accept and validate a mutation intent declaration before CEL entry."""
    try:
        decl = MutationIntentDeclaration(
            mutation_id=req.mutation_id,
            goal_statement=req.goal_statement,
            expected_invariants_touched=req.expected_invariants_touched,
            blast_radius_tier=req.blast_radius_tier,
            ratification_scope=req.ratification_scope,
            author_agent=req.author_agent,
            target_cel_stages=req.target_cel_stages,
            governance_objectives=req.governance_objectives,
        )
        declaration_id = _engine.declare_intent(decl, req.human0_countersig)
        return {
            "status": "DECLARED",
            "declaration_id": declaration_id,
            "mutation_id": req.mutation_id,
            "fingerprint": decl.fingerprint(),
            "invariant": "CMIM-INTENT-0",
            "phase": 196,
            "version": "10.7.0",
        }
    except CMIMError as e:
        raise HTTPException(status_code=422, detail=str(e))

@router.post("/verify")
def verify_intent(req: IntentVerifyRequest) -> Dict[str, Any]:
    """Gate 2: Post-CEL intent-behavior verification. Triggers rollback on divergence."""
    try:
        report = _engine.verify_intent(
            req.declaration_id, req.actual_invariants_triggered, req.actual_blast_tier)
        return {
            "status": "PASS",
            "verdict": report.verdict,
            "declaration_id": report.declaration_id,
            "mutation_id": report.mutation_id,
            "intent_behavior_divergence": report.intent_behavior_divergence,
            "rollback_required": report.rollback_required,
        }
    except CMIMRollbackTriggered as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CMIMError as e:
        raise HTTPException(status_code=422, detail=str(e))

@router.get("/report/{declaration_id}")
def get_report(declaration_id: str) -> Dict[str, Any]:
    """Retrieve a stored intent declaration."""
    d = _engine.get_declaration(declaration_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"Declaration {declaration_id} not found.")
    return d

@router.get("/summary")
def get_summary() -> Dict[str, Any]:
    """Ledger summary: entry counts and chain tip."""
    return _engine.get_ledger_summary()

@router.get("/chain/verify")
def verify_chain() -> Dict[str, Any]:
    """Verify HMAC chain integrity of the full intent ledger."""
    try:
        return _engine.verify_chain_integrity()
    except CMIMChainBroken as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export")
def export_ledger() -> List[Dict[str, Any]]:
    """Export full intent ledger for deterministic replay."""
    return _engine.export_ledger()
