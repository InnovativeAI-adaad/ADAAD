# SPDX-License-Identifier: Apache-2.0
"""Phase 148 / INNOV-54 — Live Execution Feed (LEF) acceptance tests.

30 tests covering:
  - CELStepEvent determinism (LEF-DETERM-0)
  - HMAC chain integrity (LEF-CHAIN-0)
  - Subscriber passivity (CEL-FEED-0)
  - No ledger writes in SSE generator (LEF-NOWRITE-0)
  - Cycle conclusion guard (CEL-FEED-COMPLETE-0)
  - Registry wrapper (INNOV-54)
  - MCP server route presence
  - Whaledic UI panel presence
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_lib
import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module imports
# ---------------------------------------------------------------------------

from dorkllm.cel_feed import (
    CELFeedEngine,
    CELStepEvent,
    LEFChainState,
    LEFChainViolation,
    LEFDeterminismViolation,
    LEFFeedIncomplete,
    LEFWriteViolation,
    LEFFeedMutationViolation,
    TERMINAL_STATUSES,
    get_engine,
    make_event,
)
from runtime.innovations30.live_execution_feed import (
    INNOV_ID,
    INVARIANTS,
    INNOV_PHASE,
    probe,
    registry_entry,
    get_feed_engine,
)

_HMAC_KEY = os.getenv("ADAAD_LEF_HMAC_KEY", "adaad-lef-dev-secret-do-not-use-in-prod").encode()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_ledger() -> Path:
    d = Path(tempfile.mkdtemp())
    return d / "test.lef.jsonl"


def _engine(phase: int = 9000) -> CELFeedEngine:
    """Fresh engine with temp ledger per test."""
    return CELFeedEngine(phase, ledger_path=_tmp_ledger())


def _evt(phase=9000, step=1, status="RUNNING", agent="TestAgent", desc="test step", prev_hmac="") -> CELStepEvent:
    return CELStepEvent(phase=phase, step=step, status=status, agent=agent, description=desc, prev_hmac=prev_hmac)


# ===========================================================================
# Group 1: CELStepEvent — LEF-DETERM-0
# ===========================================================================


@pytest.mark.T148
def test_lef01_event_canonical_dict_keys_sorted():
    """LEF-DETERM-0: canonical dict keys are sorted deterministically."""
    evt = _evt()
    d = evt._canonical_dict()
    assert list(d.keys()) == sorted(d.keys())


@pytest.mark.T148
def test_lef02_event_json_stable():
    """LEF-DETERM-0: two calls to to_json() produce identical strings."""
    evt = _evt()
    assert evt.to_json() == evt.to_json()


@pytest.mark.T148
def test_lef03_event_no_float_keys():
    """LEF-DETERM-0: no float values in canonical dict."""
    evt = _evt()
    for v in evt._canonical_dict().values():
        assert not isinstance(v, float), f"float found: {v}"


@pytest.mark.T148
def test_lef04_event_hmac_computed_on_init():
    """LEF-CHAIN-0: event_hmac is non-empty after __post_init__."""
    evt = _evt()
    assert len(evt.event_hmac) == 64  # sha256 hex


@pytest.mark.T148
def test_lef05_event_hmac_deterministic():
    """LEF-CHAIN-0: same inputs produce same hmac."""
    e1 = CELStepEvent(9000, 1, "RUNNING", "A", "desc", "2026-01-01T00:00:00+00:00", prev_hmac="")
    e2 = CELStepEvent(9000, 1, "RUNNING", "A", "desc", "2026-01-01T00:00:00+00:00", prev_hmac="")
    assert e1.event_hmac == e2.event_hmac


@pytest.mark.T148
def test_lef06_event_roundtrip_from_dict():
    """LEF-DETERM-0: from_dict preserves all fields."""
    evt = _evt(step=7, status="COMPLETE", agent="Beast", desc="roundtrip")
    d = evt.to_dict()
    restored = CELStepEvent.from_dict(d)
    assert restored.phase == evt.phase
    assert restored.step == evt.step
    assert restored.status == evt.status
    assert restored.agent == evt.agent
    assert restored.event_hmac == evt.event_hmac


@pytest.mark.T148
def test_lef07_different_descriptions_produce_different_hmacs():
    """LEF-DETERM-0: mutation in description changes hmac."""
    e1 = _evt(desc="alpha")
    e2 = _evt(desc="beta")
    assert e1.event_hmac != e2.event_hmac


# ===========================================================================
# Group 2: LEFChainState — LEF-CHAIN-0
# ===========================================================================


@pytest.mark.T148
def test_lef08_chain_starts_empty():
    """LEF-CHAIN-0: initial tail is empty string."""
    cs = LEFChainState()
    assert cs.tail == ""


@pytest.mark.T148
def test_lef09_chain_advance_updates_tail():
    """LEF-CHAIN-0: advance() moves tail to event_hmac."""
    cs = LEFChainState()
    evt = _evt(prev_hmac="")
    cs.advance(evt)
    assert cs.tail == evt.event_hmac


@pytest.mark.T148
def test_lef10_chain_broken_raises():
    """LEF-CHAIN-0: mismatched prev_hmac raises LEFChainViolation."""
    cs = LEFChainState()
    evt = _evt(prev_hmac="not_the_right_hash")
    with pytest.raises(LEFChainViolation):
        cs.advance(evt)


@pytest.mark.T148
def test_lef11_chain_sequential_valid():
    """LEF-CHAIN-0: sequential events chain correctly."""
    cs = LEFChainState()
    e1 = _evt(step=1, prev_hmac="")
    cs.advance(e1)
    e2 = _evt(step=2, prev_hmac=e1.event_hmac)
    cs.advance(e2)
    assert cs.tail == e2.event_hmac


@pytest.mark.T148
def test_lef12_chain_reset():
    """LEF-CHAIN-0: reset() returns tail to empty."""
    cs = LEFChainState()
    e1 = _evt(prev_hmac="")
    cs.advance(e1)
    cs.reset()
    assert cs.tail == ""


# ===========================================================================
# Group 3: CELFeedEngine — CEL-FEED-0 & LEF-NOWRITE-0
# ===========================================================================


@pytest.mark.T148
def test_lef13_engine_subscribe_returns_queue():
    """CEL-FEED-0: subscribe() returns an asyncio.Queue."""
    import asyncio

    engine = _engine()
    q = asyncio.get_event_loop().run_until_complete(engine.subscribe())
    assert isinstance(q, asyncio.Queue)


@pytest.mark.T148
def test_lef14_subscribe_does_not_mutate_events():
    """CEL-FEED-0: subscribing does not add to engine._events."""
    import asyncio

    engine = _engine()
    before = len(engine._events)
    asyncio.get_event_loop().run_until_complete(engine.subscribe())
    assert len(engine._events) == before


@pytest.mark.T148
def test_lef15_publish_sync_appends_event():
    """Core: publish_sync appends to engine._events."""
    engine = _engine()
    evt = _evt(prev_hmac="")
    engine.publish_sync(evt)
    assert len(engine._events) == 1


@pytest.mark.T148
def test_lef16_publish_sync_writes_ledger():
    """LEF-NOWRITE-0 context: publish_sync writes ledger; event_stream does not."""
    engine = _engine()
    evt = _evt(prev_hmac="")
    engine.publish_sync(evt)
    assert engine._ledger_path.exists()
    lines = engine._ledger_path.read_text().strip().splitlines()
    assert len(lines) == 1


@pytest.mark.T148
def test_lef17_event_stream_is_async_generator():
    """LEF-NOWRITE-0: event_stream returns an async iterator."""
    import asyncio
    import inspect

    engine = _engine()
    q = asyncio.get_event_loop().run_until_complete(engine.subscribe())
    gen = engine.event_stream(q)
    assert inspect.isasyncgen(gen)


@pytest.mark.T148
def test_lef18_event_stream_yields_sse_format():
    """LEF-NOWRITE-0: streamed chunks are SSE data: … format."""
    import asyncio

    engine = _engine()

    async def _run():
        q = await engine.subscribe()
        evt = _evt(prev_hmac="")
        engine.publish_sync(evt)
        # We need to put it on the queue manually since publish_sync bypasses async fan-out
        await q.put(evt)
        chunk = await engine.event_stream(q).__anext__()
        return chunk

    chunk = asyncio.get_event_loop().run_until_complete(_run())
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")


@pytest.mark.T148
def test_lef19_unsubscribe_removes_queue():
    """CEL-FEED-0: unsubscribe removes queue from subscribers set."""
    import asyncio

    engine = _engine()

    async def _run():
        q = await engine.subscribe()
        assert q in engine._subscribers
        await engine.unsubscribe(q)
        assert q not in engine._subscribers

    asyncio.get_event_loop().run_until_complete(_run())


@pytest.mark.T148
def test_lef20_publish_broken_chain_raises():
    """LEF-CHAIN-0: publish_sync raises on bad prev_hmac."""
    engine = _engine()
    e1 = _evt(step=1, prev_hmac="")
    engine.publish_sync(e1)
    e2 = _evt(step=2, prev_hmac="wrong_hmac")
    with pytest.raises(LEFChainViolation):
        engine.publish_sync(e2)


# ===========================================================================
# Group 4: Cycle guard — CEL-FEED-COMPLETE-0
# ===========================================================================


@pytest.mark.T148
def test_lef21_assert_cycle_concluded_ok_on_complete():
    """CEL-FEED-COMPLETE-0: no raise when last status is COMPLETE."""
    engine = _engine()
    evt = _evt(status="COMPLETE", prev_hmac="")
    engine.publish_sync(evt)
    engine.assert_cycle_concluded()  # should not raise


@pytest.mark.T148
def test_lef22_assert_cycle_concluded_ok_on_blocked():
    """CEL-FEED-COMPLETE-0: no raise when last status is BLOCKED."""
    engine = _engine()
    evt = _evt(status="BLOCKED", prev_hmac="")
    engine.publish_sync(evt)
    engine.assert_cycle_concluded()


@pytest.mark.T148
def test_lef23_assert_cycle_concluded_raises_on_running():
    """CEL-FEED-COMPLETE-0: raise LEFFeedIncomplete if status=RUNNING."""
    engine = _engine()
    evt = _evt(status="RUNNING", prev_hmac="")
    engine.publish_sync(evt)
    with pytest.raises(LEFFeedIncomplete):
        engine.assert_cycle_concluded()


@pytest.mark.T148
def test_lef24_assert_cycle_concluded_raises_on_none():
    """CEL-FEED-COMPLETE-0: raise LEFFeedIncomplete if no events published."""
    engine = _engine()
    with pytest.raises(LEFFeedIncomplete):
        engine.assert_cycle_concluded()


@pytest.mark.T148
def test_lef25_terminal_statuses_set():
    """CEL-FEED-COMPLETE-0: TERMINAL_STATUSES contains COMPLETE and BLOCKED."""
    assert "COMPLETE" in TERMINAL_STATUSES
    assert "BLOCKED" in TERMINAL_STATUSES
    assert "RUNNING" not in TERMINAL_STATUSES


# ===========================================================================
# Group 5: Ledger verification
# ===========================================================================


@pytest.mark.T148
def test_lef26_verify_ledger_chain_no_ledger():
    """Verify returns ok=True with events=0 when ledger absent."""
    engine = _engine()
    result = engine.verify_ledger_chain()
    assert result["ok"] is True
    assert result["events"] == 0


@pytest.mark.T148
def test_lef27_verify_ledger_chain_valid():
    """Verify returns ok=True after valid sequential events."""
    engine = _engine()
    e1 = _evt(step=1, prev_hmac="")
    engine.publish_sync(e1)
    e2 = _evt(step=2, prev_hmac=e1.event_hmac)
    engine.publish_sync(e2)
    result = engine.verify_ledger_chain()
    assert result["ok"] is True
    assert result["events"] == 2


@pytest.mark.T148
def test_lef28_health_check_returns_dict():
    """health_check() returns a dict with required keys."""
    engine = _engine()
    h = engine.health_check()
    assert h["ok"] is True
    assert "events_published" in h
    assert "phase" in h
    assert "chain_tail" in h


# ===========================================================================
# Group 6: INNOV-54 registry wrapper
# ===========================================================================


@pytest.mark.T148
def test_lef29_innov54_registry_entry():
    """INNOV-54 registry_entry() contains required fields."""
    entry = registry_entry()
    assert entry["id"] == "INNOV-54"
    assert entry["phase"] == 148
    assert len(entry["invariants"]) == 5
    assert "GET /events/cel-feed" in entry["endpoints"]


@pytest.mark.T148
def test_lef30_make_event_convenience_factory():
    """make_event() creates a valid CELStepEvent with correct fields."""
    evt = make_event(phase=148, step=1, status="RUNNING", agent="Architect", description="init", prev_hmac="")
    assert evt.phase == 148
    assert evt.step == 1
    assert evt.status == "RUNNING"
    assert len(evt.event_hmac) == 64
    d = evt._canonical_dict()
    assert list(d.keys()) == sorted(d.keys())


@pytest.mark.T148
def test_lef31_probe_uses_requested_phase(monkeypatch: pytest.MonkeyPatch):
    """INNOV-54: probe() resolves engine using the requested phase."""
    requested_phase = 2148
    captured: dict[str, int] = {}

    class _FakeEngine:
        def health_check(self):
            return {"ok": True, "events_published": 0, "chain_tail": ""}

    def _fake_get_engine(phase: int):
        captured["phase"] = phase
        return _FakeEngine()

    monkeypatch.setattr("runtime.innovations30.live_execution_feed.get_engine", _fake_get_engine)
    result = probe(requested_phase)
    assert captured["phase"] == requested_phase
    assert result["ok"] is True
    assert result["phase"] == requested_phase
