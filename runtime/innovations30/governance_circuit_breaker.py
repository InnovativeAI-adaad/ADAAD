# SPDX-License-Identifier: Apache-2.0
"""INNOV-56 · Governance Circuit Breaker (GCB) — registry wrapper.

Phase 150 / v9.83.0

Exposes the full GCB public API to GovernanceGateV2 and makes
constitutional metadata available for governance reporting.

Hard-class invariants introduced
---------------------------------
GCB-CHAIN-0    : HMAC-SHA256 chain integrity across all circuit events.
GCB-FAILCLOSE-0: OPEN circuit blocks all mutations via assert_circuit_closed().
GCB-READONLY-0 : GCB never mutates CEL, LEF, or mutation pipeline state.
GCB-DETERM-0   : Cascade detection is deterministic; timestamps excluded.
GCB-HUMAN0-0   : Circuit reset requires constant-time HUMAN-0 token auth.
"""

from dorkllm.circuit_breaker import (
    CIRCUIT_CLOSED,
    CIRCUIT_OPEN,
    DEFAULT_NAMESPACE_THRESHOLD,
    DEFAULT_VIOLATION_THRESHOLD,
    DEFAULT_WINDOW_SIZE,
    CircuitBreakerEngine,
    CircuitEvent,
    GCBAuthViolation,
    GCBChainState,
    GCBChainViolation,
    GCBDeterminismViolation,
    GCBMutationViolation,
    GCBOpenViolation,
    ViolationWindow,
)

INNOVATION_CODE = "INNOV-56"
INNOVATION_NAME = "Governance Circuit Breaker (GCB)"
INNOVATION_VERSION = "9.83.0"
INNOVATION_PHASE = 150

CONSTITUTIONAL_INVARIANTS = [
    {
        "id": "GCB-CHAIN-0",
        "class": "Hard",
        "description": (
            "All GCB ledger entries MUST carry a valid HMAC-SHA256 chain link. "
            "Any chain break is fatal and immediately raises GCBChainViolation. "
            "No entry may be written without a valid prev_hash link."
        ),
    },
    {
        "id": "GCB-FAILCLOSE-0",
        "class": "Hard",
        "description": (
            "When the circuit is OPEN, assert_circuit_closed() MUST raise "
            "GCBOpenViolation. Mutation pipeline gates MUST call this method "
            "before any mutation proceeds. The gate never silently passes."
        ),
    },
    {
        "id": "GCB-READONLY-0",
        "class": "Hard",
        "description": (
            "GCB MUST never mutate CEL execution state, LEF subscriber sets, "
            "or any mutation pipeline state. Only the GCB JSONL ledger is "
            "written. GCBMutationViolation is raised if the contract is broken."
        ),
    },
    {
        "id": "GCB-DETERM-0",
        "class": "Hard",
        "description": (
            "Cascade detection MUST be deterministic. Identical violation "
            "sequences always produce identical circuit decisions. Timestamps "
            "are excluded from the cascade algorithm; only event ordering and "
            "namespace counts determine the outcome."
        ),
    },
    {
        "id": "GCB-HUMAN0-0",
        "class": "Hard",
        "description": (
            "Circuit reset from OPEN to CLOSED requires HUMAN-0 authorisation "
            "verified via constant-time hmac.compare_digest. Plaintext token "
            "comparison is constitutionally prohibited. Invalid tokens raise "
            "GCBAuthViolation and the circuit remains OPEN."
        ),
    },
]

WORLD_FIRST_CLAIM = (
    "First constitutionally governed, fail-closed circuit breaker integrated "
    "into an autonomous AI mutation pipeline — trips deterministically on "
    "invariant cascade detection and requires HUMAN-0 cryptographic "
    "authorisation to restore, ensuring human oversight is mandatory after "
    "any constitutional cascade failure."
)

__all__ = [
    "CIRCUIT_CLOSED",
    "CIRCUIT_OPEN",
    "CONSTITUTIONAL_INVARIANTS",
    "DEFAULT_NAMESPACE_THRESHOLD",
    "DEFAULT_VIOLATION_THRESHOLD",
    "DEFAULT_WINDOW_SIZE",
    "INNOVATION_CODE",
    "INNOVATION_NAME",
    "INNOVATION_PHASE",
    "INNOVATION_VERSION",
    "WORLD_FIRST_CLAIM",
    "CircuitBreakerEngine",
    "CircuitEvent",
    "GCBAuthViolation",
    "GCBChainState",
    "GCBChainViolation",
    "GCBDeterminismViolation",
    "GCBMutationViolation",
    "GCBOpenViolation",
    "ViolationWindow",
]
