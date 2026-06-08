# SPDX-License-Identifier: Apache-2.0
"""
INNOV-107 · CCSW — Convergence Criteria State Wire — FastAPI Router
Phase 202 · v10.13.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dorkllm.convergence_criteria_state_wire import ConvergenceCriteriaStateWire

router = APIRouter(prefix="/ccsw", tags=["CCSW"])


# ── Request / Response models ──────────────────────────────────────────────────

class WireRequest(BaseModel):
    wire_id: str | None = None


class WireResponse(BaseModel):
    wire_id: str
    wire_status: str
    convergence_score: float
    v10_ready: bool
    criteria_passed: int
    criteria_total: int
    gir_cri: float
    gir_readiness_score_alias: float
    human0_advisory_emitted: bool
    hmac_digest: str
    agent_fields_added: list[str]
    bootstrap_summary: list[dict]


class PreviewResponse(BaseModel):
    convergence_score: float
    v10_ready: bool
    criteria_passed: int
    criteria_total: int
    cca_threshold: float
    criteria_results: list[dict]


class StatusResponse(BaseModel):
    module: str
    innov: str
    version: str
    governor: str
    total_wire_calls: int
    last_wire_id: str | None
    last_convergence_score: float
    last_updated: str
    chain_head_digest: str
    ccsw_min_convergence_score: float


class ChainVerifyResponse(BaseModel):
    valid: bool
    records_checked: int
    error: str | None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/wire", response_model=WireResponse, summary="Execute CCSW wiring sequence")
def wire(req: WireRequest = WireRequest()) -> WireResponse:
    """
    Execute the full Convergence Criteria State Wire sequence:
      1. Bootstrap GIR subsystem ledgers
      2. Run GIR assessment → gir_snapshot.json
      3. Inject readiness_score alias → fixes C1
      4. Patch agent state (hard_class_invariants, cel_loop_status, schema_version)
      5. Verify CCA convergence score ≥ 0.875

    CCSW-VERIFY-0: returns HTTP 422 if post-wire CCA score < 0.875.
    CCSW-AUDIT-0: every call writes a signed HMAC-chained wire ledger entry.
    """
    try:
        ccsw = ConvergenceCriteriaStateWire()
        result = ccsw.wire(wire_id=req.wire_id)
        return WireResponse(
            wire_id=result.wire_id,
            wire_status=result.wire_status,
            convergence_score=result.convergence_verification["convergence_score"],
            v10_ready=result.convergence_verification["v10_ready"],
            criteria_passed=result.convergence_verification["criteria_passed"],
            criteria_total=result.convergence_verification["criteria_total"],
            gir_cri=result.gir_cri,
            gir_readiness_score_alias=result.gir_readiness_score_alias,
            human0_advisory_emitted=result.human0_advisory_emitted,
            hmac_digest=result.hmac_digest,
            agent_fields_added=result.agent_patch_result.get("fields_added", []),
            bootstrap_summary=[
                {
                    "subsystem": b["subsystem"],
                    "entries_written": b["genesis_entries_written"],
                    "idempotent_skip": b["skipped_idempotent"],
                    "total_entries": b["final_entry_count"],
                }
                for b in result.bootstrap_results
            ],
        )
    except RuntimeError as exc:
        # CCSW-VERIFY-0 failure → unprocessable
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCSW wire error: {exc}")


@router.get("/preview", response_model=PreviewResponse, summary="Preview CCA convergence score (no ledger write)")
def preview() -> PreviewResponse:
    """
    Return the current CCA convergence score and criteria results without
    writing to any ledger. Safe for dashboards and health checks.
    """
    try:
        ccsw = ConvergenceCriteriaStateWire()
        result = ccsw.preview()
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return PreviewResponse(
            convergence_score=result.get("convergence_score", 0.0),
            v10_ready=result.get("v10_ready", False),
            criteria_passed=result.get("criteria_passed", 0),
            criteria_total=result.get("criteria_total", 8),
            cca_threshold=result.get("cca_threshold", 0.875),
            criteria_results=result.get("criteria_results", []),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCSW preview error: {exc}")


@router.get("/status", response_model=StatusResponse, summary="CCSW operational status")
def status() -> StatusResponse:
    """Return current CCSW operational state and configuration."""
    try:
        ccsw = ConvergenceCriteriaStateWire()
        s = ccsw.get_status()
        return StatusResponse(**s)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CCSW status error: {exc}")


@router.get("/verify-chain", response_model=ChainVerifyResponse, summary="Verify HMAC chain integrity")
def verify_chain() -> ChainVerifyResponse:
    """
    Verify HMAC-SHA-256 chain integrity across all wire ledger records.
    CCSW-CHAIN-0 enforcement endpoint.
    """
    try:
        ccsw = ConvergenceCriteriaStateWire()
        valid, count, error = ccsw.verify_chain()
        return ChainVerifyResponse(valid=valid, records_checked=count, error=error)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chain verify error: {exc}")
