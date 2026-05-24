# SPDX-License-Identifier: Proprietary — All Rights Reserved
"""
REST router — INNOV-93 · GTC — Governance Tag Certifier
Phase 188 · v9.121.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/gtc", tags=["GTC — Governance Tag Certifier"])

_GTC_INSTANCE: Any = None


def _get_gtc() -> Any:
    global _GTC_INSTANCE
    if _GTC_INSTANCE is None:
        from dorkllm.governance_tag_certifier import GovernanceTagCertifier
        _GTC_INSTANCE = GovernanceTagCertifier()
    return _GTC_INSTANCE


@router.post("/certify", summary="Execute governance tag certification sequence")
def certify(require_gpe_ready: bool = Query(False, description="Require GPE PromotionStatus.READY")):
    """
    Execute the Governance Tag Certification sequence.

    Computes the Constitutional Merkle Root over all shipped innovations,
    emits a HUMAN-0 ceremony advisory, seals the Release Bundle, and returns
    the full certification result including ceremony runbook.

    GTC-SCOPE-0: read-only operation against agent state and GPE manifest.
    GTC-HUMAN0-0: HUMAN-0 advisory emitted before bundle is sealed.
    """
    try:
        result = _get_gtc().certify(require_gpe_ready=require_gpe_ready)
        # Convert enum to string for JSON serialisation
        if hasattr(result.get("certification_status"), "value"):
            result["certification_status"] = result["certification_status"].value
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", summary="Return the full HMAC-chained release bundle ledger")
def history():
    """
    GTC-IMMUT-0: returns read-only view of all release bundle entries.
    """
    try:
        return {"release_ledger": _get_gtc().history()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/verify-chain", summary="Verify HMAC chain integrity of release ledger")
def verify_chain():
    """
    GTC-CHAIN-0: verify that every bundle entry's HMAC matches expected value.
    Returns 200 on success, 500 on chain violation.
    """
    try:
        ok = _get_gtc().verify_chain()
        return {"chain_valid": ok}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chain violation: {exc}")


@router.get("/advisory", summary="Return the latest HUMAN-0 ceremony advisory")
def latest_advisory():
    """
    Returns the most recent HUMAN-0 ceremony advisory emitted by GTC.
    """
    try:
        adv = _get_gtc().latest_advisory()
        if adv is None:
            return {"advisory": None, "message": "No advisory emitted yet — call /certify first"}
        return {"advisory": adv}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
