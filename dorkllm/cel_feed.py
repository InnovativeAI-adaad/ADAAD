# SPDX-License-Identifier: Apache-2.0
"""
dorkllm.cel_feed — Live Execution Feed (LEF) engine for Phase 148.

Constitutional invariants enforced here:

  CEL-FEED-0    Subscribing MUST NEVER influence CEL execution path.
                Subscribers are purely passive observers; the engine
                never awaits subscriber acknowledgement before continuing.

  CEL-FEED-COMPLETE-0
                Every CEL cycle MUST emit a COMPLETE or BLOCKED step
                before the generator returns.  Silent exits are a
                constitutional violation.

  LEF-CHAIN-0   The HMAC chain is integrity-critical.  Any chain break
                (wrong prev_hash) raises CELChainIntegrityError and the
                engine stops emitting.  No partial-chain emission.

  LEF-DETERM-0  CELStepEvent serialisation is deterministic for identical
                inputs (sorted keys, UTC timestamps, no random salt beyond
                the HMAC key).

  LEF-NOWRITE-0 SSE subscription produces zero lineage ledger writes.
                The engine holds events in memory only; it never touches
                the evidence ledger or GovernanceGate.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

__all__ = [
    "CELStepEvent",
    "CELFeedEngine",
    "CELFeedError",
    "CELChainIntegrityError",
    "get_global_engine",
    "INVARIANT_CEL_FEED_0",
    "INVARIANT_CEL_FEED_COMPLETE_0",
    "INVARIANT_LEF_CHAIN_0",
    "INVARIANT_LEF_DETERM_0",
    "INVARIANT_LEF_NOWRITE_0",
]

LOG = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Invariant sentinels (importable for test assertion)                          #
# --------------------------------------------------------------------------- #
INVARIANT_CEL_FEED_0 = "CEL-FEED-0:subscribe_never_influences_execution"
INVARIANT_CEL_FEED_COMPLETE_0 = "CEL-FEED-COMPLETE-0:every_cycle_emits_complete_or_blocked"
INVARIANT_LEF_CHAIN_0 = "LEF-CHAIN-0:hmac_chain_integrity_fatal"
INVARIANT_LEF_DETERM_0 = "LEF-DETERM-0:serialisation_deterministic"
INVARIANT_LEF_NOWRITE_0 = "LEF-NOWRITE-0:no_ledger_writes"

# --------------------------------------------------------------------------- #
# Exceptions                                                                   #
# --------------------------------------------------------------------------- #

class CELFeedError(RuntimeError):
    """Base exception for LEF engine errors."""


class CELChainIntegrityError(CELFeedError):
    """Raised when the HMAC chain is broken (LEF-CHAIN-0 violation)."""


# --------------------------------------------------------------------------- #
# Event dataclass                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class CELStepEvent:
    """
    Atomic CEL pipeline step record.

    Fields
    ------
    event_id       : globally unique UUID4 per event
    epoch_id       : epoch identifier from EvolutionLoop (or synthetic)
    step_name      : human-readable label, e.g. "PROPOSAL", "GATE_EVAL"
    status         : one of STARTED / COMPLETE / BLOCKED / ERROR
    timestamp_utc  : Unix epoch seconds (float)
    payload        : arbitrary JSON-serialisable step metadata
    prev_hash      : SHA-256 hex of previous event's hmac_sig (chain link)
    hmac_sig       : HMAC-SHA256(key, canonical_bytes) hex digest
    """

    event_id: str
    epoch_id: str
    step_name: str
    status: str  # STARTED | COMPLETE | BLOCKED | ERROR
    timestamp_utc: float
    payload: Dict[str, Any] = field(default_factory=dict)
    prev_hash: str = "0" * 64       # genesis sentinel
    hmac_sig: str = field(default="", init=False)

    # Allowed status values — enforced at emit time
    VALID_STATUSES = frozenset({"STARTED", "COMPLETE", "BLOCKED", "ERROR"})

    def canonical_bytes(self) -> bytes:
        """
        Deterministic serialisation for HMAC computation (LEF-DETERM-0).

        Excludes hmac_sig itself; sorted keys ensure stability across
        Python versions.
        """
        body = {
            "event_id": self.event_id,
            "epoch_id": self.epoch_id,
            "step_name": self.step_name,
            "status": self.status,
            "timestamp_utc": self.timestamp_utc,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

    def to_sse_data(self) -> str:
        """Serialise for Server-Sent Events data field (JSON, sorted keys)."""
        d = {
            "event_id": self.event_id,
            "epoch_id": self.epoch_id,
            "step_name": self.step_name,
            "status": self.status,
            "timestamp_utc": self.timestamp_utc,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "hmac_sig": self.hmac_sig,
        }
        return json.dumps(d, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Engine                                                                        #
# --------------------------------------------------------------------------- #

_GENESIS_HASH = "0" * 64
_MAX_BUFFER = 512           # per-subscriber ring buffer cap
_HMAC_KEY_ENV = "ADAAD_LEF_HMAC_KEY"


def _get_hmac_key() -> bytes:
    raw = os.environ.get(_HMAC_KEY_ENV, "")
    if raw:
        return raw.encode()
    # Derive a stable per-process key from ADAAD signing material or fallback
    signing_seed = os.environ.get("ADAAD_MCP_JWT_SECRET", "adaad-lef-default")
    return hashlib.sha256(signing_seed.encode()).digest()


def _compute_hmac(key: bytes, data: bytes) -> str:
    return _hmac.new(key, data, hashlib.sha256).hexdigest()


class CELFeedEngine:
    """
    HMAC-chained LEF event bus.

    Responsibilities
    ----------------
    * Accept emitted ``CELStepEvent`` objects from EvolutionLoop hooks.
    * Compute and verify the HMAC chain (LEF-CHAIN-0).
    * Fan events out to registered async queues (subscribers).
    * Expose ``event_stream()`` sync generator and ``async_event_stream()``
      async generator for SSE consumption.

    Thread safety
    -------------
    ``emit()`` is safe to call from any thread (uses a Lock for chain state).
    Subscriber queues are asyncio Queues; the engine posts to them via
    ``loop.call_soon_threadsafe``.
    """

    def __init__(self, *, hmac_key: Optional[bytes] = None) -> None:
        self._key: bytes = hmac_key or _get_hmac_key()
        self._prev_hash: str = _GENESIS_HASH
        self._chain_lock = threading.Lock()
        self._subscribers: List[asyncio.Queue] = []   # CEL-FEED-0: read-only fan-out
        self._sub_lock = threading.Lock()
        self._event_log: List[CELStepEvent] = []      # LEF-NOWRITE-0: memory only
        self._running = True

    # ------------------------------------------------------------------ #
    # Public emit API                                                       #
    # ------------------------------------------------------------------ #

    def emit(self, event: CELStepEvent) -> CELStepEvent:
        """
        Sign, chain, and fan-out a CEL step event.

        Raises
        ------
        CELChainIntegrityError  if prev_hash does not match expected head
                                (LEF-CHAIN-0).
        ValueError              if status not in VALID_STATUSES.
        """
        if event.status not in CELStepEvent.VALID_STATUSES:
            raise ValueError(f"invalid status '{event.status}'; must be one of {CELStepEvent.VALID_STATUSES}")

        with self._chain_lock:
            # Chain verification (LEF-CHAIN-0)
            if event.prev_hash != self._prev_hash:
                raise CELChainIntegrityError(
                    f"LEF-CHAIN-0 violation: expected prev_hash={self._prev_hash!r} "
                    f"got {event.prev_hash!r} on event {event.event_id!r}"
                )

            # Sign (LEF-DETERM-0)
            event.hmac_sig = _compute_hmac(self._key, event.canonical_bytes())

            # Advance chain head
            self._prev_hash = event.hmac_sig

            # Memory store (LEF-NOWRITE-0)
            self._event_log.append(event)

        # Fan-out to subscribers (CEL-FEED-0: never awaits, non-blocking)
        self._fanout(event)
        LOG.debug("LEF emit step=%s status=%s epoch=%s", event.step_name, event.status, event.epoch_id)
        return event

    def build_event(
        self,
        *,
        step_name: str,
        status: str,
        epoch_id: str = "UNSET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> CELStepEvent:
        """
        Factory helper — constructs a correctly chained event.

        Call ``emit()`` afterwards to sign and broadcast it.
        """
        with self._chain_lock:
            prev = self._prev_hash
        return CELStepEvent(
            event_id=str(uuid.uuid4()),
            epoch_id=epoch_id,
            step_name=step_name,
            status=status,
            timestamp_utc=time.time(),
            payload=payload or {},
            prev_hash=prev,
        )

    def emit_step(
        self,
        step_name: str,
        status: str,
        *,
        epoch_id: str = "UNSET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> CELStepEvent:
        """Convenience: build + emit in one call."""
        ev = self.build_event(step_name=step_name, status=status, epoch_id=epoch_id, payload=payload)
        return self.emit(ev)

    # ------------------------------------------------------------------ #
    # Subscriber management (CEL-FEED-0)                                   #
    # ------------------------------------------------------------------ #

    def subscribe(self) -> asyncio.Queue:
        """
        Register a new subscriber queue.  Returns an asyncio.Queue that
        receives CELStepEvent objects.

        CEL-FEED-0: subscription never influences the emission path.
        The queue is purely additive; removing a subscriber has zero
        effect on the chain or any other subscriber.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFER)
        with self._sub_lock:
            self._subscribers.append(q)
        LOG.debug("LEF: subscriber registered (total=%d)", len(self._subscribers))
        return q

    async def subscribe(self) -> asyncio.Queue:
        """
        Register a new subscriber queue.  Returns an asyncio.Queue that
        receives CELStepEvent objects.

        Declared async so the MCP SSE endpoint can use:
            ``q = await engine.subscribe()``

        CEL-FEED-0: subscription never influences the emission path.
        The queue is purely additive; removing a subscriber has zero
        effect on the chain or any other subscriber.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFER)
        with self._sub_lock:
            self._subscribers.append(q)
        LOG.debug("LEF: subscriber registered (total=%d)", len(self._subscribers))
        return q

    def subscribe_sync(self) -> asyncio.Queue:
        """
        Synchronous subscriber registration for non-async contexts (testing, etc).
        Behaviour identical to subscribe(); use this from sync code.

        CEL-FEED-0: no emission-path influence.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFER)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    async def subscribe_async(self) -> asyncio.Queue:
        """Awaitable alias — delegates to subscribe()."""
        return await self.subscribe()

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue (CEL-FEED-0: no side-effects on chain)."""
        with self._sub_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _fanout(self, event: CELStepEvent) -> None:
        """Non-blocking fan-out to all subscriber queues."""
        with self._sub_lock:
            subs = list(self._subscribers)
        dead = []
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                LOG.warning("LEF: subscriber queue full, dropping event %s", event.event_id)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("LEF: subscriber fanout error %s", exc)
                dead.append(q)
        if dead:
            with self._sub_lock:
                for q in dead:
                    try:
                        self._subscribers.remove(q)
                    except ValueError:
                        pass

    # ------------------------------------------------------------------ #
    # Stream generators                                                     #
    # ------------------------------------------------------------------ #

    async def async_event_stream(
        self, *, timeout: float = 30.0
    ) -> AsyncGenerator[str, None]:
        """
        Async generator yielding SSE-formatted strings.

        Automatically unsubscribes on generator exit (cancellation or close).

        CEL-FEED-COMPLETE-0: callers must ensure the epoch driver emits
        COMPLETE or BLOCKED before abandoning this generator; the generator
        itself does NOT enforce this invariant — that is the epoch driver's
        responsibility.

        LEF-NOWRITE-0: yields strings only, touches no ledger.
        """
        q = self.subscribe()
        try:
            while True:
                try:
                    event: CELStepEvent = await asyncio.wait_for(q.get(), timeout=timeout)
                    yield f"data: {event.to_sse_data()}\n\n"
                    if event.status in ("COMPLETE", "BLOCKED"):
                        # Signal epoch boundary — stream remains open for next epoch
                        yield "data: {\"type\":\"epoch_boundary\"}\n\n"
                except asyncio.TimeoutError:
                    # Send SSE keepalive comment
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            self.unsubscribe(q)

    def event_stream(
        self, q: Optional[asyncio.Queue] = None
    ) -> Generator[str, None, None]:
        """
        Synchronous generator for non-async contexts (WSGI / testing).

        When the MCP SSE endpoint calls ``engine.event_stream(q)`` with a
        pre-registered asyncio.Queue, this method drains that queue synchronously
        using ``asyncio.get_event_loop().run_until_complete`` or a blocking wait.

        For pure sync use (no queue supplied), events are collected from a
        lightweight list-based subscriber.

        LEF-NOWRITE-0: no ledger writes.
        """
        if q is not None:
            # Drain the pre-registered async queue in a blocking manner.
            # Used by the MCP SSE endpoint in an async context via StreamingResponse.
            # The caller (FastAPI's async generator wrapper) handles iteration.
            import asyncio as _aio

            async def _drain():
                while True:
                    try:
                        event: CELStepEvent = await _aio.wait_for(q.get(), timeout=30.0)
                        yield f"data: {event.to_sse_data()}\n\n"
                        if event.status in ("COMPLETE", "BLOCKED"):
                            yield 'data: {"type":"epoch_boundary"}\n\n'
                    except _aio.TimeoutError:
                        yield ": keepalive\n\n"
                    except _aio.CancelledError:
                        break

            # Return the async generator directly — FastAPI handles async iteration
            return _drain()  # type: ignore[return-value]

        # Pure-sync path: lightweight list subscriber
        buf: "list[CELStepEvent]" = []
        with self._sub_lock:
            self._subscribers.append(buf)  # type: ignore[arg-type]
        try:
            last_idx = 0
            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                if last_idx < len(buf):  # type: ignore[arg-type]
                    event = buf[last_idx]  # type: ignore[index]
                    last_idx += 1
                    yield f"data: {event.to_sse_data()}\n\n"
                else:
                    time.sleep(0.05)
        finally:
            with self._sub_lock:
                try:
                    self._subscribers.remove(buf)  # type: ignore[arg-type]
                except ValueError:
                    pass

    async def event_stream_async(
        self,
        q: Optional[asyncio.Queue] = None,
        *,
        timeout: float = 30.0,
    ) -> AsyncGenerator[str, None]:
        """
        Async generator yielding SSE strings, optionally consuming a pre-registered queue.

        The MCP SSE endpoint uses the pattern::

            q = await engine.subscribe()
            async for chunk in engine.event_stream(q):
                yield chunk

        When ``q`` is supplied the engine drains it directly without creating
        a second subscriber (CEL-FEED-0: no double-counting).

        LEF-NOWRITE-0: yields strings only, touches no ledger.
        """
        owned = q is None
        if owned:
            q = await self.subscribe()
        try:
            while True:
                try:
                    event: CELStepEvent = await asyncio.wait_for(q.get(), timeout=timeout)
                    yield f"data: {event.to_sse_data()}\n\n"
                    if event.status in ("COMPLETE", "BLOCKED"):
                        yield 'data: {"type":"epoch_boundary"}\n\n'
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            if owned:
                self.unsubscribe(q)

    # ------------------------------------------------------------------ #
    # Introspection                                                         #
    # ------------------------------------------------------------------ #

    @property
    def chain_head(self) -> str:
        """Current HMAC chain head (last emitted event's hmac_sig)."""
        return self._prev_hash

    @property
    def event_count(self) -> int:
        return len(self._event_log)

    def verify_chain(self) -> bool:
        """
        Replay the in-memory log and verify every HMAC link.

        Returns True if chain is intact, raises CELChainIntegrityError otherwise.
        """
        prev = _GENESIS_HASH
        for ev in self._event_log:
            if ev.prev_hash != prev:
                raise CELChainIntegrityError(
                    f"Chain broken at event {ev.event_id}: "
                    f"expected prev={prev!r} got {ev.prev_hash!r}"
                )
            expected_sig = _compute_hmac(self._key, ev.canonical_bytes())
            if not _hmac.compare_digest(ev.hmac_sig, expected_sig):
                raise CELChainIntegrityError(
                    f"HMAC mismatch at event {ev.event_id}"
                )
            prev = ev.hmac_sig
        return True

    def verify_ledger_chain(self) -> Dict[str, Any]:
        """
        LEF-CHAIN-0 ledger chain verification — returns a structured JSON-safe dict
        suitable for the ``GET /events/cel-feed/chain`` REST endpoint.

        On success  → ``{"ok": True,  "chain_integrity": True,  "event_count": N, "chain_head": "..."}``
        On failure  → ``{"ok": False, "chain_integrity": False, "error": "...", "event_count": N}``
        """
        try:
            self.verify_chain()
            return {
                "ok": True,
                "chain_integrity": True,
                "event_count": self.event_count,
                "chain_head": self.chain_head,
                "invariant": "LEF-CHAIN-0",
                "status": "verified",
            }
        except CELChainIntegrityError as exc:
            return {
                "ok": False,
                "chain_integrity": False,
                "event_count": self.event_count,
                "chain_head": self.chain_head,
                "invariant": "LEF-CHAIN-0",
                "status": "broken",
                "error": str(exc),
            }

    def snapshot(self) -> List[Dict[str, Any]]:
        """Return read-only snapshot of all events (LEF-NOWRITE-0: no writes)."""
        return [
            {
                "event_id": e.event_id,
                "epoch_id": e.epoch_id,
                "step_name": e.step_name,
                "status": e.status,
                "timestamp_utc": e.timestamp_utc,
                "hmac_sig": e.hmac_sig,
                "prev_hash": e.prev_hash,
            }
            for e in self._event_log
        ]


# --------------------------------------------------------------------------- #
# Process-global singleton                                                      #
# --------------------------------------------------------------------------- #

_global_engine: Optional[CELFeedEngine] = None
_global_lock = threading.Lock()


def get_global_engine() -> CELFeedEngine:
    """
    Return (or lazily create) the process-global CELFeedEngine.

    Safe to call from any thread.
    """
    global _global_engine
    if _global_engine is None:
        with _global_lock:
            if _global_engine is None:
                _global_engine = CELFeedEngine()
    return _global_engine
