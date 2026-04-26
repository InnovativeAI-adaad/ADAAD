# SPDX-License-Identifier: Apache-2.0
"""Phase 161 — INNOV-67 · CFE API routes.

Routes
------
GET  /api/governance/cfe/status        — engine health + chain length
GET  /api/governance/cfe/chain         — full forecast ledger chain
POST /api/governance/cfe/forecast      — submit a pressure window for forecast
GET  /api/governance/cfe/chain/verify  — replay chain integrity check
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dorkllm.constitutional_forecast import (
    CFEChainError,
    CFEHumanGateError,
    CFEWindowError,
    ConstitutionalForecastEngine,
)

router = APIRouter(prefix="/api/governance/cfe", tags=["cfe"])

_ENGINE: ConstitutionalForecastEngine = ConstitutionalForecastEngine()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ForecastRequest(BaseModel):
    pressure_window: List[float] = Field(
        ...,
        description="Ordered constitutional pressure readings [0.0, 1.0], oldest first.",
        min_items=3,
    )
    horizon_epochs: int = Field(default=5, ge=1, le=50)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ForecastResponse(BaseModel):
    forecast_id: str
    window_size: int
    trend_slope: float
    forecast_pressure: float
    risk_tier: str
    horizon_epochs: int
    prev_digest: str
    digest: str
    timestamp_iso: str
    metadata: Dict[str, Any]


class StatusResponse(BaseModel):
    component: str
    status: str
    chain_length: int
    chain_tip: str


class VerifyResponse(BaseModel):
    valid: bool
    chain_length: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    chain = _ENGINE.chain()
    tip = chain[-1]["digest"] if chain else "0" * 64
    return StatusResponse(
        component="cfe",
        status="operational",
        chain_length=len(chain),
        chain_tip=tip,
    )


@router.get("/chain", response_model=List[Dict[str, Any]])
async def get_chain() -> List[Dict[str, Any]]:
    return _ENGINE.chain()


@router.post("/forecast", response_model=ForecastResponse)
async def post_forecast(body: ForecastRequest) -> ForecastResponse:
    # Rebuild engine if horizon_epochs differs from request
    engine = (
        _ENGINE
        if body.horizon_epochs == _ENGINE._horizon_epochs
        else ConstitutionalForecastEngine(horizon_epochs=body.horizon_epochs)
    )
    try:
        entry = engine.forecast(body.pressure_window, metadata=body.metadata)
    except CFEWindowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CFEChainError, CFEHumanGateError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ForecastResponse(**entry.to_dict())


@router.get("/chain/verify", response_model=VerifyResponse)
async def get_chain_verify() -> VerifyResponse:
    chain = _ENGINE.chain()
    try:
        _ENGINE.verify_chain()
        valid = True
    except CFEChainError:
        valid = False
    return VerifyResponse(valid=valid, chain_length=len(chain))
