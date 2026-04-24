# SPDX-License-Identifier: Apache-2.0
"""INNOV-59 · Adaptive Mutation Throttle (AMT) — Phase 153 / v9.86.0

Innovation registry wrapper for the ADAAD Constitutional Evolution Loop.

World-first claim (INNOV-59 #14):
    First constitutionally governed, feedback-control mutation throttle
    integrated into an autonomous AI governance pipeline — continuously
    adapts mutation admission rate from CPI pressure readings, enforces a
    Hard-class constitutional floor, and requires HUMAN-0 cryptographic
    authorisation for full-stop overrides, closing the CPI → AMT → GCB
    control loop with full ledger auditability.
"""

from __future__ import annotations

from dorkllm.adaptive_throttle import (
    AMT_VERSION,
    AMT_FLOOR,
    INNOV_ID,
    AMTConfig,
    AMTLedger,
    ThrottleEngine,
    ThrottleRegime,
    ThrottleSnapshot,
    AMTDeterminismError,
    AMTLedgerError,
    AMTFloorError,
    AMTAuthError,
    AMTScopeError,
)

INNOVATION_ID: str = INNOV_ID  # INNOV-59
PHASE: int = 153
VERSION: str = "9.86.0"

WORLD_FIRST_CLAIM: str = (
    "First constitutionally governed, feedback-control mutation throttle "
    "integrated into an autonomous AI governance pipeline — continuously adapts "
    "mutation admission rate from CPI pressure readings, enforces a Hard-class "
    "constitutional floor, and requires HUMAN-0 cryptographic authorisation for "
    "full-stop overrides, closing the CPI → AMT → GCB control loop with full "
    "ledger auditability."
)

HARD_CLASS_INVARIANTS: list[dict] = [
    {
        "id": "AMT-DETERM-0",
        "description": (
            "Throttle multiplier is a pure deterministic function of "
            "(pressure_snapshot, weights, floor); identical inputs always "
            "produce identical output. Timestamps and entropy are excluded."
        ),
        "tier": "Hard",
        "exception": "AMTDeterminismError",
    },
    {
        "id": "AMT-LEDGER-0",
        "description": (
            "Every ThrottleEngine.compute() call writes a THROTTLE_EVENT to "
            "the HMAC-chained ledger before the multiplier is returned. "
            "Ledger-write failure raises AMTLedgerError; no multiplier returned."
        ),
        "tier": "Hard",
        "exception": "AMTLedgerError",
    },
    {
        "id": "AMT-FLOOR-0",
        "description": (
            "The throttle multiplier never falls below AMT_FLOOR (0.05) "
            "during normal operation. Only a HUMAN-0-authorised emergency "
            "override may set multiplier to 0.0. Violation raises AMTFloorError."
        ),
        "tier": "Hard",
        "exception": "AMTFloorError",
    },
    {
        "id": "AMT-HUMAN0-0",
        "description": (
            "Emergency override and throttle-weight reconfiguration require a "
            "non-empty HUMAN-0 operator identity. Empty / None operator raises "
            "AMTAuthError before any state change occurs."
        ),
        "tier": "Hard",
        "exception": "AMTAuthError",
    },
    {
        "id": "AMT-FEEDBACK-0",
        "description": (
            "AMT reads only THROTTLE_EVENT and PRESSURE_SNAPSHOT records from "
            "the HMAC-chained ledger. It never reads live system state, process "
            "memory, or external APIs. Violations raise AMTScopeError."
        ),
        "tier": "Hard",
        "exception": "AMTScopeError",
    },
]


def build_engine(
    config: AMTConfig | None = None,
    ledger: AMTLedger | None = None,
) -> ThrottleEngine:
    """Convenience factory used by the CEL and MCP server."""
    return ThrottleEngine(config=config, ledger=ledger)


__all__ = [
    "INNOVATION_ID",
    "PHASE",
    "VERSION",
    "WORLD_FIRST_CLAIM",
    "HARD_CLASS_INVARIANTS",
    "AMT_VERSION",
    "AMT_FLOOR",
    "AMTConfig",
    "AMTLedger",
    "ThrottleEngine",
    "ThrottleRegime",
    "ThrottleSnapshot",
    "AMTDeterminismError",
    "AMTLedgerError",
    "AMTFloorError",
    "AMTAuthError",
    "AMTScopeError",
    "build_engine",
]
