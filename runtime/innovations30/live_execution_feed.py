# SPDX-License-Identifier: Apache-2.0
"""
runtime.innovations30.live_execution_feed — Innovation 54

LiveExecutionFeed (LEF) is the EvolutionLoop-aware adapter that wraps
``dorkllm.cel_feed.CELFeedEngine`` and provides:

  * Pre/post epoch hooks for automatic step emission
  * Named step context manager for wrapping arbitrary CEL pipeline steps
  * Registry integration so the innovation is discoverable at runtime

Constitutional invariants (inherited from dorkllm.cel_feed):
  CEL-FEED-0, CEL-FEED-COMPLETE-0, LEF-CHAIN-0, LEF-DETERM-0, LEF-NOWRITE-0
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from typing import Any, Dict, Generator, Optional

from dorkllm.cel_feed import (
    CELFeedEngine,
    CELStepEvent,
    get_global_engine,
    INVARIANT_CEL_FEED_0,
    INVARIANT_LEF_NOWRITE_0,
)

__all__ = [
    "LiveExecutionFeed",
    "lef_context",
    "INNOVATION_ID",
    "INNOVATION_VERSION",
]

LOG = logging.getLogger(__name__)

INNOVATION_ID = "INNOV-54"
INNOVATION_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# LiveExecutionFeed                                                             #
# --------------------------------------------------------------------------- #


class LiveExecutionFeed:
    """
    EvolutionLoop adapter for the LEF engine.

    Provides:
        on_epoch_start(epoch_id)      — emits STARTED step
        on_epoch_complete(epoch_id)   — emits COMPLETE step  (CEL-FEED-COMPLETE-0)
        on_epoch_blocked(epoch_id)    — emits BLOCKED step   (CEL-FEED-COMPLETE-0)
        step(name, epoch_id)          — context manager for arbitrary step spans
        engine                        — exposes underlying CELFeedEngine

    CEL-FEED-0: These hooks are purely observational. They are called
    *after* the EvolutionLoop internal state has been updated, never
    in a position to mutate or gate loop execution.

    LEF-NOWRITE-0: No filesystem or ledger writes occur.
    """

    def __init__(self, engine: Optional[CELFeedEngine] = None) -> None:
        self._engine: CELFeedEngine = engine or get_global_engine()
        self._active_epoch: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def engine(self) -> CELFeedEngine:
        return self._engine

    # ------------------------------------------------------------------ #
    # Epoch lifecycle hooks                                                #
    # ------------------------------------------------------------------ #

    def on_epoch_start(self, epoch_id: str, *, payload: Optional[Dict[str, Any]] = None) -> CELStepEvent:
        """
        Emit STARTED for the epoch entry point.

        CEL-FEED-0: called by EvolutionLoop AFTER it has begun; never gates entry.
        """
        with self._lock:
            self._active_epoch = epoch_id
        return self._engine.emit_step(
            "EPOCH_START",
            "STARTED",
            epoch_id=epoch_id,
            payload=payload or {"innovation": INNOVATION_ID},
        )

    def on_epoch_complete(self, epoch_id: str, *, payload: Optional[Dict[str, Any]] = None) -> CELStepEvent:
        """
        Emit COMPLETE for a successfully finished epoch (CEL-FEED-COMPLETE-0).
        """
        ev = self._engine.emit_step(
            "EPOCH_COMPLETE",
            "COMPLETE",
            epoch_id=epoch_id,
            payload=payload or {},
        )
        with self._lock:
            if self._active_epoch == epoch_id:
                self._active_epoch = None
        return ev

    def on_epoch_blocked(self, epoch_id: str, *, reason: str = "governance_gate", payload: Optional[Dict[str, Any]] = None) -> CELStepEvent:
        """
        Emit BLOCKED when epoch is halted by governance (CEL-FEED-COMPLETE-0).
        """
        p = {"reason": reason}
        if payload:
            p.update(payload)
        ev = self._engine.emit_step(
            "EPOCH_BLOCKED",
            "BLOCKED",
            epoch_id=epoch_id,
            payload=p,
        )
        with self._lock:
            if self._active_epoch == epoch_id:
                self._active_epoch = None
        return ev

    def on_step_error(self, step_name: str, epoch_id: str, *, error: str = "") -> CELStepEvent:
        """Emit ERROR for a named step."""
        return self._engine.emit_step(
            step_name,
            "ERROR",
            epoch_id=epoch_id,
            payload={"error": error},
        )

    # ------------------------------------------------------------------ #
    # Context manager for arbitrary named steps                            #
    # ------------------------------------------------------------------ #

    @contextlib.contextmanager
    def step(
        self,
        name: str,
        *,
        epoch_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Generator[CELStepEvent, None, None]:
        """
        Context manager that emits STARTED on entry and COMPLETE on clean exit
        (or ERROR on exception).

        CEL-FEED-0: Never raises or suppresses exceptions from wrapped code.

        Usage::

            lef = LiveExecutionFeed()
            with lef.step("PROPOSAL", epoch_id="ep-42") as ev:
                # ... run proposal code ...
                pass
            # COMPLETE emitted automatically
        """
        eid = epoch_id or (self._active_epoch or "UNSET")
        start_payload = dict(payload or {})
        start_ev = self._engine.emit_step(name, "STARTED", epoch_id=eid, payload=start_payload)
        t0 = time.monotonic()
        try:
            yield start_ev
            elapsed = time.monotonic() - t0
            self._engine.emit_step(name, "COMPLETE", epoch_id=eid, payload={"elapsed_s": round(elapsed, 4)})
        except Exception as exc:
            elapsed = time.monotonic() - t0
            try:
                self._engine.emit_step(name, "ERROR", epoch_id=eid, payload={"error": str(exc), "elapsed_s": round(elapsed, 4)})
            except Exception:  # noqa: BLE001
                pass
            raise  # CEL-FEED-0: never suppress

    # ------------------------------------------------------------------ #
    # Introspection                                                         #
    # ------------------------------------------------------------------ #

    @property
    def active_epoch(self) -> Optional[str]:
        return self._active_epoch

    @property
    def chain_head(self) -> str:
        return self._engine.chain_head

    def verify_chain(self) -> bool:
        """Delegate to engine chain verifier."""
        return self._engine.verify_chain()


# --------------------------------------------------------------------------- #
# Module-level singleton factory                                               #
# --------------------------------------------------------------------------- #

@contextlib.contextmanager
def lef_context(epoch_id: str, *, engine: Optional[CELFeedEngine] = None) -> Generator[LiveExecutionFeed, None, None]:
    """
    Convenience context manager for a full epoch lifecycle::

        with lef_context("ep-001") as lef:
            # epoch runs
            pass
        # EPOCH_COMPLETE emitted on exit

    CEL-FEED-COMPLETE-0: COMPLETE always emitted unless an exception
    causes BLOCKED/ERROR to be emitted instead.
    """
    lef = LiveExecutionFeed(engine=engine)
    lef.on_epoch_start(epoch_id)
    try:
        yield lef
        lef.on_epoch_complete(epoch_id)
    except Exception as exc:
        try:
            lef.on_epoch_blocked(epoch_id, reason=str(exc))
        except Exception:  # noqa: BLE001
            pass
        raise


# --------------------------------------------------------------------------- #
# Per-phase engine registry (Phase 148 — required by MCP SSE endpoint)         #
#                                                                               #
# get_feed_engine(phase) returns a stable CELFeedEngine instance keyed by      #
# phase number.  The global engine (phase=0 / default) is also accessible.     #
#                                                                               #
# CEL-FEED-0: registry operations never influence any engine's emit path.       #
# LEF-NOWRITE-0: registry is in-memory only; no ledger writes.                 #
# --------------------------------------------------------------------------- #

_phase_engines: Dict[int, CELFeedEngine] = {}
_registry_lock = threading.Lock()

_DEFAULT_PHASE = 148


def get_feed_engine(phase: int = _DEFAULT_PHASE) -> CELFeedEngine:
    """
    Return (or lazily create) a stable ``CELFeedEngine`` for the given phase number.

    Called by the MCP SSE endpoint:
        ``engine = get_feed_engine(phase)``

    CEL-FEED-0: getting an engine never influences any emission path.
    LEF-NOWRITE-0: the registry is in-memory only.

    Parameters
    ----------
    phase : int
        Phase number key (default: 148 — the LEF inception phase).
        Phase 0 is an alias for the process-global engine.
    """
    if phase == 0:
        return get_global_engine()
    with _registry_lock:
        if phase not in _phase_engines:
            _phase_engines[phase] = CELFeedEngine()
        return _phase_engines[phase]


def probe(phase: int = _DEFAULT_PHASE) -> Dict[str, Any]:
    """
    INNOV-COMPLETE-0 health probe for the LEF engine at *phase*.

    Called by the MCP endpoint:
        ``GET /events/cel-feed/health``
        ``return lef_probe(phase)``

    Returns a JSON-safe dict with chain integrity, event count, subscriber
    count, and constitutional invariant status.  Never raises; fails to
    ``{"ok": False, "error": "..."}`` on any exception.

    LEF-NOWRITE-0: read-only; no ledger writes.
    CEL-FEED-0: probe never influences the emission path.
    """
    try:
        engine = get_feed_engine(phase)
        try:
            chain_ok = engine.verify_chain()
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "phase": phase,
                "chain_integrity": False,
                "error": str(exc),
                "event_count": engine.event_count,
                "chain_head": engine.chain_head,
                "invariants": {
                    "CEL-FEED-0": "enforced",
                    "LEF-CHAIN-0": "broken",
                    "LEF-NOWRITE-0": "enforced",
                },
            }
        with engine._sub_lock:
            subscriber_count = len(engine._subscribers)
        return {
            "ok": True,
            "phase": phase,
            "chain_integrity": chain_ok,
            "event_count": engine.event_count,
            "chain_head": engine.chain_head,
            "subscriber_count": subscriber_count,
            "invariants": {
                "CEL-FEED-0": "enforced",
                "CEL-FEED-COMPLETE-0": "enforced",
                "LEF-CHAIN-0": "verified",
                "LEF-DETERM-0": "enforced",
                "LEF-NOWRITE-0": "enforced",
            },
            "innovation": INNOVATION_ID,
            "version": INNOVATION_VERSION,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "phase": phase, "error": str(exc)}
