# SPDX-License-Identifier: Apache-2.0
# INNOV-119 · CGVE — Constitutional Governance Version Enforcer — REST API
# Phase 214 · v10.25.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
FastAPI router for the Constitutional Governance Version Enforcer (CGVE).

Endpoints
---------
POST /cgve/enforce          — Run a full enforcement + auto-repair cycle
GET  /cgve/status           — Read current version surface snapshot (no mutation)
GET  /cgve/verify-chain     — Verify full HMAC chain integrity
GET  /cgve/history          — Retrieve enforcement history from ledger
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dorkllm.constitutional_governance_version_enforcer import (
    ConstitutionalGovernanceVersionEnforcer,
)

router = APIRouter(
    prefix="/cgve",
    tags=["CGVE — Constitutional Governance Version Enforcer"],
)

_enforcer = ConstitutionalGovernanceVersionEnforcer()


# ── Request / Response Models ─────────────────────────────────────────────────

class EnforceRequest(BaseModel):
    auto_repair: bool = Field(
        default=True,
        description="If True, blast_radius=1 drifts are atomically repaired.",
    )
    repo_root: Optional[str] = Field(
        default=None,
        description="Override repo root path (defaults to CWD).",
    )


class EnforceResponse(BaseModel):
    run_id: str
    timestamp: str
    canonical_version: str
    status: str
    drifts_detected: int
    repairs_executed: int
    human0_advisory: bool
    human0_message: Optional[str]
    hmac_digest: str


class SurfaceStatus(BaseModel):
    surface_id: str
    path: str
    version: Optional[str]
    readable: bool
    error: Optional[str]


class StatusResponse(BaseModel):
    canonical_version: Optional[str]
    compliant: bool
    surfaces: List[SurfaceStatus]


class ChainVerifyResponse(BaseModel):
    valid: bool
    entries: Optional[int]
    broken_at: Optional[int]
    run_id: Optional[str]
    message: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/enforce", response_model=EnforceResponse, summary="Run enforcement cycle")
def enforce(req: EnforceRequest) -> EnforceResponse:
    """
    Execute a full CGVE enforcement cycle.

    Reads all four canonical version surfaces, detects drift, auto-repairs
    blast_radius=1 sub-package surfaces (if auto_repair=True), and seals the
    run in the HMAC-chained enforcement ledger.
    """
    try:
        eng = ConstitutionalGovernanceVersionEnforcer(
            repo_root=Path(req.repo_root) if req.repo_root else None,
            auto_repair=req.auto_repair,
        )
        record = eng.enforce()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVE enforcement error: {exc}")

    return EnforceResponse(
        run_id=record.run_id,
        timestamp=record.timestamp,
        canonical_version=record.canonical_version,
        status=record.status,
        drifts_detected=len(record.drifts_detected),
        repairs_executed=len(record.repairs_executed),
        human0_advisory=record.human0_advisory,
        human0_message=record.human0_message,
        hmac_digest=record.hmac_digest,
    )


@router.get("/status", response_model=StatusResponse, summary="Version surface snapshot")
def status() -> StatusResponse:
    """
    Read current version surface state without triggering any enforcement.
    Safe to call at any time — purely observational.
    """
    try:
        snap = _enforcer.status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return StatusResponse(
        canonical_version=snap["canonical_version"],
        compliant=snap["compliant"],
        surfaces=[SurfaceStatus(**s) for s in snap["surfaces"]],
    )


@router.get("/verify-chain", response_model=ChainVerifyResponse, summary="Verify HMAC chain")
def verify_chain() -> ChainVerifyResponse:
    """Verify integrity of the full CGVE enforcement ledger HMAC chain."""
    try:
        result = _enforcer.verify_chain()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return ChainVerifyResponse(
        valid=result["valid"],
        entries=result.get("entries"),
        broken_at=result.get("broken_at"),
        run_id=result.get("run_id"),
        message=result["message"],
    )


@router.get("/history", summary="Enforcement history")
def history(
    limit: int = Query(default=20, ge=1, le=200, description="Max records to return"),
) -> List[Dict[str, Any]]:
    """Return the most recent enforcement run records from the ledger."""
    from dorkllm.constitutional_governance_version_enforcer import _LEDGER_PATH
    import json

    if not _LEDGER_PATH.exists():
        return []
    lines = [l.strip() for l in _LEDGER_PATH.read_text().splitlines() if l.strip()]
    recent = lines[-limit:]
    results = []
    for line in reversed(recent):
        try:
            r = json.loads(line)
            results.append({
                "run_id": r.get("run_id"),
                "timestamp": r.get("timestamp"),
                "canonical_version": r.get("canonical_version"),
                "status": r.get("status"),
                "drifts_detected": len(r.get("drifts_detected", [])),
                "repairs_executed": len(r.get("repairs_executed", [])),
                "human0_advisory": r.get("human0_advisory", False),
                "hmac_digest": r.get("hmac_digest", "")[:16] + "...",
            })
        except json.JSONDecodeError:
            continue
    return results
