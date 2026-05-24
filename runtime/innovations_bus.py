# SPDX-License-Identifier: Apache-2.0
"""Phase 70 — Innovations Event Bus.

Async fan-out broadcaster for real-time CEL and innovations events.
WebSocket connections register here; emitters push typed frames.

Constitutional invariants
=========================
IBUS-FANOUT-0   Every connected subscriber receives every emitted frame.
IBUS-FAILSAFE-0 A broken subscriber is silently dropped; emission never raises.
IBUS-DETERM-0   Frame payloads must be JSON-serialisable dicts (no side effects).
IBUS-THREAD-0   emit() is coroutine-safe; call via asyncio.create_task from sync
                contexts using emit_sync().

Frame schema
============
Every frame is a dict with at minimum:
  {"type": str, "ts": ISO-8601, ...payload}

Defined frame types:
  cel_step       — one CEL step completed (step_number, step_name, outcome, detail)
  epoch_start    — epoch run begins      (epoch_id, run_mode)
  epoch_end      — epoch run completes   (epoch_id, outcome, mutations_succeeded)
  story_arc      — new arc pushed live   (epoch, agent, result, title)
  personality    — active personality for epoch (agent_id, philosophy, vector)
  reflection     — self-reflection report (dominant, underperforming, hint)
  gplugin        — G-plugin result        (plugin_id, passed, message)
  seed_planted   — capability seed registered (seed_id, lane, intent)
  seed_graduated — capability seed graduated   (seed_id, lane, expansion_score, epoch_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InnovationsEventBus:
    """Async fan-out event bus for the innovations stack.

    Singleton — use `get_bus()` rather than constructing directly.
    """

    def __init__(self) -> None:
        self._subscribers: List[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber; returns its Queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.append(q)
        logger.debug("innovations_bus: subscriber added (total=%d)", len(self._subscribers))
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue (called on WebSocket disconnect)."""
        async with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not q]
        logger.debug("innovations_bus: subscriber removed (total=%d)", len(self._subscribers))

    async def emit(self, frame: Dict[str, Any]) -> None:
        """Fan-out a frame to all subscribers.

        IBUS-FAILSAFE-0: broken queues (full) are silently dropped.
        IBUS-DETERM-0: frame must be JSON-serialisable.
        """
        if "ts" not in frame:
            frame = {**frame, "ts": _now_iso()}
        dead: List[asyncio.Queue] = []
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                logger.warning("innovations_bus: subscriber queue full — dropping (IBUS-FAILSAFE-0)")
                dead.append(q)
        if dead:
            async with self._lock:
                self._subscribers = [s for s in self._subscribers if s not in dead]

    def emit_sync(self, frame: Dict[str, Any]) -> None:
        """Fire-and-forget emit from sync context (IBUS-THREAD-0).

        Schedules emit() on the running event loop if one exists.
        Safe to call from non-async code; silently no-ops if no loop running.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(frame))
        except RuntimeError:
            pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# ── Singleton ─────────────────────────────────────────────────────────────────

_BUS: Optional[InnovationsEventBus] = None


def get_bus() -> InnovationsEventBus:
    """Return the process-wide InnovationsEventBus singleton."""
    global _BUS
    if _BUS is None:
        _BUS = InnovationsEventBus()
    return _BUS


# ── Typed emit helpers (used by CEL wiring and innovations_wiring) ─────────────

def emit_epoch_start(epoch_id: str, run_mode: str = "SANDBOX_ONLY") -> None:
    get_bus().emit_sync({"type": "epoch_start", "epoch_id": epoch_id, "run_mode": run_mode})


def emit_epoch_end(
    epoch_id: str,
    outcome: str,
    mutations_succeeded: int = 0,
    mutations_attempted: int = 0,
) -> None:
    get_bus().emit_sync({
        "type": "epoch_end",
        "epoch_id": epoch_id,
        "outcome": outcome,
        "mutations_succeeded": mutations_succeeded,
        "mutations_attempted": mutations_attempted,
    })


def emit_cel_step(
    epoch_id: str,
    step_number: int,
    step_name: str,
    outcome: str,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    get_bus().emit_sync({
        "type": "cel_step",
        "epoch_id": epoch_id,
        "step_number": step_number,
        "step_name": step_name,
        "outcome": outcome,
        "detail": detail or {},
    })


def emit_story_arc(
    epoch_id: str,
    agent: str,
    result: str,
    title: str = "",
    decision: str = "",
) -> None:
    get_bus().emit_sync({
        "type": "story_arc",
        "epoch": epoch_id,
        "agent": agent,
        "result": result,
        "title": title or f"Epoch {epoch_id}",
        "decision": decision,
    })


def emit_personality(agent_id: str, philosophy: str, vector: List[float], epoch_id: str = "") -> None:
    get_bus().emit_sync({
        "type": "personality",
        "agent_id": agent_id,
        "philosophy": philosophy,
        "vector": vector,
        "epoch_id": epoch_id,
    })


def emit_reflection(
    epoch_id: str,
    dominant_agent: str,
    underperforming_agent: str,
    rebalance_hint: str,
) -> None:
    get_bus().emit_sync({
        "type": "reflection",
        "epoch_id": epoch_id,
        "dominant_agent": dominant_agent,
        "underperforming_agent": underperforming_agent,
        "rebalance_hint": rebalance_hint,
    })


def emit_gplugin(plugin_id: str, passed: bool, message: str, mutation_id: str = "") -> None:
    get_bus().emit_sync({
        "type": "gplugin",
        "plugin_id": plugin_id,
        "passed": passed,
        "message": message,
        "mutation_id": mutation_id,
    })


def emit_seed_planted(seed_id: str, lane: str, intent: str, author: str = "") -> None:
    get_bus().emit_sync({
        "type": "seed_planted",
        "seed_id": seed_id,
        "lane": lane,
        "intent": intent,
        "author": author,
    })


def emit_seed_graduated(
    seed_id: str,
    lane: str,
    expansion_score: float,
    epoch_id: str = "",
) -> None:
    """Emit seed_graduated frame when a Capability Seed reaches graduation threshold.

    SEED-GRAD-0: emitted once per seed per epoch; payload includes expansion_score.
    IBUS-FAILSAFE-0: bus delivery is best-effort; caller must not rely on receipt.
    """
    get_bus().emit_sync({
        "type": "seed_graduated",
        "seed_id": seed_id,
        "lane": lane,
        "expansion_score": expansion_score,
        "epoch_id": epoch_id,
        "ritual": "capability_graduation",
    })


__all__ = [
    "InnovationsEventBus",
    "get_bus",
    "emit_cel_step",
    "emit_epoch_start",
    "emit_epoch_end",
    "emit_story_arc",
    "emit_personality",
    "emit_reflection",
    "emit_gplugin",
    "emit_seed_planted",
    "emit_seed_graduated",
]
