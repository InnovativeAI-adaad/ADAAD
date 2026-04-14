# SPDX-License-Identifier: Apache-2.0
"""Innovation #22 — Market-Conditioned Fitness.
Real external signals feed into fitness scoring.
"""
from __future__ import annotations
import json, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
MAFI_INV_CHAIN: str = "MAFI-INV-CHAIN"
MAFI_LEDGER_DEFAULT: str = "data/market_fitness_events.jsonl"


class MarketFitnessViolation(RuntimeError):
    """Raised when a Market Fitness constitutional invariant is breached."""



@dataclass
class ExternalSignal:
    signal_id: str
    source: str          # "github_stars" | "benchmark_rank" | "api_latency"
    value: float         # normalized 0–1
    direction: float     # -1 (worsening), 0 (stable), +1 (improving)
    timestamp: float
    weight: float = 0.10


class MarketConditionedFitness:
    """Anchors fitness to external market validation signals."""

    def __init__(self, signals_path: Path = Path("data/market_signals.jsonl"),
                 signal_weight: float = 0.10):
        self.signals_path = Path(signals_path)
        self.signal_weight = signal_weight
        self._signals: dict[str, ExternalSignal] = {}
        self._load()

    def register_signal(self, signal: ExternalSignal) -> None:
        self._signals[signal.signal_id] = signal
        self._persist(signal)

    def adjust_fitness(self, base_fitness: float, mutation_id: str) -> float:
        """Adjust fitness score based on recent market signal directions."""
        if not self._signals:
            return base_fitness
        recent = [s for s in self._signals.values()
                   if time.time() - s.timestamp < 86400 * 7]  # 7 days
        if not recent:
            return base_fitness
        avg_direction = sum(s.direction * s.weight for s in recent) / len(recent)
        # Positive market signals boost fitness slightly; negative penalize
        adjustment = avg_direction * self.signal_weight
        return max(0.0, min(1.0, base_fitness + adjustment))

    def market_health_score(self) -> float:
        if not self._signals:
            return 1.0
        values = [s.value for s in self._signals.values()]
        return round(sum(values) / len(values), 4)

    # ── MARKET-HALT-0: Halt invariant ─────────────────────────────────────
    # Invariant: synthetic market fitness fallback must be bounded.
    # If fewer than MIN_SIGNALS active signals are present, the market
    # fitness layer becomes unconstrained — every mutation gets the same
    # neutral score, defeating anti-drift protection.  When this condition
    # is detected, mutations are blocked until real signals are registered.
    # [MARKET-HALT-0] fail-closed: no signals → block, not allow.

    MIN_SIGNALS: int = 1   # constitutional minimum; raise to 3+ in production

    def halt_if_unconstrained(self) -> tuple[bool, str]:
        """Check MARKET-HALT-0: insufficient signals = halt (fail-closed).

        Returns:
            (should_halt: bool, reason: str)
            should_halt=True means mutations must be blocked until signals
            are registered.  Callers must treat this as blocking, not advisory.
        """
        active = [
            s for s in self._signals.values()
            if time.time() - s.timestamp < 86400 * 7  # 7-day active window
        ]
        if len(active) < self.MIN_SIGNALS:
            reason = (
                f"[MARKET-HALT-0] Insufficient market signals: "
                f"{len(active)} active (minimum: {self.MIN_SIGNALS}). "
                f"Market fitness is unconstrained. Mutations halted until "
                f"at least {self.MIN_SIGNALS} signal(s) are registered via "
                f"register_signal(). This is a fail-closed constitutional gate."
            )
            return True, reason
        return False, "ok"

    def signal_summary(self) -> dict:
        """Return structured summary of current signal state."""
        active = [
            s for s in self._signals.values()
            if time.time() - s.timestamp < 86400 * 7
        ]
        stale = [
            s for s in self._signals.values()
            if time.time() - s.timestamp >= 86400 * 7
        ]
        improving = sum(1 for s in active if s.direction > 0)
        degrading  = sum(1 for s in active if s.direction < 0)
        stable     = sum(1 for s in active if s.direction == 0)
        should_halt, halt_reason = self.halt_if_unconstrained()

        return {
            "total_registered": len(self._signals),
            "active_7d": len(active),
            "stale": len(stale),
            "improving": improving,
            "degrading": degrading,
            "stable": stable,
            "market_health_score": self.market_health_score(),
            "halt_invariant_triggered": should_halt,
            "halt_reason": halt_reason if should_halt else None,
            "min_signals_required": self.MIN_SIGNALS,
        }

    def direction_trend(self, window_days: int = 7) -> str:
        """Overall market direction: 'improving' | 'degrading' | 'stable'."""
        cutoff = time.time() - 86400 * window_days
        recent = [s for s in self._signals.values() if s.timestamp >= cutoff]
        if not recent:
            return "stable"
        avg = sum(s.direction * s.weight for s in recent) / len(recent)
        if avg > 0.05:
            return "improving"
        if avg < -0.05:
            return "degrading"
        return "stable"

    def _load(self) -> None:
        if not self.signals_path.exists():
            return
        for line in self.signals_path.read_text().splitlines():
            try:
                d = json.loads(line)
                s = ExternalSignal(**d)
                self._signals[s.signal_id] = s
            except Exception:
                pass

    def _persist(self, signal: ExternalSignal) -> None:
        import dataclasses

        self.signals_path.parent.mkdir(parents=True, exist_ok=True)
        with self.signals_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(signal)) + "\n")


# ── Chain-linkage scaffold (hardening pass — prev_digest + _append_event) ─────
import hashlib as _hashlib
import json as _json


_MODULE_PREV_DIGEST: str = "genesis"   # prev_digest chain head for this module


def _append_event(event: dict, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT, CED-INV-CHAIN].

    Writes a chain-linked record to ledger_path (or discards if empty).
    Full integration deferred to per-module deep-dive phase.
    """
    global _MODULE_PREV_DIGEST
    if not ledger_path:
        return
    import dataclasses as _dc
    from pathlib import Path as _Path
    row = event if isinstance(event, dict) else (
        _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else {}
    )
    row["prev_digest"] = _MODULE_PREV_DIGEST
    digest_payload = _json.dumps(row, sort_keys=True).encode()
    row["event_digest"] = "sha256:" + _hashlib.sha256(digest_payload).hexdigest()
    p = _Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_json.dumps(row, sort_keys=True) + "\n")
    _MODULE_PREV_DIGEST = row["event_digest"]


__all__ = [
    "MarketConditionedFitness",
    "ExternalSignal",
    # Invariant codes surfaced as module-level constants for CI assertion
    # MARKET-HALT-0 is enforced via MarketConditionedFitness.halt_if_unconstrained()
]
