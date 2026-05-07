# SPDX-License-Identifier: Apache-2.0
"""Phase 163 — INNOV-69 · MCE API routes.

Routes
------
GET  /api/governance/mce/status        — MCE engine status + weight summary
GET  /api/governance/mce/weights       — Current calibrated MIA weights
GET  /api/governance/mce/history       — Recent calibration records (last 50)
POST /api/governance/mce/outcome       — Record a mutation outcome + calibrate
GET  /api/governance/mce/chain/verify  — Verify HMAC chain integrity
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from dorkllm.mutation_calibration_engine import (
    MCEChainError, MCESourceError, MCEWeightError, MCELookupError,
    MutationCalibrationEngine, MutationOutcome, OutcomeClass, get_engine,
)

router = APIRouter(prefix="/api/governance/mce", tags=["mce"])


class OutcomeRequest(BaseModel):
    impact_id:            str   = Field(..., description="MIA impact_id being calibrated.")
    mutation_id:          str   = Field(..., description="Stable mutation identifier.")
    actual_result:        str   = Field(..., description="APPROVED/REVERTED/BLOCKED_POST_GATE/NEUTRAL")
    execution_phase:      int   = Field(..., description="Phase number in which mutation executed.")
    csi_delta:            float = Field(default=0.0, description="CSI score change post-execution.")
    invariant_violations: int   = Field(default=0, description="Count of invariant violations triggered.")
    submitted_by:         str   = Field(default="cel_loop", description="Submitting agent or human.")
    source:               str   = Field(default="cel_loop", description="Caller source key.")


@router.get("/status")
async def mce_status() -> Dict[str, Any]:
    try:
        return get_engine().status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/weights")
async def mce_weights() -> Dict[str, Any]:
    try:
        weights = get_engine().current_weights()
        return {"weights": weights, "component": "mce", "innovation": "INNOV-69"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/history")
async def mce_history(limit: int = 50) -> Dict[str, Any]:
    try:
        records = get_engine().history(limit=limit)
        return {"records": records, "count": len(records), "component": "mce"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/outcome")
async def mce_record_outcome(req: OutcomeRequest) -> Dict[str, Any]:
    try:
        outcome_class = OutcomeClass(req.actual_result)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid actual_result: {req.actual_result}")
    try:
        outcome = MutationOutcome(
            impact_id=req.impact_id,
            mutation_id=req.mutation_id,
            actual_result=outcome_class,
            execution_phase=req.execution_phase,
            csi_delta=req.csi_delta,
            invariant_violations=req.invariant_violations,
            submitted_by=req.submitted_by,
        )
        record = get_engine().record_outcome(outcome, source=req.source)
        return {
            "calibration_id":    record.calibration_id,
            "prediction_tier":   record.prediction_tier,
            "actual_class":      record.actual_class,
            "prediction_error":  round(record.prediction_error, 6),
            "new_weights":       record.cumulative_weights,
            "ledger_seq":        record.ledger_seq,
            "component":         "mce",
        }
    except MCESourceError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (MCEChainError, MCEWeightError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/chain/verify")
async def mce_chain_verify() -> Dict[str, Any]:
    try:
        return get_engine().verify_chain()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
