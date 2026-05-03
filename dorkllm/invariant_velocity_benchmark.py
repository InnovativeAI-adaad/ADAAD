# SPDX-License-Identifier: Apache-2.0
"""Phase 167 · INNOV-73 · Invariant Velocity Benchmark (IVB).

Tracks the rate of Hard-class invariant accumulation across phases and
forecasts the phase count required to reach V10_MIN_INVARIANTS (350).
Produces HMAC-chained, deterministic VelocitySnapshots that feed directly
into the INVARIANT_DENSITY convergence criterion assessment.

Key capabilities
----------------
* record()          — record a phase invariant count; produce VelocitySnapshot
* forecast()        — forecast phases needed to reach target density
* velocity()        — return rolling average invariants-per-phase
* history()         — return full HMAC-chained snapshot ledger
* verify_chain()    — verify chain integrity

Constitutional invariants enforced
------------------------------------
IVB-DETERM-0   record() is a pure function of its inputs; wall-clock time
               and randomness never influence VelocitySnapshot value fields.
IVB-CHAIN-0    Every VelocitySnapshot is HMAC-chained to its predecessor;
               tampered or missing links raise IVBChainError.
IVB-HUMAN0-0   If forecasted_phases_to_target > IVB_HUMAN0_THRESHOLD, a
               HUMAN-0 review flag is set in the snapshot; no auto-extension
               of the V10 deadline is permitted without ratification.
IVB-WINDOW-0   Rolling velocity is computed over exactly IVB_WINDOW_SIZE
               recent snapshots; window size cannot be altered at runtime.
IVB-PERSIST-0  Every record() call appends one VelocitySnapshot to the
               append-only JSONL ledger before returning.
IVB-ATOMIC-0   Ledger writes use tmp-file + rename for crash safety.
IVB-AUDIT-0    Ledger entries are never modified or deleted after write.
IVB-FLOOR-0    invariant_count must be >= prev_invariant_count; regression
               raises IVBRegressionError and is never silently tolerated.
IVB-BOUND-0    velocity() always returns a non-negative float; division by
               zero is guarded by returning 0.0 on empty history.
IVB-SCOPE-0    forecast() computes exclusively from the IVB rolling window;
               no external data source may influence the forecast result.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GOVERNOR: str = "DUSTIN L REID"
CHAIN_ROOT: str = "0" * 64
HMAC_KEY: bytes = b"ivb-chain-key-v1"

IVB_WINDOW_SIZE: int = 5          # rolling velocity window (IVB-WINDOW-0)
IVB_HUMAN0_THRESHOLD: int = 10    # phases remaining → HUMAN-0 alert
V10_MIN_INVARIANTS: int = 350
IVB_VERSION: str = "1.0"

LEDGER_PATH: Path = Path("ledger/invariant_velocity.jsonl")
LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class IVBChainError(RuntimeError):
    """Raised when the snapshot chain is broken or tampered."""


class IVBRegressionError(RuntimeError):
    """Raised when a new invariant_count is lower than the previous. IVB-FLOOR-0."""


class IVBHuman0Flag(RuntimeError):
    """Raised when forecasted phases to target exceed IVB_HUMAN0_THRESHOLD."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VelocitySnapshot:
    snapshot_id: str
    phase: int
    invariant_count: int
    delta: int
    rolling_velocity: float
    forecasted_phases_to_target: Optional[int]
    target_reachable: bool
    human0_review_required: bool
    prev_digest: str
    chain_digest: str
    governor: str = GOVERNOR


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
class InvariantVelocityBenchmark:
    """Tracks invariant accumulation velocity toward V10_MIN_INVARIANTS.

    IVB-DETERM-0 / IVB-CHAIN-0 / IVB-WINDOW-0
    """

    def __init__(
        self,
        ledger_path: Path = LEDGER_PATH,
        target: int = V10_MIN_INVARIANTS,
    ) -> None:
        self._ledger_path = ledger_path
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._target = target
        self._prev_digest: str = self._load_prev_digest()
        self._last_count: Optional[int] = self._load_last_count()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, phase: int, invariant_count: int) -> VelocitySnapshot:
        """Record a phase checkpoint and produce a VelocitySnapshot.

        IVB-DETERM-0 / IVB-FLOOR-0 / IVB-PERSIST-0
        """
        # IVB-FLOOR-0: reject regressions
        if self._last_count is not None and invariant_count < self._last_count:
            raise IVBRegressionError(
                f"invariant_count={invariant_count} < prev={self._last_count}: "
                "Hard-class invariant regression is a constitutional violation."
            )

        delta = invariant_count - (self._last_count or invariant_count)
        history = self.history()

        # rolling window velocity (IVB-WINDOW-0)
        window = history[-IVB_WINDOW_SIZE:] if history else []
        if window:
            total_delta = sum(r.get("delta", 0) for r in window) + delta
            rolling_velocity = round(total_delta / (len(window) + 1), 6)
        else:
            rolling_velocity = float(delta)

        # forecast (IVB-SCOPE-0 / IVB-BOUND-0)
        remaining = max(0, self._target - invariant_count)
        if remaining == 0:
            forecasted_phases = 0
            reachable = True
        elif rolling_velocity > 0:
            forecasted_phases = int(remaining / rolling_velocity) + 1
            reachable = True
        else:
            forecasted_phases = None
            reachable = False

        human0_required = (
            forecasted_phases is not None
            and forecasted_phases > IVB_HUMAN0_THRESHOLD
            and remaining > 0
        )

        epoch_id = self._deterministic_epoch(phase, invariant_count)
        snap_id = f"IVB-{epoch_id[:12]}"
        prev = self._prev_digest
        chain_digest = self._chain_digest(snap_id, epoch_id, rolling_velocity, prev)

        snapshot = VelocitySnapshot(
            snapshot_id=snap_id,
            phase=phase,
            invariant_count=invariant_count,
            delta=delta,
            rolling_velocity=rolling_velocity,
            forecasted_phases_to_target=forecasted_phases,
            target_reachable=reachable,
            human0_review_required=human0_required,
            prev_digest=prev,
            chain_digest=chain_digest,
        )

        # IVB-PERSIST-0 / IVB-ATOMIC-0
        self._append_ledger(snapshot)
        self._prev_digest = chain_digest
        self._last_count = invariant_count

        # IVB-HUMAN0-0
        if human0_required:
            raise IVBHuman0Flag(
                f"forecasted_phases_to_target={forecasted_phases} > "
                f"{IVB_HUMAN0_THRESHOLD}: HUMAN-0 review required."
            )

        return snapshot

    def velocity(self) -> float:
        """Return rolling average invariants-per-phase.  IVB-BOUND-0."""
        history = self.history()
        if not history:
            return 0.0
        window = history[-IVB_WINDOW_SIZE:]
        if not window:
            return 0.0
        return round(sum(r.get("delta", 0) for r in window) / len(window), 6)

    def forecast(self, current_count: int) -> Optional[int]:
        """Forecast phases needed to reach target.  IVB-SCOPE-0."""
        remaining = max(0, self._target - current_count)
        if remaining == 0:
            return 0
        v = self.velocity()
        if v <= 0:
            return None
        return int(remaining / v) + 1

    def history(self) -> List[Dict[str, Any]]:
        """Return full ledger.  IVB-AUDIT-0."""
        if not self._ledger_path.exists():
            return []
        records = []
        with self._ledger_path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def verify_chain(self) -> bool:
        """Verify HMAC chain integrity.  IVB-CHAIN-0."""
        records = self.history()
        prev = CHAIN_ROOT
        for rec in records:
            expected = self._chain_digest(
                rec["snapshot_id"], rec["epoch_id"],
                rec["rolling_velocity"], prev
            )
            if not hmac.compare_digest(rec["chain_digest"][:24], expected[:24]):
                raise IVBChainError(
                    f"Chain broken at snapshot_id={rec['snapshot_id']}"
                )
            prev = rec["chain_digest"]
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _deterministic_epoch(self, phase: int, count: int) -> str:
        payload = json.dumps({"phase": phase, "count": count}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _chain_digest(
        self, snap_id: str, epoch_id: str, velocity: float, prev: str
    ) -> str:
        payload = json.dumps(
            {"snap_id": snap_id, "epoch_id": epoch_id,
             "velocity": velocity, "prev": prev},
            sort_keys=True,
        )
        return hmac.new(HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()

    def _load_prev_digest(self) -> str:
        if not self._ledger_path.exists():
            return CHAIN_ROOT
        last = None
        with self._ledger_path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)
        return last["chain_digest"] if last else CHAIN_ROOT

    def _load_last_count(self) -> Optional[int]:
        if not self._ledger_path.exists():
            return None
        last = None
        with self._ledger_path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)
        return last["invariant_count"] if last else None

    def _append_ledger(self, snap: VelocitySnapshot) -> None:
        """Atomic append.  IVB-ATOMIC-0 / IVB-PERSIST-0."""
        tmp = self._ledger_path.with_suffix(".jsonl.tmp")
        record = {
            "snapshot_id": snap.snapshot_id,
            "epoch_id": self._deterministic_epoch(snap.phase, snap.invariant_count),
            "phase": snap.phase,
            "invariant_count": snap.invariant_count,
            "delta": snap.delta,
            "rolling_velocity": snap.rolling_velocity,
            "forecasted_phases_to_target": snap.forecasted_phases_to_target,
            "target_reachable": snap.target_reachable,
            "human0_review_required": snap.human0_review_required,
            "prev_digest": snap.prev_digest,
            "chain_digest": snap.chain_digest,
        }
        existing = self._ledger_path.read_text() if self._ledger_path.exists() else ""
        tmp.write_text(existing + json.dumps(record) + "\n")
        tmp.rename(self._ledger_path)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_BENCHMARK: Optional[InvariantVelocityBenchmark] = None


def get_benchmark() -> InvariantVelocityBenchmark:
    global _BENCHMARK
    if _BENCHMARK is None:
        _BENCHMARK = InvariantVelocityBenchmark()
    return _BENCHMARK
