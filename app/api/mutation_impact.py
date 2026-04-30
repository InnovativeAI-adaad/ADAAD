# SPDX-License-Identifier: Apache-2.0
"""Phase 162 — INNOV-68 · MIA API routes.

Routes
------
GET  /api/governance/mia/status        — MIA engine status + tier/recommendation counts
GET  /api/governance/mia/history       — Recent impact assessments (last 50)
POST /api/governance/mia/analyze       — Submit a mutation payload for impact analysis
GET  /api/governance/mia/chain/verify  — Verify HMAC chain integrity of MIA ledger
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.mutation_impact_analyzer import (
    MIAChainError,
    MutationImpactAnalyzer,
    MutationPayload,
    get_analyzer,
)

router = APIRouter(prefix="/api/governance/mia", tags=["mia"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    mutation_id: str = Field(..., description="Stable caller-supplied mutation identifier.")
    target_module: str = Field(..., description="Dotted module path being mutated.")
    diff_summary: str = Field(..., max_length=4096, description="Plain-text summary of the diff.")
    rationale: str = Field(..., description="Constitutional justification for the mutation.")
    proposed_by: str = Field(default="HUMAN-0", description="Agent or human proposing this mutation.")
    csi_band: Optional[str] = Field(default=None, description="Current CSI band (EXCELLENT/HEALTHY/CAUTION/CRITICAL).")
    cfe_risk_tier: Optional[str] = Field(default=None, description="Current CFE risk tier (LOW/MEDIUM/HIGH_RISK/CRITICAL).")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status")
async def mia_status() -> Dict[str, Any]:
    """Return MIA engine status, invariant list, and assessment summary."""
    try:
        return get_analyzer().status()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/history")
async def mia_history(limit: int = 50) -> Dict[str, Any]:
    """Return recent impact assessment records."""
    try:
        records = get_analyzer().get_history(limit=min(limit, 200))
        return {"records": records, "count": len(records)}
    except MIAChainError as exc:
        raise HTTPException(status_code=500, detail=f"chain_broken: {exc}") from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze")
async def mia_analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    """Submit a mutation payload and receive a structured impact assessment."""
    try:
        payload = MutationPayload(
            mutation_id=req.mutation_id,
            target_module=req.target_module,
            diff_summary=req.diff_summary,
            rationale=req.rationale,
            proposed_by=req.proposed_by,
        )
        assessment = get_analyzer().analyze(
            payload,
            csi_band=req.csi_band,
            cfe_risk_tier=req.cfe_risk_tier,
        )
        return assessment.to_dict()
    except MIAChainError as exc:
        raise HTTPException(status_code=500, detail=f"chain_broken: {exc}") from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chain/verify")
async def mia_chain_verify() -> Dict[str, Any]:
    """Verify HMAC chain integrity of the MIA impact ledger."""
    try:
        result = get_analyzer().verify_chain()
        if result["status"] != "ok":
            raise HTTPException(status_code=500, detail=result.get("error", "chain_broken"))
        return result
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc
