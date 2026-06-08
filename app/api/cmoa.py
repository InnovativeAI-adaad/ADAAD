# SPDX-License-Identifier: Apache-2.0
"""FastAPI router for INNOV-113 · CMOA — Constitutional Mutation Outcome Analyst.

Endpoints:
  POST /cmoa/analyse              — run outcome analysis, emit fitness + velocity signals
  GET  /cmoa/history              — recent analysis + recalibration ledger records
  POST /cmoa/recalibrate          — HUMAN-0 manual fitness weight recalibration
  GET  /cmoa/verify-chain         — verify OutcomeLedger HMAC chain
  GET  /cmoa/status               — CMOA system status

Governor: DUSTIN L REID · InnovativeAI LLC · Phase 208
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_mutation_outcome_analyst import (
    ConstitutionalMutationOutcomeAnalyst,
    CMOAHuman0Error,
    CMOACGDRGateError,
    CMOABiasError,
    CMOAViolation,
)

router = APIRouter(prefix="/cmoa", tags=["CMOA"])
_engine = ConstitutionalMutationOutcomeAnalyst()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AnalyseRequest(BaseModel):
    requester: str = Field(default="SYSTEM", description="Agent or user ID requesting analysis")
    inject_records: Optional[List[dict]] = Field(
        default=None,
        description="Test-only: inject CMWE attestation records directly (bypasses ledger read)",
    )


class RecalibrateRequest(BaseModel):
    human_id: str = Field(..., description="HUMAN-0 authority identifier")
    fitness_delta_override: float = Field(
        ...,
        ge=-0.20,
        le=0.20,
        description="Fitness delta override, bounded to [-0.20, +0.20] (CMOA-BIAS-0)",
    )
    rationale: str = Field(default="", description="Governance rationale for recalibration")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/analyse")
def run_analysis(req: AnalyseRequest) -> dict:
    """POST /cmoa/analyse — Run outcome analysis pipeline.

    Reads CMWE attestation records, computes success rates, and emits:
      - fitness_signal: bounded delta for AMPS proposal scoring (CMOA-BIAS-0)
      - velocity_signal: nudge recommendation for CMVG (HALT/THROTTLE/CRUISE/ACCELERATE)

    Blocked when CGDR gate is DRIFTED (CMOA-CGDR-0).
    Requires ≥ 3 outcome records (CMOA-MIN-0).
    """
    try:
        return _engine.analyse(
            requester=req.requester,
            inject_records=req.inject_records,
        )
    except CMOACGDRGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMOAViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        # CMOA-FAILCLOSED-0: return NO_SIGNAL, not 500
        return {"outcome": "NO_SIGNAL", "error": str(exc)}


@router.get("/history")
def get_history(limit: int = 20) -> dict:
    """GET /cmoa/history — Recent analysis and recalibration ledger records."""
    records = _engine.get_history(limit=limit)
    return {"records": records, "count": len(records)}


@router.post("/recalibrate")
def recalibrate(req: RecalibrateRequest) -> dict:
    """POST /cmoa/recalibrate — HUMAN-0 manual fitness weight recalibration.

    Enforces CMOA-HUMAN0-0 (authority) and CMOA-BIAS-0 (delta bounds).
    """
    try:
        return _engine.recalibrate(
            human_id=req.human_id,
            fitness_delta_override=req.fitness_delta_override,
            rationale=req.rationale,
        )
    except CMOAHuman0Error as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except CMOABiasError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/verify-chain")
def verify_chain() -> dict:
    """GET /cmoa/verify-chain — Verify OutcomeLedger HMAC chain (CMOA-CHAIN-0)."""
    return _engine.verify_chain()


@router.get("/status")
def get_status() -> dict:
    """GET /cmoa/status — CMOA system status, gate state, invariant list."""
    return _engine.get_status()
