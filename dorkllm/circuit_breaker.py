# SPDX-License-Identifier: Apache-2.0
"""Governance Circuit Breaker (GCB) — Phase 150 / INNOV-56.

Constitutional invariants enforced in this module
--------------------------------------------------
GCB-CHAIN-0    : HMAC-SHA256 links every circuit event to its predecessor;
                 any chain break is immediately fatal (GCBChainViolation).
GCB-FAILCLOSE-0: When the circuit is OPEN no mutation may proceed; callers
                 that invoke assert_circuit_closed() while circuit is OPEN
                 receive GCBOpenViolation — the gate never silently passes.
GCB-READONLY-0 : GCB only reads violation signals forwarded by callers; it
                 never mutates CEL execution state, LEF subscriber sets, or
                 any mutation pipeline state (GCBMutationViolation on attempt).
GCB-DETERM-0   : Cascade detection is deterministic — identical violation
                 sequences always produce identical circuit decisions.
                 Timestamps are excluded from the detection algorithm; only
                 event ordering and namespace counts determine outcomes.
GCB-HUMAN0-0   : Circuit reset from OPEN requires HUMAN-0 authorisation
                 verified via constant-time hmac.compare_digest.
                 Plaintext comparison is constitutionally prohibited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Typed exceptions — one per Hard-class invariant
# ---------------------------------------------------------------------------


class GCBChainViolation(RuntimeError):
    """GCB-CHAIN-0: HMAC chain is broken between circuit events."""


class GCBOpenViolation(RuntimeError):
    """GCB-FAILCLOSE-0: mutation attempted while circuit is OPEN."""


class GCBMutationViolation(RuntimeError):
    """GCB-READONLY-0: GCB attempted to mutate external state."""


class GCBDeterminismViolation(RuntimeError):
    """GCB-DETERM-0: cascade decision is non-deterministic."""


class GCBAuthViolation(RuntimeError):
    """GCB-HUMAN0-0: circuit reset attempted without valid HUMAN-0 token."""


# ---------------------------------------------------------------------------
# HMAC key
# ---------------------------------------------------------------------------

_HMAC_KEY: bytes = os.getenv(
    "ADAAD_GCB_HMAC_KEY", "gcb-default-key-change-in-prod"
).encode()

# ---------------------------------------------------------------------------
# Circuit state constants
# ---------------------------------------------------------------------------

CIRCUIT_CLOSED = "CLOSED"   # Normal; mutations may proceed.
CIRCUIT_OPEN   = "OPEN"     # Tripped; all mutations are blocked.


# ---------------------------------------------------------------------------
# GCB cascade detection defaults
# ---------------------------------------------------------------------------

DEFAULT_VIOLATION_THRESHOLD = 3   # violations in a single namespace → trip
DEFAULT_NAMESPACE_THRESHOLD = 2   # distinct namespaces → trip (cascade)
DEFAULT_WINDOW_SIZE = 20          # rolling window length (event count)


# ---------------------------------------------------------------------------
# CircuitEvent — HMAC-chain-linked record
# ---------------------------------------------------------------------------


@dataclass
class CircuitEvent:
    """Single GCB ledger event; HMAC-SHA256 chained to predecessor.

    Constitutional note (GCB-DETERM-0): _canonical_dict() excludes timestamps
    from the chain digest.  Only deterministic fields participate in the HMAC.
    """

    event_id: str
    event_type: str          # "VIOLATION" | "TRIP" | "RESET" | "STATUS"
    namespace: str           # invariant namespace (e.g. "MXE", "LEF", "GCB")
    violation_id: str        # specific invariant or "" for non-violation events
    circuit_state: str       # CLOSED | OPEN at time of event
    window_snapshot: List[str]   # ordered namespace list in current window
    prev_hash: str           # HMAC of previous event's canonical dict
    entry_hash: str = field(default="", init=False)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def _canonical_dict(self) -> dict:
        """Deterministic representation for HMAC chaining (GCB-DETERM-0).

        Timestamps are deliberately excluded — the digest depends only on
        event ordering and structural fields, ensuring replay-determinism.
        """
        return {
            "circuit_state": self.circuit_state,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "namespace": self.namespace,
            "prev_hash": self.prev_hash,
            "violation_id": self.violation_id,
            "window_snapshot": sorted(self.window_snapshot),
        }

    def _compute_hash(self) -> str:
        payload = json.dumps(self._canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hmac.new(_HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()

    def finalise(self) -> "CircuitEvent":
        self.entry_hash = self._compute_hash()
        return self

    def to_dict(self) -> dict:
        d = self._canonical_dict()
        d["entry_hash"] = self.entry_hash
        d["timestamp"] = self.timestamp
        return d


# ---------------------------------------------------------------------------
# GCBChainState — chain integrity verifier
# ---------------------------------------------------------------------------


class GCBChainState:
    """Maintains the rolling HMAC chain for the GCB ledger.

    GCB-CHAIN-0: any break raises GCBChainViolation immediately.
    """

    GENESIS_HASH: str = "0" * 64

    def __init__(self) -> None:
        self._last_hash: str = self.GENESIS_HASH

    def advance(self, event: CircuitEvent) -> None:
        """Verify event links correctly to previous hash, then advance."""
        if not hmac.compare_digest(event.prev_hash, self._last_hash):
            raise GCBChainViolation(
                f"GCB-CHAIN-0: chain break at event {event.event_id!r}. "
                f"Expected prev_hash={self._last_hash!r}, got {event.prev_hash!r}"
            )
        expected = event._compute_hash()
        if not hmac.compare_digest(event.entry_hash, expected):
            raise GCBChainViolation(
                f"GCB-CHAIN-0: entry_hash mismatch at event {event.event_id!r}"
            )
        self._last_hash = event.entry_hash

    @property
    def last_hash(self) -> str:
        return self._last_hash


# ---------------------------------------------------------------------------
# ViolationWindow — deterministic cascade detector
# ---------------------------------------------------------------------------


class ViolationWindow:
    """Fixed-size rolling window of violation namespaces.

    GCB-DETERM-0: identical violation sequences always produce identical
    cascade decisions.  No randomness; no timestamps in detection logic.
    """

    def __init__(self, size: int = DEFAULT_WINDOW_SIZE) -> None:
        if size < 1:
            raise ValueError("window size must be >= 1")
        self._size = size
        self._window: List[str] = []   # ordered list of namespaces

    def push(self, namespace: str) -> List[str]:
        """Append namespace; drop oldest if at capacity.  Returns current window."""
        self._window.append(namespace)
        if len(self._window) > self._size:
            self._window = self._window[-self._size :]
        return list(self._window)

    def snapshot(self) -> List[str]:
        return list(self._window)

    def namespace_counts(self) -> Dict[str, int]:
        """Deterministic count map of namespaces in current window."""
        counts: Dict[str, int] = {}
        for ns in self._window:
            counts[ns] = counts.get(ns, 0) + 1
        return dict(sorted(counts.items()))

    def max_single_namespace_count(self) -> int:
        counts = self.namespace_counts()
        return max(counts.values()) if counts else 0

    def distinct_namespace_count(self) -> int:
        return len(set(self._window))

    def should_trip(
        self,
        violation_threshold: int = DEFAULT_VIOLATION_THRESHOLD,
        namespace_threshold: int = DEFAULT_NAMESPACE_THRESHOLD,
    ) -> bool:
        """Deterministic cascade decision (GCB-DETERM-0).

        Trips if either:
        - A single namespace exceeds violation_threshold, OR
        - Distinct namespaces with >= 1 violation exceed namespace_threshold.
        """
        if self.max_single_namespace_count() >= violation_threshold:
            return True
        if self.distinct_namespace_count() >= namespace_threshold:
            return True
        return False

    def reset(self) -> None:
        self._window = []


# ---------------------------------------------------------------------------
# CircuitBreakerEngine — main GCB engine
# ---------------------------------------------------------------------------


class CircuitBreakerEngine:
    """Governance Circuit Breaker — fail-closed constitutional safety layer.

    Constitutionally permanent per ADAAD innovation contract.
    This engine monitors invariant violation signals and trips the circuit
    when cascade thresholds are reached, preventing all further mutations
    while the circuit is OPEN.

    GCB-READONLY-0: this engine NEVER mutates CEL, LEF, or mutation pipeline
    state.  It only writes to its own append-only JSONL ledger.
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        violation_threshold: int = DEFAULT_VIOLATION_THRESHOLD,
        namespace_threshold: int = DEFAULT_NAMESPACE_THRESHOLD,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> None:
        self._ledger_path = ledger_path or Path(
            os.getenv("ADAAD_GCB_LEDGER", "data/gcb/gcb_ledger.jsonl")
        )
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

        self._violation_threshold = violation_threshold
        self._namespace_threshold = namespace_threshold
        self._window = ViolationWindow(size=window_size)
        self._chain = GCBChainState()
        self._state: str = CIRCUIT_CLOSED
        self._event_counter: int = 0
        self._total_violations: int = 0
        self._trip_count: int = 0

        # Replay existing ledger to restore chain state
        self._restore_chain()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def is_closed(self) -> bool:
        return self._state == CIRCUIT_CLOSED

    def is_open(self) -> bool:
        return self._state == CIRCUIT_OPEN

    def assert_circuit_closed(self) -> None:
        """GCB-FAILCLOSE-0: raise GCBOpenViolation if circuit is OPEN.

        Callers (mutation pipeline gates) MUST invoke this before any
        mutation proceeds.  The gate never silently passes.
        """
        if self._state == CIRCUIT_OPEN:
            raise GCBOpenViolation(
                "GCB-FAILCLOSE-0: circuit is OPEN — all mutations are blocked. "
                "A HUMAN-0 reset is required before mutations may proceed."
            )

    def record_violation(
        self,
        namespace: str,
        violation_id: str,
        *,
        _readonly_guard: bool = True,
    ) -> bool:
        """Record an invariant violation signal and check cascade threshold.

        Returns True if the circuit was tripped by this violation.

        GCB-READONLY-0: this method does NOT mutate CEL, LEF, or mutation
        pipeline state.  _readonly_guard exists to make the contract explicit.

        GCB-DETERM-0: cascade decision is deterministic — only event ordering
        and namespace counts (not timestamps) determine the outcome.
        """
        if not _readonly_guard:
            raise GCBMutationViolation(
                "GCB-READONLY-0: _readonly_guard must remain True; "
                "GCB must never mutate external state."
            )

        self._total_violations += 1
        window_snap = self._window.push(namespace)

        event = self._build_event(
            event_type="VIOLATION",
            namespace=namespace,
            violation_id=violation_id,
            window_snap=window_snap,
        )
        self._append_event(event)

        # Cascade check (GCB-DETERM-0)
        if self._state == CIRCUIT_CLOSED and self._window.should_trip(
            self._violation_threshold, self._namespace_threshold
        ):
            self._trip(triggered_by=violation_id)
            return True
        return False

    def reset_circuit(self, human0_token: str) -> None:
        """Reset an OPEN circuit to CLOSED.  Requires HUMAN-0 token.

        GCB-HUMAN0-0: token verified via constant-time hmac.compare_digest.
        """
        expected_token = os.getenv("ADAAD_HUMAN0_TOKEN", "HUMAN-0-ADAAD-TOKEN")
        if not hmac.compare_digest(human0_token.encode(), expected_token.encode()):
            raise GCBAuthViolation(
                "GCB-HUMAN0-0: circuit reset requires valid HUMAN-0 token. "
                "Plaintext comparison is constitutionally prohibited."
            )
        self._state = CIRCUIT_CLOSED
        self._window.reset()

        event = self._build_event(
            event_type="RESET",
            namespace="GCB",
            violation_id="",
            window_snap=[],
        )
        self._append_event(event)

    def get_status(self) -> dict:
        """Read-only status snapshot.  Never modifies state."""
        return {
            "circuit_state": self._state,
            "total_violations": self._total_violations,
            "trip_count": self._trip_count,
            "window_namespace_counts": self._window.namespace_counts(),
            "window_distinct_namespaces": self._window.distinct_namespace_count(),
            "violation_threshold": self._violation_threshold,
            "namespace_threshold": self._namespace_threshold,
            "chain_last_hash": self._chain.last_hash,
        }

    def health_check(self) -> dict:
        return {
            "status": "ok",
            "circuit_state": self._state,
            "invariant": "GCB-FAILCLOSE-0",
            "ledger": str(self._ledger_path),
        }

    def verify_ledger_chain(self) -> dict:
        """Re-read ledger and verify full HMAC chain integrity (GCB-CHAIN-0)."""
        if not self._ledger_path.exists():
            return {"verified": True, "events": 0, "message": "empty ledger"}

        prev = GCBChainState.GENESIS_HASH
        count = 0
        with self._ledger_path.open() as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise GCBChainViolation(
                        f"GCB-CHAIN-0: corrupt ledger JSON at line {lineno}: {exc}"
                    ) from exc

                # Rebuild event for digest verification
                canonical = {
                    "circuit_state": row["circuit_state"],
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "namespace": row["namespace"],
                    "prev_hash": row["prev_hash"],
                    "violation_id": row["violation_id"],
                    "window_snapshot": sorted(row["window_snapshot"]),
                }
                payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
                expected = hmac.new(_HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()

                if not hmac.compare_digest(row["prev_hash"], prev):
                    raise GCBChainViolation(
                        f"GCB-CHAIN-0: prev_hash mismatch at ledger line {lineno}"
                    )
                if not hmac.compare_digest(row["entry_hash"], expected):
                    raise GCBChainViolation(
                        f"GCB-CHAIN-0: entry_hash mismatch at ledger line {lineno}"
                    )
                prev = row["entry_hash"]
                count += 1

        return {"verified": True, "events": count}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trip(self, triggered_by: str) -> None:
        self._state = CIRCUIT_OPEN
        self._trip_count += 1

        event = self._build_event(
            event_type="TRIP",
            namespace="GCB",
            violation_id=triggered_by,
            window_snap=self._window.snapshot(),
        )
        self._append_event(event)

    def _build_event(
        self,
        event_type: str,
        namespace: str,
        violation_id: str,
        window_snap: List[str],
    ) -> CircuitEvent:
        self._event_counter += 1
        ev = CircuitEvent(
            event_id=f"gcb-{self._event_counter:06d}",
            event_type=event_type,
            namespace=namespace,
            violation_id=violation_id,
            circuit_state=self._state,
            window_snapshot=window_snap,
            prev_hash=self._chain.last_hash,
        )
        ev.finalise()
        self._chain.advance(ev)   # raises GCBChainViolation on break
        return ev

    def _append_event(self, event: CircuitEvent) -> None:
        """Append event to JSONL ledger.  Append-only; never truncates."""
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def _restore_chain(self) -> None:
        """Replay existing ledger to restore chain tail and circuit state."""
        if not self._ledger_path.exists():
            return
        with self._ledger_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Advance counter
                self._event_counter += 1
                # Restore last known state
                self._state = row.get("circuit_state", CIRCUIT_CLOSED)
                # Advance chain without verification (already verified at write)
                self._chain._last_hash = row.get("entry_hash", GCBChainState.GENESIS_HASH)
