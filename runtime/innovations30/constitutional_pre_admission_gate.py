# SPDX-License-Identifier: Apache-2.0
"""INNOV-60 · Constitutional Pre-Admission Gate (CPAG) — Phase 154 / v9.87.0

Innovation registry wrapper for the ADAAD Constitutional Evolution Loop.

World-first claim (INNOV-60 #15):
    First constitutionally governed, pre-admission mutation gate integrated
    into an autonomous AI pipeline — evaluates every proposed mutation
    against the active Hard-class invariant set before pipeline entry,
    enforces fail-closed rejection with full per-invariant rationale,
    integrates AMT throttle pressure to tighten admission bars under load,
    and requires HUMAN-0 cryptographic authorisation for threshold
    reconfiguration — completing the full constitutional lifecycle:
    propose → CPAG (gate) → CEL (execute) → AMT (throttle) → GCB (break)
    → GRB (recover).
"""

from __future__ import annotations

from dorkllm.constitutional_gate import (
    CPAG_VERSION,
    INNOV_ID,
    AdmissionVerdict,
    ConstitutionalGate,
    ConstitutionalInvariant,
    CPAGAuthError,
    CPAGConfig,
    CPAGDeterminismError,
    CPAGLedger,
    CPAGLedgerError,
    CPAGRejectionError,
    CPAGScopeError,
    InvariantEval,
    VerdictResult,
    default_invariant_set,
)

INNOVATION_ID: str = INNOV_ID  # INNOV-60
PHASE: int = 154
VERSION: str = "9.87.0"

WORLD_FIRST_CLAIM: str = (
    "First constitutionally governed, pre-admission mutation gate integrated "
    "into an autonomous AI pipeline — evaluates every proposed mutation against "
    "the active Hard-class invariant set before pipeline entry, enforces "
    "fail-closed rejection with full per-invariant rationale, integrates AMT "
    "throttle pressure to tighten admission bars under load, and requires "
    "HUMAN-0 cryptographic authorisation for threshold reconfiguration — "
    "completing the full constitutional lifecycle: propose → CPAG → CEL → "
    "AMT → GCB → GRB."
)

HARD_CLASS_INVARIANTS: list[dict] = [
    {
        "id": "CPAG-DETERM-0",
        "description": (
            "AdmissionVerdict is a pure deterministic function of "
            "(mutation_spec, invariant_set, throttle_multiplier, thresholds). "
            "Timestamps and entropy excluded."
        ),
        "tier": "Hard",
        "exception": "CPAGDeterminismError",
    },
    {
        "id": "CPAG-LEDGER-0",
        "description": (
            "Every gate() call writes an ADMISSION_VERDICT to the "
            "HMAC-chained ledger before the verdict is returned. "
            "Ledger failure raises CPAGLedgerError."
        ),
        "tier": "Hard",
        "exception": "CPAGLedgerError",
    },
    {
        "id": "CPAG-FAILCLOSE-0",
        "description": (
            "REJECT verdicts raise CPAGRejectionError — the gate never "
            "silently passes a rejected mutation."
        ),
        "tier": "Hard",
        "exception": "CPAGRejectionError",
    },
    {
        "id": "CPAG-HUMAN0-0",
        "description": (
            "Threshold reconfiguration requires a non-empty HUMAN-0 operator "
            "identity. Empty / None raises CPAGAuthError."
        ),
        "tier": "Hard",
        "exception": "CPAGAuthError",
    },
    {
        "id": "CPAG-SCOPE-0",
        "description": (
            "CPAG evaluates only the mutation_spec dict and invariant_set. "
            "It never reads live system state, process memory, or external "
            "APIs during scoring. Violations raise CPAGScopeError."
        ),
        "tier": "Hard",
        "exception": "CPAGScopeError",
    },
]


def build_gate(
    config: CPAGConfig | None = None,
    invariant_set: list[ConstitutionalInvariant] | None = None,
    ledger: CPAGLedger | None = None,
) -> ConstitutionalGate:
    """Convenience factory used by the CEL admission layer."""
    return ConstitutionalGate(
        config=config,
        invariant_set=invariant_set,
        ledger=ledger,
    )


__all__ = [
    "INNOVATION_ID",
    "PHASE",
    "VERSION",
    "WORLD_FIRST_CLAIM",
    "HARD_CLASS_INVARIANTS",
    "CPAG_VERSION",
    "AdmissionVerdict",
    "ConstitutionalGate",
    "ConstitutionalInvariant",
    "CPAGAuthError",
    "CPAGConfig",
    "CPAGDeterminismError",
    "CPAGLedger",
    "CPAGLedgerError",
    "CPAGRejectionError",
    "CPAGScopeError",
    "InvariantEval",
    "VerdictResult",
    "default_invariant_set",
    "build_gate",
]
