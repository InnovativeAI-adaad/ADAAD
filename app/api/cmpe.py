# SPDX-License-Identifier: Apache-2.0
"""REST router — INNOV-114 · CMPE — Constitutional Mutation Policy Engine.

Endpoints:
  POST /api/cmpe/evaluate        — evaluate a strategy against current policy
  POST /api/cmpe/amend           — add / replace a policy rule (HUMAN-0 for TIER0)
  POST /api/cmpe/reset-budget    — reset blast-radius budget (HUMAN-0)
  POST /api/cmpe/freeze          — enable/disable EMERGENCY_FREEZE (HUMAN-0)
  GET  /api/cmpe/rules           — list all active policy rules
  GET  /api/cmpe/verify          — verify PolicyLedger chain integrity
  GET  /api/cmpe/health          — liveness + engine state
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_policy_engine import (
    ConstitutionalMutationPolicyEngine,
    CMPEAuthError,
    CMPEChainError,
    CMPEError,
    CMPEImmutError,
    CMPERuleError,
    PolicyEvalContext,
    PolicyRule,
    INNOV_CODE,
    INNOV_NUMBER,
    VERSION,
    PHASE,
)

router = APIRouter(prefix="/api/cmpe", tags=["CMPE"])
_engine = ConstitutionalMutationPolicyEngine()


class EvaluateRequest(BaseModel):
    strategy_id: str
    blast_tier: int = Field(..., ge=0, le=2)
    invariant_health_ratio: float = Field(..., ge=0.0, le=1.0)
    velocity_state: str = Field(default="CRUISE")
    v10_criteria_met: bool = False
    scope: list[str] = Field(default_factory=list)
    human0_identity: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class AmendRequest(BaseModel):
    rule_id: str
    description: str
    blast_tier_max: int = Field(..., ge=0, le=2)
    min_health_ratio: float = Field(..., ge=0.0, le=1.0)
    requires_human0: bool = False
    active: bool = True
    human0_identity: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ResetBudgetRequest(BaseModel):
    human0_identity: str


class FreezeRequest(BaseModel):
    human0_identity: str
    freeze: bool


@router.post("/evaluate")
def evaluate(req: EvaluateRequest):
    ctx = PolicyEvalContext(
        strategy_id=req.strategy_id,
        blast_tier=req.blast_tier,
        invariant_health_ratio=req.invariant_health_ratio,
        velocity_state=req.velocity_state,
        v10_criteria_met=req.v10_criteria_met,
        scope=req.scope,
        metadata=req.metadata,
    )
    try:
        result = _engine.evaluate(ctx, human0_identity=req.human0_identity)
        return {
            "verdict": result.verdict,
            "strategy_id": result.strategy_id,
            "denial_reasons": result.denial_reasons,
            "applied_rules": result.applied_rules,
            "blast_budget_remaining": result.blast_budget_remaining,
            "engine_mode": result.engine_mode,
            "innov_code": INNOV_CODE,
        }
    except CMPEError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/amend")
def amend(req: AmendRequest):
    rule = PolicyRule(
        rule_id=req.rule_id,
        description=req.description,
        blast_tier_max=req.blast_tier_max,
        min_health_ratio=req.min_health_ratio,
        requires_human0=req.requires_human0,
        active=req.active,
        metadata=req.metadata,
    )
    try:
        r = _engine.amend(rule, human0_identity=req.human0_identity)
        return {"status": "AMENDED", "rule_id": r.rule_id, "innov_code": INNOV_CODE}
    except CMPEAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (CMPERuleError, CMPEImmutError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/reset-budget")
def reset_budget(req: ResetBudgetRequest):
    try:
        remaining = _engine.reset_budget(req.human0_identity)
        return {"status": "RESET", "blast_budget_remaining": remaining, "innov_code": INNOV_CODE}
    except CMPEAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/freeze")
def freeze(req: FreezeRequest):
    try:
        _engine.set_emergency_freeze(req.human0_identity, req.freeze)
        return {"status": "OK", "engine_mode": _engine.mode, "innov_code": INNOV_CODE}
    except CMPEAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/rules")
def list_rules():
    return {
        "rules": [
            {"rule_id": r.rule_id, "description": r.description,
             "blast_tier_max": r.blast_tier_max, "min_health_ratio": r.min_health_ratio,
             "requires_human0": r.requires_human0, "active": r.active}
            for r in _engine.rules.values()
        ],
        "total": len(_engine.rules),
        "innov_code": INNOV_CODE,
    }


@router.get("/verify")
def verify():
    try:
        ok = _engine.verify_ledger()
        return {"chain_valid": ok, "innov_code": INNOV_CODE}
    except CMPEChainError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
def health():
    return {
        "status": "operational",
        "innov_code": INNOV_CODE,
        "innov_number": INNOV_NUMBER,
        "version": VERSION,
        "phase": PHASE,
        "engine_mode": _engine.mode,
        "blast_budget_remaining": _engine.blast_budget_remaining,
        "active_rules": len(_engine.rules),
        "governor": "DUSTIN L REID",
    }
