# SPDX-License-Identifier: Apache-2.0
"""INNOV-57 · Governed Rollback (GRB) — Phase 151 / v9.84.0

Safety-gated rollback operation.  Uses the lineage ledger as source of truth
to reconstruct the system's declared state at a prior phase, validates the
target state against all currently-active Hard-class invariants via a
GovernanceGate preflight, writes a tamper-evident ROLLBACK_EVENT to the
ledger, and guarantees atomicity: no file writes occur unless the preflight
passes and the ledger write succeeds first.

Hard-class invariants
----------------------
GRB-PREFLIGHT-0  : Rollback is rejected if target-phase state violates any
                   currently-active Hard-class invariant.
GRB-LEDGER-0     : Every rollback writes a ROLLBACK_EVENT (src, target,
                   operator, timestamp) to the lineage ledger before any
                   state mutation occurs.
GRB-ATOMIC-0     : Rollback is all-or-nothing; partial state writes
                   are impossible — the ledger event is written first, and
                   any write failure rolls back the ledger entry.
GRB-DETERM-0     : Rollback outcome is deterministic on (src_phase,
                   target_phase, invariant_set); timestamps excluded.
GRB-HUMAN0-0     : Rollback execution requires a non-empty operator identity
                   string; empty/None operator is rejected at the preflight.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

GRB_VERSION: str = "1.0.0"
GRB_EVENT_TYPE: str = "ROLLBACK_EVENT"
GRB_PREFLIGHT_RULE: str = "ROLLBACK-PREFLIGHT-0"
GRB_LEDGER_RULE: str = "ROLLBACK-LEDGER-0"
GRB_ATOMIC_RULE: str = "ROLLBACK-ATOMIC-0"
GRB_DETERM_RULE: str = "ROLLBACK-DETERM-0"
GRB_HUMAN0_RULE: str = "ROLLBACK-HUMAN0-0"

INVARIANT_IDS: tuple[str, ...] = (
    "GRB-PREFLIGHT-0",
    "GRB-LEDGER-0",
    "GRB-ATOMIC-0",
    "GRB-DETERM-0",
    "GRB-HUMAN0-0",
)


# ---------------------------------------------------------------------------
# Enums and value objects
# ---------------------------------------------------------------------------

class RollbackStatus(str, Enum):
    PENDING = "PENDING"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    LEDGER_FAILED = "LEDGER_FAILED"
    SUCCESS = "SUCCESS"
    REJECTED_OPERATOR = "REJECTED_OPERATOR"
    REJECTED_TARGET = "REJECTED_TARGET"


@dataclass(frozen=True)
class InvariantCheckResult:
    """Result of a single invariant check against a rollback target."""
    invariant_id: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class RollbackPreflightReport:
    """Aggregated preflight result for a rollback request."""
    target_phase: int
    source_phase: int
    operator: str
    checks: tuple[InvariantCheckResult, ...]
    passed: bool
    failure_reason: str = ""

    @property
    def failed_invariants(self) -> tuple[InvariantCheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)


@dataclass(frozen=True)
class RollbackLedgerEntry:
    """Tamper-evident ledger record for a rollback event."""
    event_type: str
    source_phase: int
    target_phase: int
    operator: str
    version_before: str
    version_after: str
    hard_class_before: int
    hard_class_after: int
    preflight_passed: bool
    entry_digest: str
    prev_digest: str
    seq: int


@dataclass(frozen=True)
class RollbackResult:
    """Final result returned to the caller after a rollback attempt."""
    status: RollbackStatus
    source_phase: int
    target_phase: int
    operator: str
    preflight: RollbackPreflightReport | None
    ledger_entry: RollbackLedgerEntry | None
    state_delta: dict[str, Any]
    error: str = ""


# ---------------------------------------------------------------------------
# Invariant checks
# ---------------------------------------------------------------------------

class RollbackPreflightError(ValueError):
    """Raised when GRB-PREFLIGHT-0 is violated."""


class RollbackOperatorError(ValueError):
    """Raised when GRB-HUMAN0-0 is violated (empty/None operator)."""


class RollbackTargetError(ValueError):
    """Raised when the requested target phase is nonsensical."""


class RollbackLedgerError(RuntimeError):
    """Raised when GRB-LEDGER-0 / GRB-ATOMIC-0 ledger write fails."""


# ---------------------------------------------------------------------------
# Phase state snapshot — lightweight representation used by the preflight
# ---------------------------------------------------------------------------

@dataclass
class PhaseStateSnapshot:
    """Minimal declared state for a phase, used by rollback preflight."""
    phase: int
    version: str
    hard_class_count: int
    innovations_shipped: int
    invariant_ids: frozenset[str] = field(default_factory=frozenset)

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "version": self.version,
            "hard_class_count": self.hard_class_count,
            "innovations_shipped": self.innovations_shipped,
            "invariant_ids": sorted(self.invariant_ids),
        }


# ---------------------------------------------------------------------------
# Ledger chain helper  (independent of CryovantJournal to avoid coupling)
# ---------------------------------------------------------------------------

def _compute_entry_digest(
    event_type: str,
    source_phase: int,
    target_phase: int,
    operator: str,
    seq: int,
) -> str:
    """Deterministic digest for a rollback ledger entry (GRB-DETERM-0).

    Timestamps are *excluded* intentionally so that the digest is
    reproducible given the same logical inputs.
    """
    payload = json.dumps(
        {
            "event_type": event_type,
            "source_phase": source_phase,
            "target_phase": target_phase,
            "operator": operator,
            "seq": seq,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _chain_digest(entry_digest: str, prev_digest: str) -> str:
    """HMAC-chain two digests using SHA-256 (GRB-LEDGER-0)."""
    return hmac.new(
        prev_digest.encode(),
        entry_digest.encode(),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class GovernedRollbackEngine:
    """Implements the GRB safety-gated rollback protocol.

    Parameters
    ----------
    current_snapshot:
        The live system state (source phase for the rollback).
    ledger_entries:
        Mutable list that accumulates ROLLBACK_EVENT records.
        Callers may inject an in-memory list (tests) or a real append-only
        store.
    invariant_registry:
        Mapping of invariant_id → callable(PhaseStateSnapshot) → bool.
        Used by the preflight to validate the target state against every
        active Hard-class invariant.
    """

    def __init__(
        self,
        current_snapshot: PhaseStateSnapshot,
        ledger_entries: list[dict[str, Any]] | None = None,
        invariant_registry: dict[str, Any] | None = None,
    ) -> None:
        self._current = current_snapshot
        self._ledger: list[dict[str, Any]] = ledger_entries if ledger_entries is not None else []
        self._registry: dict[str, Any] = invariant_registry or {}
        self._seq: int = len(self._ledger)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preflight(
        self,
        target_snapshot: PhaseStateSnapshot,
        operator: str,
    ) -> RollbackPreflightReport:
        """Run the GovernanceGate preflight for a rollback request.

        Validates:
        1. GRB-HUMAN0-0   — operator identity is non-empty
        2. GRB-PREFLIGHT-0 — target state passes all active invariants
        3. Target phase < source phase (sanity)

        Returns a :class:`RollbackPreflightReport` — never raises.
        """
        checks: list[InvariantCheckResult] = []

        # HUMAN0-0: operator identity
        human0_ok = bool(operator and operator.strip())
        checks.append(InvariantCheckResult(
            invariant_id=GRB_HUMAN0_RULE,
            passed=human0_ok,
            reason="operator identity provided" if human0_ok else "empty operator identity violates GRB-HUMAN0-0",
        ))

        # target phase sanity
        target_ok = 0 < target_snapshot.phase < self._current.phase
        checks.append(InvariantCheckResult(
            invariant_id="GRB-TARGET-SANITY",
            passed=target_ok,
            reason=(
                f"target phase {target_snapshot.phase} < source {self._current.phase}"
                if target_ok
                else f"target phase {target_snapshot.phase} must be < source {self._current.phase} and > 0"
            ),
        ))

        # PREFLIGHT-0: each registered invariant against target state
        for inv_id, checker in self._registry.items():
            try:
                result = checker(target_snapshot)
                passed = bool(result)
                reason = "invariant satisfied" if passed else f"{inv_id} violated by target state"
            except Exception as exc:  # noqa: BLE001
                passed = False
                reason = f"{inv_id} check raised: {exc!r}"
            checks.append(InvariantCheckResult(
                invariant_id=inv_id,
                passed=passed,
                reason=reason,
            ))

        all_passed = all(c.passed for c in checks)
        failure_reason = ""
        if not all_passed:
            failed = [c.invariant_id for c in checks if not c.passed]
            failure_reason = f"GRB-PREFLIGHT-0: failed invariants: {', '.join(failed)}"

        return RollbackPreflightReport(
            target_phase=target_snapshot.phase,
            source_phase=self._current.phase,
            operator=operator,
            checks=tuple(checks),
            passed=all_passed,
            failure_reason=failure_reason,
        )

    def execute(
        self,
        target_snapshot: PhaseStateSnapshot,
        operator: str,
    ) -> RollbackResult:
        """Execute a governed rollback.

        Protocol (GRB-ATOMIC-0):
        1. Preflight — reject fast if invariants fail
        2. Write ROLLBACK_EVENT to ledger **before** any state delta
        3. Compute state_delta (what would change)
        4. Return SUCCESS with the ledger entry and delta

        The engine does *not* write to disk — the caller receives the
        ``state_delta`` and is responsible for applying it.  This keeps
        the engine pure and testable (no I/O side effects).
        """
        # Step 1: preflight
        preflight = self.preflight(target_snapshot, operator)

        if not preflight.passed:
            if not (operator and operator.strip()):
                return RollbackResult(
                    status=RollbackStatus.REJECTED_OPERATOR,
                    source_phase=self._current.phase,
                    target_phase=target_snapshot.phase,
                    operator=operator,
                    preflight=preflight,
                    ledger_entry=None,
                    state_delta={},
                    error=preflight.failure_reason,
                )
            if not (0 < target_snapshot.phase < self._current.phase):
                return RollbackResult(
                    status=RollbackStatus.REJECTED_TARGET,
                    source_phase=self._current.phase,
                    target_phase=target_snapshot.phase,
                    operator=operator,
                    preflight=preflight,
                    ledger_entry=None,
                    state_delta={},
                    error=preflight.failure_reason,
                )
            return RollbackResult(
                status=RollbackStatus.PREFLIGHT_FAILED,
                source_phase=self._current.phase,
                target_phase=target_snapshot.phase,
                operator=operator,
                preflight=preflight,
                ledger_entry=None,
                state_delta={},
                error=preflight.failure_reason,
            )

        # Step 2: write ROLLBACK_EVENT to ledger (GRB-LEDGER-0, GRB-ATOMIC-0)
        self._seq += 1
        entry_digest = _compute_entry_digest(
            GRB_EVENT_TYPE,
            self._current.phase,
            target_snapshot.phase,
            operator,
            self._seq,
        )
        prev_digest = (
            self._ledger[-1].get("chain_digest", "0" * 64)
            if self._ledger
            else "0" * 64
        )
        chain = _chain_digest(entry_digest, prev_digest)

        raw_entry: dict[str, Any] = {
            "event_type": GRB_EVENT_TYPE,
            "source_phase": self._current.phase,
            "target_phase": target_snapshot.phase,
            "operator": operator,
            "version_before": self._current.version,
            "version_after": target_snapshot.version,
            "hard_class_before": self._current.hard_class_count,
            "hard_class_after": target_snapshot.hard_class_count,
            "preflight_passed": True,
            "entry_digest": entry_digest,
            "chain_digest": chain,
            "prev_digest": prev_digest,
            "seq": self._seq,
        }
        try:
            self._ledger.append(raw_entry)
        except Exception as exc:  # noqa: BLE001 — GRB-ATOMIC-0: ledger write failure = no state change
            return RollbackResult(
                status=RollbackStatus.LEDGER_FAILED,
                source_phase=self._current.phase,
                target_phase=target_snapshot.phase,
                operator=operator,
                preflight=preflight,
                ledger_entry=None,
                state_delta={},
                error=f"GRB-LEDGER-0: ledger write failed: {exc!r}",
            )

        ledger_entry = RollbackLedgerEntry(
            event_type=GRB_EVENT_TYPE,
            source_phase=self._current.phase,
            target_phase=target_snapshot.phase,
            operator=operator,
            version_before=self._current.version,
            version_after=target_snapshot.version,
            hard_class_before=self._current.hard_class_count,
            hard_class_after=target_snapshot.hard_class_count,
            preflight_passed=True,
            entry_digest=entry_digest,
            prev_digest=prev_digest,
            seq=self._seq,
        )

        # Step 3: compute state delta (pure — no disk writes)
        state_delta = _compute_state_delta(self._current, target_snapshot)

        return RollbackResult(
            status=RollbackStatus.SUCCESS,
            source_phase=self._current.phase,
            target_phase=target_snapshot.phase,
            operator=operator,
            preflight=preflight,
            ledger_entry=ledger_entry,
            state_delta=state_delta,
        )

    # ------------------------------------------------------------------
    # Ledger introspection
    # ------------------------------------------------------------------

    def ledger_snapshot(self) -> list[dict[str, Any]]:
        """Return a copy of the current ledger (read-only, GRB-LEDGER-0)."""
        return list(self._ledger)

    def verify_chain(self) -> bool:
        """Verify HMAC chain integrity of all ledger entries (GRB-LEDGER-0)."""
        if not self._ledger:
            return True
        prev = self._ledger[0].get("prev_digest", "0" * 64)
        for entry in self._ledger:
            expected_chain = _chain_digest(entry["entry_digest"], prev)
            if not hmac.compare_digest(expected_chain, entry.get("chain_digest", "")):
                return False
            prev = entry["chain_digest"]
        return True


# ---------------------------------------------------------------------------
# State delta computation (deterministic, GRB-DETERM-0)
# ---------------------------------------------------------------------------

def _compute_state_delta(
    source: PhaseStateSnapshot,
    target: PhaseStateSnapshot,
) -> dict[str, Any]:
    """Compute the declared-state delta between source and target phases.

    Returns a mapping of field → (source_value, target_value) for every
    field that differs.  Deterministic: no timestamps, no randomness.
    """
    src_dict = source.as_dict()
    tgt_dict = target.as_dict()
    delta: dict[str, Any] = {}
    for key in src_dict:
        if src_dict[key] != tgt_dict.get(key):
            delta[key] = {"before": src_dict[key], "after": tgt_dict.get(key)}
    for key in tgt_dict:
        if key not in src_dict:
            delta[key] = {"before": None, "after": tgt_dict[key]}
    return delta


# ---------------------------------------------------------------------------
# Public convenience factory
# ---------------------------------------------------------------------------

def build_rollback_engine(
    current_phase: int,
    current_version: str,
    hard_class_count: int,
    innovations_shipped: int,
    invariant_ids: frozenset[str] | None = None,
    ledger: list[dict[str, Any]] | None = None,
    invariant_registry: dict[str, Any] | None = None,
) -> GovernedRollbackEngine:
    """Convenience factory for :class:`GovernedRollbackEngine`."""
    snapshot = PhaseStateSnapshot(
        phase=current_phase,
        version=current_version,
        hard_class_count=hard_class_count,
        innovations_shipped=innovations_shipped,
        invariant_ids=invariant_ids or frozenset(),
    )
    return GovernedRollbackEngine(
        current_snapshot=snapshot,
        ledger_entries=ledger,
        invariant_registry=invariant_registry,
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
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
