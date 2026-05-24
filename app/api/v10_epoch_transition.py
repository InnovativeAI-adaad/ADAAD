# SPDX-License-Identifier: Proprietary — All Rights Reserved
"""
REST router — INNOV-94 · V10ET — V10 Epoch Transition Engine
Phase 189 · v9.122.0 · InnovativeAI LLC
Governor: DUSTIN L REID
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/v10et", tags=["V10ET — V10 Epoch Transition Engine"])

_V10ET_INSTANCE: Any = None


def _get_engine() -> Any:
    global _V10ET_INSTANCE
    if _V10ET_INSTANCE is None:
        from dorkllm.v10_epoch_transition import V10EpochTransitionEngine
        _V10ET_INSTANCE = V10EpochTransitionEngine()
    return _V10ET_INSTANCE


@router.post("/seal", summary="Execute V10 epoch transition — seal v9→v10 boundary")
def seal(
    dry_run: bool = Query(False, description="Validate and emit advisory without writing to ledger"),
):
    """
    Execute the V10 Epoch Transition sequence.

    Consumes the GTC Release Bundle, re-validates the Constitutional Merkle Root
    (V10ET-VERIFY-0), emits the HUMAN-0 Track B runbook (V10ET-HUMAN0-0), and
    seals the v9→v10 epoch boundary in the append-only epoch ledger (V10ET-CHAIN-0).

    V10ET-EPOCH-0: this is a one-way, irreversible operation.
    V10ET-SCOPE-0: read-only with respect to all upstream state.
    """
    try:
        result = _get_engine().seal(dry_run=dry_run)
        return {
            "status": result.status,
            "epoch_boundary": result.epoch_boundary,
            "human0_advisory": result.human0_advisory,
            "chain_valid": result.chain_valid,
            "findings": result.findings,
            "track_b_runbook": result.track_b_runbook,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", summary="Return the full HMAC-chained epoch ledger")
def history():
    """
    V10ET-CHAIN-0 + V10ET-IMMUT-0: returns read-only view of all epoch boundary entries.
    """
    try:
        return {"epoch_ledger": _get_engine().history()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/verify-chain", summary="Verify HMAC chain integrity of the epoch ledger")
def verify_chain():
    """
    V10ET-CHAIN-0: verify that every epoch ledger entry's HMAC is valid.
    Returns 200 + chain_valid: true on success, 500 on chain violation.
    """
    try:
        ok = _get_engine().verify_chain()
        return {"chain_valid": ok}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chain violation: {exc}")


@router.get("/advisory", summary="Return the latest HUMAN-0 Track B ceremony advisory")
def latest_advisory():
    """
    V10ET-HUMAN0-0: returns the most recent HUMAN-0 advisory emitted by V10ET.
    """
    try:
        adv = _get_engine().latest_advisory()
        if adv is None:
            return {
                "advisory": None,
                "message": "No advisory emitted yet — call POST /v10et/seal first",
            }
        return {"advisory": adv}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
