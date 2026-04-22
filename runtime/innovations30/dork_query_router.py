# SPDX-License-Identifier: Apache-2.0
"""
runtime/innovations30/dork_query_router.py
Phase 146 · INNOV-52 · Dork Query Router (DQR)

Constitutional evolution wrapper for dorkllm/query_router.py.

Exposes DQR to the ADAAD innovation registry with Hard-class invariant
declarations and constitutional metadata required by GovernanceGateV2.

Hard-class invariants (5):
  DQR-ROUTE-0    Every query MUST produce a logged RouteDecision before dispatch.
  DQR-CHAIN-0    DQR ledger HMAC chain integrity is always verified on demand.
  DQR-DETERM-0   Scoring functions produce identical output for identical input.
  DQR-FALLBACK-0 route_query() MUST NEVER propagate an unhandled exception.
  DQR-AUTH-0     override_policy() requires constant-time HUMAN-0 auth.
"""
from __future__ import annotations

from typing import Any, Dict

# Re-export public API from the implementation module
from dorkllm.query_router import (  # noqa: F401
    RouteDecision,
    DQRInvariantViolation,
    DQRRouteViolation,
    DQRChainViolation,
    DQRAuthViolation,
    DQRLedgerWriteError,
    ROUTE_DPM,
    ROUTE_RAGS,
    ROUTE_PASSTHROUGH,
    DQR_ROUTE_0,
    DQR_CHAIN_0,
    DQR_DETERM_0,
    DQR_FALLBACK_0,
    DQR_AUTH_0,
    route_query,
    override_policy,
    clear_override,
    verify_chain,
    ledger_stats,
    _score_dpm,
    _score_rags,
)

# ── Innovation registry metadata ──────────────────────────────────────────────

INNOVATION_ID = "INNOV-52"
INNOVATION_NAME = "Dork Query Router (DQR)"
PHASE = 146
VERSION = "9.79.0"

HARD_CLASS_INVARIANTS: Dict[str, str] = {
    DQR_ROUTE_0:    "Every query MUST produce a logged RouteDecision before dispatch.",
    DQR_CHAIN_0:    "DQR ledger entries are HMAC-SHA256 hash-chained; any break is fatal.",
    DQR_DETERM_0:   "Scoring functions are deterministic: identical inputs → identical scores.",
    DQR_FALLBACK_0: "route_query() MUST NEVER propagate an unhandled exception.",
    DQR_AUTH_0:     "override_policy() requires constant-time HUMAN-0 token verification.",
}

CONSTITUTIONAL_DEPENDENCIES: list = [
    "INNOV-50:RAGS-GROUND-0",   # DQR routes to RAGS; inherits grounding invariant
    "INNOV-51:DPM-CHAIN-0",     # DQR routes to DPM; inherits chain invariant
]


def status() -> Dict[str, Any]:
    """Return DQR innovation registry status block."""
    stats = ledger_stats()
    return {
        "innovation_id": INNOVATION_ID,
        "innovation_name": INNOVATION_NAME,
        "phase": PHASE,
        "version": VERSION,
        "hard_class_invariants": list(HARD_CLASS_INVARIANTS.keys()),
        "invariant_count": len(HARD_CLASS_INVARIANTS),
        "ledger_stats": stats,
        "constitutional_dependencies": CONSTITUTIONAL_DEPENDENCIES,
    }
