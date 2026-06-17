"""
ACDR API Router — Autonomous Constitutional Drift Reporter
INNOV-127 · Phase 222 · Arc II — Self-Amendment & Meta-Governance
InnovativeAI LLC · Governor: DUSTIN L REID

Endpoints:
  POST /acdr/detect        — Execute a drift detection run
  GET  /acdr/report/latest — Retrieve latest drift report
  GET  /acdr/chain/verify  — Verify HMAC chain integrity
  GET  /acdr/quarantine    — Inspect CRITICAL events pending HUMAN-0 ack
  POST /acdr/ack/{event_id}— HUMAN-0 acknowledge a CRITICAL drift event
  GET  /acdr/status        — Engine health and invariant roster
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

from dorkllm.autonomous_constitutional_drift_reporter import (
    AutonomousConstitutionalDriftReporter,
)

router = APIRouter(prefix="/acdr", tags=["ACDR"])

# Singleton engine instance
_engine = AutonomousConstitutionalDriftReporter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────
class DomainContext(BaseModel):
    expected_invariants:      Optional[int]   = Field(default=10, ge=0)
    observed_invariants:      Optional[int]   = Field(default=10, ge=0)
    chain_valid:              Optional[bool]  = True
    broken_sequences:         Optional[List[int]] = Field(default_factory=list)
    stalled_proposals:        Optional[int]   = Field(default=0, ge=0)
    max_stale_age_hours:      Optional[float] = Field(default=0.0, ge=0.0)
    latency_threshold_hours:  Optional[float] = Field(default=24.0, gt=0.0)
    coherence_score:          Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    prior_coherence_score:    Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    authority_violations:     Optional[List[str]] = Field(default_factory=list)


class DetectRequest(BaseModel):
    domain_contexts: Optional[Dict[str, DomainContext]] = Field(
        default=None,
        description=(
            "Per-domain context data for drift analysis. "
            "Keys must match registered domain names: "
            "ACSA, ACPA, ACAM, CARE, CEICC, CGML, ACDR."
        ),
    )


class AckRequest(BaseModel):
    authority: str = Field(
        default="HUMAN-0",
        description="Authority identity performing the acknowledgment.",
    )


# ── POST /acdr/detect ─────────────────────────────────────────────────────────
@router.post(
    "/detect",
    summary="Execute a full constitutional drift detection run",
    response_model=Dict[str, Any],
)
async def detect_drift(body: DetectRequest = Body(default=DetectRequest())) -> Dict[str, Any]:
    """
    ACDR-DETECT-0 · ACDR-AUDIT-0 · ACDR-ENTROPY-0

    Runs drift detection across all registered Arc II constitutional domains.
    Returns an entropy-scored drift report with severity tiers and remediation
    recommendations. CRITICAL events are automatically quarantined pending HUMAN-0
    acknowledgment (ACDR-HUMAN0-0).
    """
    contexts: Optional[Dict[str, dict]] = None
    if body.domain_contexts:
        contexts = {k: v.model_dump() for k, v in body.domain_contexts.items()}
    report = _engine.run_detection(domain_contexts=contexts)
    return {
        "status":           "OK",
        "report_id":        report.report_id,
        "run_id":           report.run_id,
        "domains_evaluated":report.domains_evaluated,
        "event_count":      len(report.events),
        "overall_entropy":  report.overall_entropy,
        "overall_severity": report.overall_severity,
        "remediation_count":report.remediation_count,
        "quarantined_count":report.quarantined_count,
        "chain_head":       report.chain_head[:16] + "…",
        "invariant":        "ACDR-DETECT-0",
    }


# ── GET /acdr/report/latest ───────────────────────────────────────────────────
@router.get(
    "/report/latest",
    summary="Retrieve latest drift report with full event detail",
    response_model=Dict[str, Any],
)
async def get_report() -> Dict[str, Any]:
    """
    ACDR-REPORT-0 · ACDR-REPLAY-0

    Returns the current accumulated drift report including all detected events,
    per-event remediation recommendations, and aggregate severity.
    """
    return _engine.get_report()


# ── GET /acdr/chain/verify ────────────────────────────────────────────────────
@router.get(
    "/chain/verify",
    summary="Verify HMAC-SHA-256 chain integrity of the drift ledger",
    response_model=Dict[str, Any],
)
async def verify_chain() -> Dict[str, Any]:
    """
    ACDR-CHAIN-0 · ACDR-HMAC-0 · ACDR-REPLAY-0

    Traverses the full ACDR drift ledger from GENESIS, verifying each entry's
    HMAC-SHA-256 digest and chain linkage. Any break is reported with the failing
    sequence number.
    """
    result = _engine.verify_chain()
    if not result["valid"]:
        raise HTTPException(
            status_code=500,
            detail={**result, "invariant": "ACDR-CHAIN-0",
                    "action": "Halt write operations; initiate CARE rollback."},
        )
    return {**result, "status": "CHAIN_INTACT", "invariant": "ACDR-CHAIN-0"}


# ── GET /acdr/quarantine ──────────────────────────────────────────────────────
@router.get(
    "/quarantine",
    summary="Inspect CRITICAL drift events pending HUMAN-0 acknowledgment",
    response_model=Dict[str, Any],
)
async def get_quarantine() -> Dict[str, Any]:
    """
    ACDR-HUMAN0-0

    Lists all CRITICAL-severity drift events currently quarantined pending
    explicit HUMAN-0 acknowledgment before downstream mutation promotion
    may proceed.
    """
    return _engine.get_quarantine()


# ── POST /acdr/ack/{event_id} ─────────────────────────────────────────────────
@router.post(
    "/ack/{event_id}",
    summary="HUMAN-0 acknowledge a CRITICAL drift event to lift quarantine",
    response_model=Dict[str, Any],
)
async def acknowledge_event(
    event_id: str = Path(..., description="UUID of the CRITICAL drift event to acknowledge"),
    body: AckRequest = Body(default=AckRequest()),
) -> Dict[str, Any]:
    """
    ACDR-HUMAN0-0 · ACDR-HISTORY-0 · ACDR-AUDIT-0

    HUMAN-0 exclusive action: acknowledges a CRITICAL drift event, lifting
    its quarantine. The acknowledgment is sealed into the immutable drift ledger.
    Non-existent or already-acknowledged events return 404.
    """
    result = _engine.human0_acknowledge(event_id, authority=body.authority)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(
            status_code=404,
            detail={**result,
                    "note": "Event not in quarantine (may already be acknowledged or not exist)."},
        )
    return result


# ── GET /acdr/status ──────────────────────────────────────────────────────────
@router.get(
    "/status",
    summary="ACDR engine health, chain state, and invariant roster",
    response_model=Dict[str, Any],
)
async def get_status() -> Dict[str, Any]:
    """
    Returns live ACDR engine status including ledger sequence, chain head,
    quarantine count, and the full 10-invariant roster.
    """
    return _engine.get_status()
