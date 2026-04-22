# SPDX-License-Identifier: Apache-2.0
"""INNOV-57 · Governed Rollback (GRB) — registry wrapper.

Phase 151 / v9.84.0

Exposes the full GRB public API and constitutional metadata for governance
reporting.

Hard-class invariants introduced
----------------------------------
GRB-PREFLIGHT-0 : Rollback rejected unless target state passes all active
                  Hard-class invariants.
GRB-LEDGER-0    : Every rollback writes ROLLBACK_EVENT to lineage ledger
                  before any state mutation.
GRB-ATOMIC-0    : Rollback is all-or-nothing; ledger entry written first,
                  partial state writes impossible.
GRB-DETERM-0    : Rollback outcome is deterministic on (src, target,
                  invariant_set); timestamps excluded from digest.
GRB-HUMAN0-0    : Rollback requires non-empty operator identity; empty/None
                  operator rejected at preflight.
"""
from __future__ import annotations

from dorkllm.governed_rollback import (
    GRB_ATOMIC_RULE,
    GRB_DETERM_RULE,
    GRB_EVENT_TYPE,
    GRB_HUMAN0_RULE,
    GRB_LEDGER_RULE,
    GRB_PREFLIGHT_RULE,
    GRB_VERSION,
    INVARIANT_IDS,
    GovernedRollbackEngine,
    InvariantCheckResult,
    PhaseStateSnapshot,
    RollbackLedgerEntry,
    RollbackPreflightReport,
    RollbackResult,
    RollbackStatus,
    build_rollback_engine,
)

# ---------------------------------------------------------------------------
# Innovation metadata
# ---------------------------------------------------------------------------

INNOVATION_ID: str = "INNOV-57"
INNOVATION_NAME: str = "Governed Rollback (GRB)"
PHASE: int = 151
VERSION: str = "9.84.0"

HARD_CLASS_INVARIANTS: tuple[dict[str, str], ...] = (
    {
        "id": "GRB-PREFLIGHT-0",
        "class": "Hard",
        "description": (
            "Rollback is rejected if target-phase state violates any currently-active "
            "Hard-class invariant."
        ),
    },
    {
        "id": "GRB-LEDGER-0",
        "class": "Hard",
        "description": (
            "Every rollback writes a ROLLBACK_EVENT (src, target, operator) to the "
            "lineage ledger before any state mutation occurs."
        ),
    },
    {
        "id": "GRB-ATOMIC-0",
        "class": "Hard",
        "description": (
            "Rollback is all-or-nothing; partial state writes are impossible — ledger "
            "entry is written first, write failure prevents any state change."
        ),
    },
    {
        "id": "GRB-DETERM-0",
        "class": "Hard",
        "description": (
            "Rollback outcome is deterministic on (src_phase, target_phase, "
            "invariant_set); timestamps excluded from digest computation."
        ),
    },
    {
        "id": "GRB-HUMAN0-0",
        "class": "Hard",
        "description": (
            "Rollback execution requires a non-empty operator identity string; "
            "empty/None operator is rejected at preflight."
        ),
    },
)

INNOVATION_MANIFEST: dict[str, object] = {
    "innovation_id": INNOVATION_ID,
    "innovation_name": INNOVATION_NAME,
    "phase": PHASE,
    "version": VERSION,
    "grb_version": GRB_VERSION,
    "hard_class_invariants": HARD_CLASS_INVARIANTS,
    "invariant_ids": INVARIANT_IDS,
    "primary_module": "dorkllm/governed_rollback.py",
    "test_file": f"tests/innovations/test_phase{PHASE}_grb.py",
    "acceptance_tests": 30,
}

# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    # metadata
    "INNOVATION_ID",
    "INNOVATION_NAME",
    "PHASE",
    "VERSION",
    "HARD_CLASS_INVARIANTS",
    "INNOVATION_MANIFEST",
    # core API
    "GRB_VERSION",
    "GRB_EVENT_TYPE",
    "GRB_PREFLIGHT_RULE",
    "GRB_LEDGER_RULE",
    "GRB_ATOMIC_RULE",
    "GRB_DETERM_RULE",
    "GRB_HUMAN0_RULE",
    "INVARIANT_IDS",
    "RollbackStatus",
    "InvariantCheckResult",
    "RollbackPreflightReport",
    "RollbackLedgerEntry",
    "RollbackResult",
    "PhaseStateSnapshot",
    "GovernedRollbackEngine",
    "build_rollback_engine",
]
