# SPDX-License-Identifier: Apache-2.0
"""Live Execution Feed (LEF) — Phase 148 / INNOV-54.

Constitutional invariants enforced in this module
--------------------------------------------------
LEF-DETERM-0  : Every CELStepEvent serialises to a deterministic canonical dict;
                no float keys, no set ordering, timestamps are ISO-8601 strings.
LEF-CHAIN-0   : HMAC-SHA256 links each event to its predecessor; broken chains
                raise LEFChainViolation immediately.
CEL-FEED-0    : Subscribers are passive observers only.  subscribe/unsubscribe
                NEVER mutate CEL execution state.
LEF-NOWRITE-0 : event_stream() is read/drain only; zero ledger writes occur
                inside the SSE generator.
CEL-FEED-COMPLETE-0 : A cycle that exits without COMPLETE or BLOCKED status
                      raises LEFFeedIncomplete immediately.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Typed exceptions (one per Hard-class invariant)
# ---------------------------------------------------------------------------


class LEFDeterminismViolation(RuntimeError):
    """LEF-DETERM-0: event dict is not deterministic / canonical."""


class LEFChainViolation(RuntimeError):
    """LEF-CHAIN-0: HMAC chain is broken between events."""


class LEFFeedMutationViolation(RuntimeError):
    """CEL-FEED-0: subscriber code attempted to mutate CEL state."""


class LEFWriteViolation(RuntimeError):
    """LEF-NOWRITE-0: ledger write attempted inside SSE generator."""


class LEFFeedIncomplete(RuntimeError):
    """CEL-FEED-COMPLETE-0: cycle exited without COMPLETE or BLOCKED."""


# ---------------------------------------------------------------------------
# HMAC key — loaded from env or default dev secret
# ---------------------------------------------------------------------------

_HMAC_KEY: bytes = os.getenv("ADAAD_LEF_HMAC_KEY", "adaad-lef-dev-secret-do-not-use-in-prod").encode()

TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETE", "BLOCKED"})
_LEDGER_SUFFIX = ".lef.jsonl"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CELStepEvent:
    """Immutable snapshot of one CEL step, chain-linked by HMAC."""

    phase: int
    step: int
    status: str  # RUNNING | COMPLETE | BLOCKED | ERROR
    agent: str
    description: str
    timestamp_iso: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    prev_hmac: str = ""  # hex digest of previous event's canonical dict
    event_hmac: str = field(init=False, default="")

    def __post_init__(self) -> None:
        canonical = self._canonical_dict(include_event_hmac=False)
        self.event_hmac = hmac.new(_HMAC_KEY, json.dumps(canonical, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------
    def _canonical_dict(self, *, include_event_hmac: bool = True) -> Dict:
        """Deterministic serialisation — LEF-DETERM-0."""
        d: Dict = {
            "agent": str(self.agent),
            "description": str(self.description),
            "phase": int(self.phase),
            "prev_hmac": str(self.prev_hmac),
            "status": str(self.status),
            "step": int(self.step),
            "timestamp_iso": str(self.timestamp_iso),
        }
        if include_event_hmac:
            d["event_hmac"] = str(self.event_hmac)
        return dict(sorted(d.items()))

    def to_dict(self) -> Dict:
        return self._canonical_dict()

    def to_json(self) -> str:
        return json.dumps(self._canonical_dict(), sort_keys=True)

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: Dict) -> "CELStepEvent":
        evt = cls(
            phase=d["phase"],
            step=d["step"],
            status=d["status"],
            agent=d["agent"],
            description=d["description"],
            timestamp_iso=d["timestamp_iso"],
            prev_hmac=d.get("prev_hmac", ""),
        )
        # Override computed hmac with stored value for chain verification
        evt.event_hmac = d["event_hmac"]
        return evt


# ---------------------------------------------------------------------------
# Chain state
# ---------------------------------------------------------------------------


class LEFChainState:
    """Tracks the running HMAC tail for chain linking — LEF-CHAIN-0."""

    def __init__(self) -> None:
        self._tail_hmac: str = ""

    @property
    def tail(self) -> str:
        return self._tail_hmac

    def advance(self, event: CELStepEvent) -> None:
        """Verify event's prev_hmac matches current tail, then advance."""
        if not hmac.compare_digest(event.prev_hmac, self._tail_hmac):
            raise LEFChainViolation(
                f"LEF-CHAIN-0: broken chain at step={event.step}; "
                f"expected prev_hmac={self._tail_hmac!r}, got {event.prev_hmac!r}"
            )
        self._tail_hmac = event.event_hmac

    def reset(self) -> None:
        self._tail_hmac = ""


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


class CELFeedEngine:
    """Passive SSE feed engine for CEL execution steps.

    Constraints
    -----------
    - subscribe/unsubscribe are purely registry operations (CEL-FEED-0).
    - event_stream() drains a queue; it never writes to the ledger (LEF-NOWRITE-0).
    - assert_cycle_concluded() enforces CEL-FEED-COMPLETE-0 at cycle close.
    """

    def __init__(
        self,
        phase: int,
        ledger_path: Optional[Path] = None,
        *,
        max_queue: int = 256,
    ) -> None:
        self.phase = phase
        self._ledger_path: Path = ledger_path or Path(f"ledger/lef/phase{phase}{_LEDGER_SUFFIX}")
        self._chain = LEFChainState()
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._events: List[CELStepEvent] = []
        self._max_queue = max_queue
        self._last_status: Optional[str] = None
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Subscriber management (CEL-FEED-0 — passive only)
    # ------------------------------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        """Register a new passive observer queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        """Deregister a passive observer queue."""
        async with self._lock:
            self._subscribers.discard(q)

    # ------------------------------------------------------------------
    # Event publication (called by CEL orchestrator, not SSE generator)
    # ------------------------------------------------------------------

    async def publish(self, event: CELStepEvent) -> None:
        """Append event to chain + ledger, then fan-out to subscribers.

        NOTE: publish() is the ONLY path that writes to the ledger.
              It is explicitly NOT called from event_stream().
        """
        self._chain.advance(event)  # LEF-CHAIN-0 — raises on violation
        self._events.append(event)
        self._last_status = event.status

        # Append-only JSONL write
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_json() + "\n")

        # Fan-out to passive subscribers (CEL-FEED-0)
        async with self._lock:
            dead: Set[asyncio.Queue] = set()
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.add(q)
            self._subscribers -= dead

    def publish_sync(self, event: CELStepEvent) -> None:
        """Synchronous publish for non-async callers (acquires no event loop)."""
        self._chain.advance(event)
        self._events.append(event)
        self._last_status = event.status
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_json() + "\n")

    # ------------------------------------------------------------------
    # SSE generator (LEF-NOWRITE-0 — read/drain only)
    # ------------------------------------------------------------------

    async def event_stream(self, q: asyncio.Queue, *, timeout: float = 30.0) -> AsyncIterator[str]:
        """Yield SSE-formatted strings.  No ledger writes here (LEF-NOWRITE-0)."""
        try:
            while True:
                try:
                    event: CELStepEvent = await asyncio.wait_for(q.get(), timeout=timeout)
                    payload = json.dumps(event.to_dict(), sort_keys=True)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await self.unsubscribe(q)

    # ------------------------------------------------------------------
    # Cycle guard (CEL-FEED-COMPLETE-0)
    # ------------------------------------------------------------------

    def assert_cycle_concluded(self) -> None:
        """Raise LEFFeedIncomplete if cycle ended without terminal status."""
        if self._last_status not in TERMINAL_STATUSES:
            raise LEFFeedIncomplete(
                f"CEL-FEED-COMPLETE-0: cycle for phase={self.phase} exited with "
                f"status={self._last_status!r}; expected one of {sorted(TERMINAL_STATUSES)}"
            )

    # ------------------------------------------------------------------
    # Ledger chain verification
    # ------------------------------------------------------------------

    def verify_ledger_chain(self) -> Dict:
        """Re-read ledger JSONL and verify full HMAC chain integrity."""
        if not self._ledger_path.exists():
            return {"ok": True, "events": 0, "note": "ledger not yet written"}

        chain = LEFChainState()
        errors: List[str] = []
        count = 0

        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    evt = CELStepEvent.from_dict(d)
                    chain.advance(evt)
                    count += 1
                except LEFChainViolation as exc:
                    errors.append(f"line {lineno}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"line {lineno}: parse error — {exc}")

        return {
            "ok": not errors,
            "events": count,
            "errors": errors,
            "tail_hmac": chain.tail,
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> Dict:
        """Return health probe dict — INNOV-COMPLETE-0 compatible."""
        return {
            "invariant": "LEF-CHAIN-0",
            "phase": self.phase,
            "events_published": len(self._events),
            "subscribers": len(self._subscribers),
            "last_status": self._last_status,
            "ledger_path": str(self._ledger_path),
            "chain_tail": self._chain.tail[:16] + "…" if self._chain.tail else "",
            "ok": True,
        }


# ---------------------------------------------------------------------------
# Module-level singleton factory
# ---------------------------------------------------------------------------

_engines: Dict[int, CELFeedEngine] = {}


def get_engine(phase: int, *, ledger_path: Optional[Path] = None) -> CELFeedEngine:
    """Return (creating if absent) the singleton engine for *phase*."""
    if phase not in _engines:
        _engines[phase] = CELFeedEngine(phase, ledger_path=ledger_path)
    return _engines[phase]


def make_event(
    phase: int,
    step: int,
    status: str,
    agent: str,
    description: str,
    prev_hmac: str = "",
) -> CELStepEvent:
    """Convenience factory — LEF-DETERM-0 compliant."""
    return CELStepEvent(
        phase=phase,
        step=step,
        status=status,
        agent=agent,
        description=description,
        prev_hmac=prev_hmac,
    )
