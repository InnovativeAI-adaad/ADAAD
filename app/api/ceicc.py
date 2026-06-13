# SPDX-License-Identifier: Apache-2.0
# INNOV-125 · CEICC REST Router — Phase 220 · v10.31.0
# Governor: DUSTIN L REID

"""
FastAPI router for CEICC — Cross-Engine Invariant Coherence Checker.
Endpoints:
  POST /ceicc/check                — Execute full corpus coherence check
  GET  /ceicc/report/latest        — Return latest CoherenceReport ledger entry
  GET  /ceicc/chain/verify         — Verify HMAC chain integrity
  GET  /ceicc/corpus/stats         — Return live invariant corpus statistics
  GET  /ceicc/status               — Module status and invariant manifest
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dorkllm.cross_engine_invariant_coherence_checker import (
    CrossEngineInvariantCoherenceChecker,
    CEICCError,
    CEICCCorpusError,
    CEICCHMACError,
    CEICCScopeError,
    GOVERNOR,
    INNOV,
    VERSION,
    run_check,
    verify_chain,
    get_latest_report,
    corpus_stats,
    status,
)

router = APIRouter(prefix="/ceicc", tags=["CEICC"])
_engine = CrossEngineInvariantCoherenceChecker()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CheckRequest(BaseModel):
    engine_manifest: Optional[List[str]] = Field(
        None,
        description=(
            "Explicit list of engine module names to include (stems only, no .py). "
            "If omitted, all dorkllm/*.py modules are scanned — CEICC-SCOPE-0."
        ),
    )


class CEICCResponse(BaseModel):
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    innov: str = INNOV
    version: str = VERSION
    governor: str = GOVERNOR


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/check",
    response_model=CEICCResponse,
    summary="Execute full corpus coherence check",
)
async def coherence_check(req: CheckRequest) -> CEICCResponse:
    """
    Run CEICC across all registered engine modules (or a provided manifest).

    Executes four contradiction detectors:
      CLASS-A Semantic Conflict, CLASS-B Scope Overlap,
      CLASS-C Authority Collision, CLASS-D Duplicate Assertion.

    Returns a sealed CoherenceReport with coherence score (0.0–1.0) and
    all findings. HUMAN-0 advisory is written to disk for CLASS-A / CLASS-C findings.
    Enforces all 10 CEICC hard-class invariants (fail-closed).
    """
    try:
        report = _engine.run_check(engine_manifest=req.engine_manifest)
        return CEICCResponse(
            ok=True,
            data={
                "report_id": report.report_id,
                "check_id": report.check_id,
                "engine_count": report.engine_count,
                "invariant_count": report.invariant_count,
                "coherence_score": report.coherence_score,
                "status": report.status.value,
                "human0_advisory_required": report.human0_advisory_required,
                "finding_count": len(report.findings),
                "findings": report.findings,
                "missing_registrations": report.missing_registrations,
                "checked_at": report.checked_at,
                "hmac_digest": report.hmac_digest,
                "prev_digest": report.prev_digest,
            },
        )
    except CEICCCorpusError as e:
        raise HTTPException(status_code=422, detail=f"CEICC-CORPUS-0: {e}")
    except CEICCScopeError as e:
        raise HTTPException(status_code=422, detail=f"CEICC-SCOPE-0: {e}")
    except CEICCHMACError as e:
        raise HTTPException(status_code=500, detail=f"CEICC-HMAC-0: {e}")
    except CEICCError as e:
        raise HTTPException(status_code=500, detail=f"CEICC constitutional violation: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CEICC internal error: {e}")


@router.get(
    "/report/latest",
    response_model=CEICCResponse,
    summary="Return latest CoherenceReport ledger entry",
)
async def latest_report() -> CEICCResponse:
    """
    Retrieve the most recent CoherenceReport from the coherence ledger.
    Returns 404 if no report has been generated yet.
    """
    try:
        report = _engine.get_latest_report()
        if report is None:
            raise HTTPException(status_code=404, detail="No coherence reports found — ledger is empty.")
        return CEICCResponse(ok=True, data=report)
    except HTTPException:
        raise
    except CEICCError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/chain/verify",
    response_model=CEICCResponse,
    summary="Verify HMAC chain integrity across coherence ledger",
)
async def chain_verify() -> CEICCResponse:
    """
    Re-read the full coherence ledger and verify HMAC forward-chain integrity.
    CEICC-HMAC-0 + CEICC-REPLAY-0 compliant.
    Raises 500 on any chain break or digest mismatch.
    """
    try:
        result = _engine.verify_chain()
        return CEICCResponse(ok=True, data=result)
    except CEICCHMACError as e:
        raise HTTPException(status_code=500, detail=f"CEICC-HMAC-0: {e}")
    except CEICCError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/corpus/stats",
    response_model=CEICCResponse,
    summary="Return live invariant corpus statistics",
)
async def coherence_corpus_stats() -> CEICCResponse:
    """
    Return real-time corpus statistics — engine count, invariant count by engine —
    without writing a ledger entry. Useful for dashboard display and pre-check sizing.
    """
    try:
        stats = _engine.corpus_stats()
        return CEICCResponse(ok=True, data=stats)
    except CEICCError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/status",
    response_model=CEICCResponse,
    summary="CEICC module status and invariant manifest",
)
async def ceicc_status() -> CEICCResponse:
    """
    Return CEICC module status: INNOV code, version, governor, and the full
    list of 10 hard-class invariants enforced by this engine.
    """
    try:
        st = status()
        return CEICCResponse(ok=True, data=st)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
