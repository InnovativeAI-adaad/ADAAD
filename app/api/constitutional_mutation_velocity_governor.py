# SPDX-License-Identifier: Apache-2.0
"""FastAPI router for INNOV-110 · CMVG — Constitutional Mutation Velocity Governor.

Endpoints:
  POST /cmvg/decide              — compute a velocity decision from signals
  GET  /cmvg/decisions           — list all velocity decisions
  GET  /cmvg/decisions/{id}      — retrieve single decision
  POST /cmvg/emergency-stop      — HUMAN-0 emergency stop
  POST /cmvg/clear-emergency-stop — HUMAN-0 clear emergency stop
  POST /cmvg/set-policy-rate     — HUMAN-0 policy rate override
  POST /cmvg/clear-policy-rate   — HUMAN-0 clear policy rate override
  GET  /cmvg/verify-chain        — verify VelocityLedger HMAC chain
  GET  /cmvg/status              — CMVG system status

Governor: DUSTIN L REID · InnovativeAI LLC · Phase 205
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_velocity_governor import (
    CMVGAuthError,
    CMVGCeilError,
    CMVGError,
    ConstitutionalMutationVelocityGovernor,
    VelocitySignals,
)

router = APIRouter(prefix="/cmvg", tags=["cmvg"])

_governor = ConstitutionalMutationVelocityGovernor()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SignalsRequest(BaseModel):
    cgdr_status: str = Field("UNKNOWN", description="CGDR status: PASSING|DRIFTED|UNKNOWN")
    invariant_density: float = Field(0.5, ge=0.0, le=1.0)
    cel_gate_pass_rate: float = Field(0.5, ge=0.0, le=1.0)
    innovation_backlog: int = Field(0, ge=0)
    last_phase_duration_s: float = Field(3600.0, gt=0)


class HumanActionRequest(BaseModel):
    human_id: str = Field(..., min_length=1, description="HUMAN-0 authenticated identity")


class PolicyRateRequest(BaseModel):
    human_id: str = Field(..., min_length=1)
    rate: float = Field(..., ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/decide")
def decide(req: SignalsRequest):
    """Compute and ledger a VelocityDecision from supplied signals."""
    signals = VelocitySignals(
        cgdr_status=req.cgdr_status,
        invariant_density=req.invariant_density,
        cel_gate_pass_rate=req.cel_gate_pass_rate,
        innovation_backlog=req.innovation_backlog,
        last_phase_duration_s=req.last_phase_duration_s,
    )
    try:
        decision = _governor.decide(signals)
        return {"outcome": decision.outcome, "decision": decision.to_dict()}
    except CMVGError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/decisions")
def list_decisions():
    """Return all VelocityDecision records from the ledger."""
    return {"decisions": _governor.all_decisions()}


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: str):
    """Return a single VelocityDecision by ID."""
    for d in _governor.all_decisions():
        if d.get("decision_id") == decision_id:
            return d
    raise HTTPException(status_code=404, detail=f"decision {decision_id!r} not found")


@router.post("/emergency-stop")
def emergency_stop(req: HumanActionRequest):
    """Engage emergency stop — HUMAN-0 required. CMVG-HUMAN0-0."""
    try:
        _governor.emergency_stop(req.human_id)
        return {"outcome": "EMERGENCY_STOP_ENGAGED", "human_id": req.human_id}
    except CMVGAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/clear-emergency-stop")
def clear_emergency_stop(req: HumanActionRequest):
    """Clear emergency stop — HUMAN-0 required. CMVG-HUMAN0-0."""
    try:
        _governor.clear_emergency_stop(req.human_id)
        return {"outcome": "EMERGENCY_STOP_CLEARED", "human_id": req.human_id}
    except CMVGAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/set-policy-rate")
def set_policy_rate(req: PolicyRateRequest):
    """Set HUMAN-0 policy override rate. CMVG-HUMAN0-0."""
    try:
        _governor.set_policy_rate(req.rate, req.human_id)
        return {"outcome": "POLICY_RATE_SET", "rate": req.rate, "human_id": req.human_id}
    except (CMVGAuthError, CMVGCeilError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/clear-policy-rate")
def clear_policy_rate(req: HumanActionRequest):
    """Clear HUMAN-0 policy override. CMVG-HUMAN0-0."""
    try:
        _governor.clear_policy_rate(req.human_id)
        return {"outcome": "POLICY_RATE_CLEARED", "human_id": req.human_id}
    except CMVGAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/verify-chain")
def verify_chain():
    """Verify VelocityLedger HMAC chain integrity. CMVG-CHAIN-0."""
    try:
        result = _governor.verify_chain()
        return result
    except CMVGError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status")
def status():
    """Return CMVG system status."""
    return _governor.status()
