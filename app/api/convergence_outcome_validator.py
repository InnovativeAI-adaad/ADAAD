# SPDX-License-Identifier: Apache-2.0
"""
INNOV-89 · COV API — Convergence Outcome Validator endpoints
Phase 184 · v9.117.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict, List

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    _FASTAPI = True
except ImportError:
    _FASTAPI = False
    APIRouter = object  # type: ignore
    HTTPException = Exception  # type: ignore

    class BaseModel:  # type: ignore
        pass


from dorkllm.convergence_outcome_validator import (
    ConvergenceOutcomeValidator,
    DEFAULT_VALIDATE_N,
)

router = APIRouter(prefix="/cov", tags=["INNOV-89-COV"]) if _FASTAPI else None

_cov = ConvergenceOutcomeValidator()


class ValidateRequest(BaseModel):
    limit: int = DEFAULT_VALIDATE_N


class ValidateResponse(BaseModel):
    validated: int
    outcomes: List[str]
    records: List[Dict[str, Any]]


if _FASTAPI:

    @router.post("/validate", response_model=ValidateResponse)
    def validate_outcomes(req: ValidateRequest) -> ValidateResponse:
        """Validate up to `limit` unvalidated CPE telemetry entries."""
        limit = max(1, min(req.limit, 20))
        records = _cov.validate(limit=limit)
        return ValidateResponse(
            validated=len(records),
            outcomes=[r.outcome for r in records],
            records=[
                {
                    "validation_id": r.validation_id,
                    "execution_id": r.execution_id,
                    "plan_id": r.plan_id,
                    "outcome": r.outcome,
                    "cri_before": r.cri_before,
                    "cri_after": r.cri_after,
                    "cri_delta": r.cri_delta,
                    "human0_advisory": r.human0_advisory,
                    "cal_signal_written": r.cal_signal_written,
                }
                for r in records
            ],
        )

    @router.get("/snapshot")
    def cov_snapshot() -> Dict[str, Any]:
        """Return current COV runtime snapshot."""
        return _cov.get_snapshot()

    @router.get("/history")
    def cov_history(limit: int = 20) -> List[Dict[str, Any]]:
        """Return last N validation records from ledger."""
        return _cov.get_validation_history(limit=min(limit, 100))

    @router.get("/summary")
    def cov_summary() -> Dict[str, Any]:
        """Return aggregate outcome summary."""
        return _cov.get_outcome_summary()

    @router.get("/chain-integrity")
    def cov_chain_integrity() -> Dict[str, Any]:
        """Verify HMAC chain integrity — COV-CHAIN-0."""
        result = _cov.verify_chain_integrity()
        if not result["chain_valid"]:
            raise HTTPException(status_code=500, detail="COV-CHAIN-0 VIOLATION")
        return result
