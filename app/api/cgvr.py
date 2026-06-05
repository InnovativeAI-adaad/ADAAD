# SPDX-License-Identifier: Apache-2.0
# INNOV-118 · CGVR — Constitutional Governance Violation Remediator — REST API
# Phase 213 · v10.24.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
FastAPI router for the Constitutional Governance Violation Remediator (CGVR).

Endpoints
---------
POST /cgvr/remediate                — Execute a remediation run for a violation
POST /cgvr/approve-tier0/{id}       — HUMAN-0 approval of Tier-0 blocked actions
GET  /cgvr/history                  — Retrieve remediation history
GET  /cgvr/verify-chain             — Verify full HMAC chain integrity
GET  /cgvr/status                   — Engine status summary
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dorkllm.constitutional_governance_violation_remediator import (
    ConstitutionalGovernanceViolationRemediator,
)

router = APIRouter(
    prefix="/cgvr",
    tags=["CGVR — Constitutional Governance Violation Remediator"],
)

_remediator = ConstitutionalGovernanceViolationRemediator()


# ── Request / Response Models ─────────────────────────────────────────────────

class RemediateRequest(BaseModel):
    violation_id:      str = Field(..., description="CGVA attestation_id or synthetic violation key")
    domain:            str = Field(..., description="Governance domain (e.g. 'pipeline', 'mutation')")
    failed_dimensions: List[str] = Field(
        default_factory=list,
        description="List of CGVA dimension names that failed validation",
    )
    context: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata")


class RemediationSummary(BaseModel):
    remediation_id:  str
    violation_id:    str
    domain:          str
    ts_ns:           int
    status:          str
    human0_required: bool
    actions_executed: int
    actions_total:   int
    governor:        str
    hmac_digest_prefix: str
    prev_digest_prefix: str


class ChainVerifyResponse(BaseModel):
    chain_valid:       bool
    first_break_index: Optional[int]
    total_records:     int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/remediate", summary="Execute a remediation run for a governance violation")
async def remediate(req: RemediateRequest) -> Dict[str, Any]:
    """
    Ingest a CGVA violation signal, derive the constitutional remediation plan,
    execute all Tier-1/2 actions autonomously, and gate Tier-0 actions behind
    HUMAN-0 ratification.  Returns a sealed RemediationRecord.
    """
    try:
        record = _remediator.remediate(
            violation_id=req.violation_id,
            domain=req.domain,
            failed_dimensions=req.failed_dimensions,
            context=req.context,
        )
        return {
            "remediation_id":   record.remediation_id,
            "violation_id":     record.violation_id,
            "domain":           record.domain,
            "ts_ns":            record.ts_ns,
            "status":           record.status,
            "human0_required":  record.human0_required,
            "actions_executed": record.actions_executed,
            "actions_total":    record.actions_total,
            "governor":         record.governor,
            "plan": [
                {
                    "action_id":    a.action_id,
                    "action_type":  a.action_type,
                    "blast_radius": a.blast_radius,
                    "description":  a.description,
                    "executed":     a.executed,
                    "outcome":      a.outcome,
                }
                for a in record.plan
            ],
            "hmac_digest_prefix": record.hmac_digest[:16],
            "prev_digest_prefix": record.prev_digest[:16] if record.prev_digest != "GENESIS" else "GENESIS",
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CGVR remediation failed: {exc}") from exc


@router.post(
    "/approve-tier0/{remediation_id}",
    response_model=RemediationSummary,
    summary="HUMAN-0 approval of Tier-0 blocked actions",
)
async def approve_tier0(remediation_id: str) -> RemediationSummary:
    """
    Apply HUMAN-0 ratification to a HUMAN0_REQUIRED remediation record,
    executing all previously-blocked Tier-0 actions and re-sealing the record.
    """
    try:
        record = _remediator.approve_tier0(remediation_id)
        return RemediationSummary(
            remediation_id=record.remediation_id,
            violation_id=record.violation_id,
            domain=record.domain,
            ts_ns=record.ts_ns,
            status=record.status,
            human0_required=record.human0_required,
            actions_executed=record.actions_executed,
            actions_total=record.actions_total,
            governor=record.governor,
            hmac_digest_prefix=record.hmac_digest[:16],
            prev_digest_prefix=record.prev_digest[:16] if record.prev_digest != "GENESIS" else "GENESIS",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tier-0 approval failed: {exc}") from exc


@router.get("/history", summary="Retrieve remediation history")
async def get_history(
    domain: Optional[str] = Query(None, description="Filter by governance domain"),
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
) -> Dict[str, Any]:
    """
    Return recent remediation records from the CGVR ledger,
    optionally filtered by domain.
    """
    records = _remediator.history(domain=domain, limit=limit)
    return {
        "count":         len(records),
        "domain_filter": domain,
        "remediations": [
            {
                "remediation_id":   r.remediation_id,
                "violation_id":     r.violation_id,
                "domain":           r.domain,
                "ts_ns":            r.ts_ns,
                "status":           r.status,
                "human0_required":  r.human0_required,
                "actions_executed": r.actions_executed,
                "actions_total":    r.actions_total,
            }
            for r in records
        ],
    }


@router.get(
    "/verify-chain",
    response_model=ChainVerifyResponse,
    summary="Verify full HMAC chain integrity",
)
async def verify_chain() -> ChainVerifyResponse:
    """
    Perform a full HMAC chain integrity sweep over the CGVR remediation ledger.
    """
    chain_valid, break_idx = _remediator.verify_chain()
    return ChainVerifyResponse(
        chain_valid=chain_valid,
        first_break_index=break_idx,
        total_records=len(_remediator.records),
    )


@router.get("/status", summary="CGVR engine status summary")
async def get_status() -> Dict[str, Any]:
    """Return comprehensive CGVR engine status."""
    return _remediator.status()
