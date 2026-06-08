# SPDX-License-Identifier: Apache-2.0
"""FastAPI router for INNOV-108 · CGDR — Convergence Governance Drift Reporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.convergence_governance_drift_reporter import (
    ConvergenceGovernanceDriftReporter,
    CGDRDriftGateError,
    CGDRHuman0Error,
    CGDRViolation,
)

router = APIRouter(prefix="/cgdr", tags=["CGDR"])
_engine = ConvergenceGovernanceDriftReporter()


# ── request / response models ─────────────────────────────────────────────────
class AssessRequest(BaseModel):
    epoch_id: str
    snapshot: dict[str, Any]


class ClearDriftRequest(BaseModel):
    human_id: str
    note: str = ""


# ── endpoints ─────────────────────────────────────────────────────────────────
@router.post("/assess")
def assess(req: AssessRequest) -> dict[str, Any]:
    """Run a CCA assessment against the provided state snapshot."""
    try:
        report = _engine.assess(req.epoch_id, req.snapshot)
        return report.to_dict()
    except CGDRViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/status")
def status() -> dict[str, Any]:
    """Return current CGDR drift status and latest report summary."""
    return _engine.summary()


@router.post("/clear-drift")
def clear_drift(req: ClearDriftRequest) -> dict[str, Any]:
    """HUMAN-0: acknowledge and clear active drift flag."""
    try:
        _engine.clear_drift(req.human_id, req.note)
        return {"cleared": True, "human_id": req.human_id}
    except CGDRHuman0Error as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/verify-chain")
def verify_chain() -> dict[str, Any]:
    """Verify HMAC ledger chain integrity."""
    return {"chain_valid": _engine.verify_chain()}


@router.get("/assert-no-drift")
def assert_no_drift(phase_label: str = "") -> dict[str, Any]:
    """Gate check: returns 200 if system is PASSING, 409 if DRIFTED."""
    try:
        _engine.assert_no_drift(phase_label)
        return {"status": "PASSING", "gate": "OPEN"}
    except CGDRDriftGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
