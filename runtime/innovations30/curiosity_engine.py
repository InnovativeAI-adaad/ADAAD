# SPDX-License-Identifier: Apache-2.0
"""Innovation #29 — Curiosity-Driven Exploration with Hard Stops (CURIOSITY).
Every 25 epochs: 3 epochs of inverted-fitness exploration.
Hard constitutional stops prevent catastrophic exploration.

Constitutional invariants:
    CURIOSITY-0       — invert_fitness() MUST return 1.0 - base_fitness when active;
                        base_fitness MUST be in [0.0, 1.0]
    CURIOSITY-STOP-0  — tick() MUST exit curiosity immediately when health < HARD_STOP_HEALTH
                        or when any proposed file matches HARD_STOP_PATTERNS
    CURIOSITY-AUDIT-0 — every state transition MUST append a reason to CuriosityState.discoveries
                        and persist state
    CED-INV-CHAIN     — each ledger entry carries prev_digest referencing the preceding digest;
                        chain verified via hmac.compare_digest — tamper detection on replay
    CED-INV-DETERM    — event_digest = sha256(event_type + epoch_id + repr(health_score) + prev_digest)
    CED-INV-AUDIT     — every CuriosityEvent is appended to append-only JSONL ledger via _append_event()
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Constitutional constants ─────────────────────────────────────────────────
CURIOSITY_INTERVAL: int = 25
CURIOSITY_DURATION: int = 3
HARD_STOP_HEALTH: float = 0.50

HARD_STOP_PATTERNS: frozenset[str] = frozenset([
    "runtime/governance/gate.py",
    "runtime/constitution.py",
    "security/ledger/journal.py",
    "HUMAN-0",
    "human_signoff",
])

# Invariant code constants — surfaced for CI assertion
CED_INV_CHAIN:  str = "CED-INV-CHAIN"
CED_INV_DETERM: str = "CED-INV-DETERM"
CED_INV_AUDIT:  str = "CED-INV-AUDIT"

CED_LEDGER_DEFAULT: str = "data/curiosity_events.jsonl"

CURIOSITY_INVARIANTS: dict[str, str] = {
    "CURIOSITY-0": (
        "invert_fitness() MUST return round(1.0 - base_fitness, 4) when active. "
        "base_fitness MUST be in [0.0, 1.0]; violation raises CuriosityViolation."
    ),
    "CURIOSITY-STOP-0": (
        "tick() MUST exit curiosity immediately when health_score < HARD_STOP_HEALTH "
        "or any proposed file matches HARD_STOP_PATTERNS. No exceptions."
    ),
    "CURIOSITY-AUDIT-0": (
        "Every state transition (enter, exit, tick) MUST append a reason to "
        "CuriosityState.discoveries and persist state to disk."
    ),
    CED_INV_CHAIN: (
        "Each CuriosityEvent ledger entry carries prev_digest referencing the preceding "
        "entry digest; chain verified via hmac.compare_digest."
    ),
    CED_INV_DETERM: (
        "event_digest = sha256(event_type + epoch_id + repr(health_score) + prev_digest); "
        "deterministic across all runtime environments."
    ),
    CED_INV_AUDIT: (
        "Every CuriosityEvent is appended to append-only JSONL ledger via _append_event(); "
        "no deletion or overwrite permitted."
    ),
}


# ── Typed gate violation exception ───────────────────────────────────────────
class CuriosityViolation(RuntimeError):
    """Raised when a Curiosity Engine constitutional invariant is breached."""


# ── Data models ──────────────────────────────────────────────────────────────
@dataclass
class CuriosityState:
    active: bool = False
    epochs_remaining: int = 0
    cycle_number: int = 0
    total_curiosity_epochs: int = 0
    discoveries: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.discoveries is None:
            self.discoveries = []


@dataclass
class CuriosityEvent:
    """Structured audit record per curiosity transition [CURIOSITY-AUDIT-0, CED-INV-CHAIN]."""
    event_type: str          # "enter" | "tick" | "hard_stop_health" | "hard_stop_file" | "cycle_complete"
    epoch_id: str
    cycle_number: int
    epochs_remaining: int
    health_score: float
    reason: str
    prev_digest: str = "genesis"    # CED-INV-CHAIN
    event_digest: str = ""          # CED-INV-DETERM
    timestamp_utc: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    innovation: str = "INNOV-29"
    phase: int = 114

    def __post_init__(self) -> None:
        if not self.event_digest:
            self.event_digest = self._compute_digest()

    def _compute_digest(self) -> str:
        """CED-INV-DETERM: deterministic digest over canonical fields."""
        payload = (
            f"{self.event_type}:{self.epoch_id}"
            f":{repr(self.health_score)}"
            f":{self.prev_digest}"
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def to_ledger_row(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True)


def curiosity_guard(state: CuriosityState, base_fitness: float | None = None) -> None:
    """Fail-closed enforcement for curiosity constitutional constraints [CURIOSITY-0].

    Raises CuriosityViolation on invariant violations.
    """
    if base_fitness is not None and not (0.0 <= base_fitness <= 1.0):
        raise CuriosityViolation(
            f"CURIOSITY-0: base_fitness={base_fitness} outside [0.0, 1.0]."
        )
    if state.epochs_remaining < 0:
        raise CuriosityViolation(
            f"CURIOSITY-0: epochs_remaining={state.epochs_remaining} is negative."
        )
    if state.active and state.epochs_remaining == 0:
        raise CuriosityViolation(
            "CURIOSITY-0: state.active=True but epochs_remaining=0 — "
            "inconsistent curiosity state."
        )


class CuriosityEngine:
    """Manages bounded curiosity-driven exploration cycles.

    Constitutional guarantees (Phase 114 + hardening):
        CURIOSITY-0       : invert_fitness validated; base_fitness bounds enforced
        CURIOSITY-STOP-0  : health/file hard stops enforced in tick()
        CURIOSITY-AUDIT-0 : all transitions logged to discoveries and persisted
        CED-INV-CHAIN     : HMAC-chained JSONL ledger via _append_event()
        CED-INV-DETERM    : deterministic sha256 event digests
        CED-INV-AUDIT     : append-only event ledger; no deletion permitted
    """

    def __init__(
        self,
        state_path: Path = Path("data/curiosity_state.json"),
        ledger_path: Path = Path(CED_LEDGER_DEFAULT),
        interval: int = CURIOSITY_INTERVAL,
        duration: int = CURIOSITY_DURATION,
    ) -> None:
        self.state_path = Path(state_path)
        self.ledger_path = Path(ledger_path)
        self.interval = interval
        self.duration = duration
        self._state = CuriosityState()
        self._last_digest: str = "genesis"
        self._load()

    def should_enter_curiosity(self, epoch_seq: int) -> bool:
        return (
            not self._state.active
            and epoch_seq > 0
            and epoch_seq % self.interval == 0
        )

    def enter_curiosity(self, epoch_id: str) -> CuriosityState:
        """Begin a curiosity cycle [CURIOSITY-AUDIT-0, CED-INV-CHAIN]."""
        self._state.active = True
        self._state.epochs_remaining = self.duration
        self._state.cycle_number += 1
        self._state.total_curiosity_epochs += self.duration
        self._state.discoveries.append(f"enter:cycle_{self._state.cycle_number}:{epoch_id}")
        event = CuriosityEvent(
            event_type="enter",
            epoch_id=epoch_id,
            cycle_number=self._state.cycle_number,
            epochs_remaining=self._state.epochs_remaining,
            health_score=1.0,
            reason=f"cycle_{self._state.cycle_number}_start",
            prev_digest=self._last_digest,
        )
        self._append_event(event)
        self._save()
        return self._state

    def tick(
        self,
        epoch_id: str,
        health_score: float,
        proposed_files: list[str],
    ) -> tuple[bool, str]:
        """Advance one epoch. Returns (still_in_curiosity, exit_reason).

        [CURIOSITY-STOP-0] — hard stops enforced before any other logic.
        [CURIOSITY-AUDIT-0] — every exit appends to discoveries.
        [CED-INV-CHAIN] — every tick appends a chain-linked event.
        """
        if not self._state.active:
            return False, ""

        # [CURIOSITY-STOP-0] health hard stop
        if health_score < HARD_STOP_HEALTH:
            reason = f"hard_stop_health:{health_score:.3f}<{HARD_STOP_HEALTH}"
            self._emit_event("hard_stop_health", epoch_id, health_score, reason)
            self._exit_curiosity(reason)
            return False, f"Curiosity hard stop: health {health_score:.3f} < {HARD_STOP_HEALTH}"

        # [CURIOSITY-STOP-0] protected file hard stop
        for f in proposed_files:
            if any(p in str(f) for p in HARD_STOP_PATTERNS):
                reason = f"hard_stop_file:{f}"
                self._emit_event("hard_stop_file", epoch_id, health_score, reason)
                self._exit_curiosity(reason)
                return False, f"Curiosity hard stop: proposal touches protected path {f}"

        self._state.epochs_remaining -= 1
        if self._state.epochs_remaining <= 0:
            self._emit_event("cycle_complete", epoch_id, health_score, "cycle_complete")
            self._exit_curiosity("cycle_complete")
            return False, "Curiosity cycle complete"

        self._state.discoveries.append(f"tick:epoch_{epoch_id}:remaining_{self._state.epochs_remaining}")
        self._emit_event("tick", epoch_id, health_score, f"remaining_{self._state.epochs_remaining}")
        self._save()
        return True, ""

    @property
    def in_curiosity(self) -> bool:
        return self._state.active

    def invert_fitness(self, base_fitness: float) -> float:
        """Invert fitness during curiosity to reward unusual mutations [CURIOSITY-0].

        base_fitness MUST be in [0.0, 1.0].
        """
        if not (0.0 <= base_fitness <= 1.0):
            raise CuriosityViolation(
                f"CURIOSITY-0: base_fitness={base_fitness} outside [0.0, 1.0]."
            )
        if not self._state.active:
            return base_fitness
        return round(1.0 - base_fitness, 4)

    def verify_chain(self) -> tuple[bool, str]:
        """Replay ledger and verify HMAC chain integrity. [CED-INV-CHAIN]"""
        if not self.ledger_path.exists():
            return True, "empty ledger — chain trivially valid"
        prev = "genesis"
        for i, line in enumerate(self.ledger_path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                recorded_prev = d.get("prev_digest", "genesis")
                if recorded_prev != prev:
                    return (
                        False,
                        f"Chain broken at entry {i}: expected prev_digest="
                        f"{prev!r}, got {recorded_prev!r}",
                    )
                stored_digest = d.get("event_digest", "")
                fields = {k: v for k, v in d.items()
                          if k in CuriosityEvent.__dataclass_fields__}
                ev = CuriosityEvent(**fields)
                ev.event_digest = ""
                expected = ev._compute_digest()
                if not hmac.compare_digest(stored_digest, expected):
                    return (
                        False,
                        f"Digest mismatch at entry {i}: "
                        f"stored={stored_digest!r} computed={expected!r}",
                    )
                prev = stored_digest
            except Exception as exc:
                return False, f"Entry {i} unparseable: {exc}"
        return True, "chain valid across all entries"

    def state_summary(self) -> dict[str, Any]:
        return dataclasses.asdict(self._state)

    # ── private ──────────────────────────────────────────────────────────────

    def _emit_event(
        self, event_type: str, epoch_id: str, health_score: float, reason: str
    ) -> None:
        """Build and append a CuriosityEvent to the chain ledger."""
        event = CuriosityEvent(
            event_type=event_type,
            epoch_id=epoch_id,
            cycle_number=self._state.cycle_number,
            epochs_remaining=self._state.epochs_remaining,
            health_score=health_score,
            reason=reason,
            prev_digest=self._last_digest,
        )
        self._append_event(event)

    def _append_event(self, event: CuriosityEvent) -> None:
        """CED-INV-AUDIT: append-only JSONL write; CED-INV-CHAIN: advance chain head."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            f.write(event.to_ledger_row() + "\n")
        self._last_digest = event.event_digest

    def _exit_curiosity(self, reason: str) -> None:
        self._state.active = False
        self._state.epochs_remaining = 0
        self._state.discoveries.append(f"exit:{reason}")
        self._save()

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                d = json.loads(self.state_path.read_text())
                if "discoveries" not in d:
                    d["discoveries"] = []
                self._state = CuriosityState(**d)
            except Exception:
                pass
        # Restore chain head from ledger
        if self.ledger_path.exists():
            last_digest = "genesis"
            for line in self.ledger_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    if d.get("event_digest"):
                        last_digest = d["event_digest"]
                except Exception:
                    pass
            self._last_digest = last_digest

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(dataclasses.asdict(self._state), indent=2)
        )


__all__ = [
    "CuriosityEngine", "CuriosityState", "CuriosityEvent", "CuriosityViolation",
    "curiosity_guard",
    "CURIOSITY_INVARIANTS", "CURIOSITY_INTERVAL", "CURIOSITY_DURATION",
    "HARD_STOP_HEALTH", "HARD_STOP_PATTERNS",
    "CED_INV_CHAIN", "CED_INV_DETERM", "CED_INV_AUDIT", "CED_LEDGER_DEFAULT",
]
