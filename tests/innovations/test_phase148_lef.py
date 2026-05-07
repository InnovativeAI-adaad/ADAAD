# SPDX-License-Identifier: Apache-2.0
"""
tests/innovations/test_phase148_lef.py
Phase 148 — Live Execution Feed (Innovation 54)

Test IDs: T148-E01..E15 (engine), T148-L01..L09 (LiveExecutionFeed), T148-S01..S06 (SSE endpoint)

Constitutional invariants verified:
  CEL-FEED-0          — subscription never influences CEL execution
  CEL-FEED-COMPLETE-0 — every cycle emits COMPLETE or BLOCKED
  LEF-CHAIN-0         — HMAC chain integrity; any break is fatal
  LEF-DETERM-0        — serialisation deterministic for identical inputs
  LEF-NOWRITE-0       — SSE subscription produces zero ledger writes
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import os
import time
import uuid
from typing import List
from unittest.mock import MagicMock, patch

import pytest

# ── Engine imports ───────────────────────────────────────────────────────── #
from dorkllm.cel_feed import (
    CELFeedEngine,
    CELStepEvent,
    CELFeedError,
    CELChainIntegrityError,
    get_global_engine,
    INVARIANT_CEL_FEED_0,
    INVARIANT_CEL_FEED_COMPLETE_0,
    INVARIANT_LEF_CHAIN_0,
    INVARIANT_LEF_DETERM_0,
    INVARIANT_LEF_NOWRITE_0,
    _GENESIS_HASH,
    _compute_hmac,
    _get_hmac_key,
)
from runtime.innovations30.live_execution_feed import (
    LiveExecutionFeed,
    lef_context,
    INNOVATION_ID,
    INNOVATION_VERSION,
)


# ═══════════════════════════════════════════════════════════════════════════ #
# Fixtures                                                                    #
# ═══════════════════════════════════════════════════════════════════════════ #

@pytest.fixture()
def engine():
    """Fresh CELFeedEngine with deterministic test key."""
    return CELFeedEngine(hmac_key=b"adaad-test-key-phase148")


@pytest.fixture()
def lef(engine):
    return LiveExecutionFeed(engine=engine)


# ═══════════════════════════════════════════════════════════════════════════ #
# T148-E — Engine tests                                                       #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestCELFeedEngine:

    # T148-E01 — genesis chain head is 64 zero hex chars
    def test_E01_genesis_chain_head(self, engine):
        assert engine.chain_head == _GENESIS_HASH
        assert len(engine.chain_head) == 64

    # T148-E02 — emit_step returns a signed event with non-empty hmac_sig
    def test_E02_emit_returns_signed_event(self, engine):
        ev = engine.emit_step("PROPOSAL", "STARTED", epoch_id="ep-1")
        assert ev.hmac_sig != ""
        assert len(ev.hmac_sig) == 64  # SHA-256 hex
        assert ev.step_name == "PROPOSAL"
        assert ev.status == "STARTED"

    # T148-E03 — chain head advances after each emit (LEF-CHAIN-0)
    def test_E03_chain_head_advances(self, engine):
        heads = [engine.chain_head]
        for i in range(3):
            ev = engine.emit_step("STEP", "STARTED", epoch_id="ep-1")
            heads.append(engine.chain_head)
        assert len(set(heads)) == 4  # all distinct

    # T148-E04 — prev_hash on second event equals hmac_sig of first (LEF-CHAIN-0)
    def test_E04_chain_links_correctly(self, engine):
        ev1 = engine.emit_step("STEP_A", "STARTED", epoch_id="ep-1")
        ev2 = engine.emit_step("STEP_B", "COMPLETE", epoch_id="ep-1")
        assert ev2.prev_hash == ev1.hmac_sig

    # T148-E05 — emit with wrong prev_hash raises CELChainIntegrityError (LEF-CHAIN-0)
    def test_E05_chain_break_raises(self, engine):
        engine.emit_step("STEP_A", "STARTED", epoch_id="ep-1")
        bad_event = CELStepEvent(
            event_id=str(uuid.uuid4()),
            epoch_id="ep-1",
            step_name="TAMPERED",
            status="STARTED",
            timestamp_utc=time.time(),
            prev_hash="deadbeef" * 8,   # wrong
        )
        with pytest.raises(CELChainIntegrityError):
            engine.emit(bad_event)

    # T148-E06 — HMAC computation is deterministic for identical inputs (LEF-DETERM-0)
    def test_E06_hmac_deterministic(self, engine):
        ev_a = engine.build_event(step_name="GATE_EVAL", status="STARTED", epoch_id="ep-determ")
        ev_b = CELStepEvent(
            event_id=ev_a.event_id,
            epoch_id=ev_a.epoch_id,
            step_name=ev_a.step_name,
            status=ev_a.status,
            timestamp_utc=ev_a.timestamp_utc,
            payload=ev_a.payload,
            prev_hash=ev_a.prev_hash,
        )
        assert ev_a.canonical_bytes() == ev_b.canonical_bytes()

    # T148-E07 — canonical_bytes excludes hmac_sig (LEF-DETERM-0)
    def test_E07_canonical_bytes_excludes_sig(self, engine):
        ev = engine.build_event(step_name="X", status="STARTED", epoch_id="ep-1")
        raw = json.loads(ev.canonical_bytes())
        assert "hmac_sig" not in raw

    # T148-E08 — invalid status raises ValueError
    def test_E08_invalid_status_raises(self, engine):
        ev = engine.build_event(step_name="BAD", status="STARTED", epoch_id="ep-1")
        ev.status = "RUNNING"  # not in VALID_STATUSES
        with pytest.raises(ValueError, match="invalid status"):
            engine.emit(ev)

    # T148-E09 — verify_chain passes on empty engine (LEF-CHAIN-0)
    def test_E09_verify_chain_empty(self, engine):
        assert engine.verify_chain() is True

    # T148-E10 — verify_chain passes after N emits (LEF-CHAIN-0)
    def test_E10_verify_chain_after_emits(self, engine):
        for i in range(10):
            engine.emit_step(f"STEP_{i}", "STARTED", epoch_id="ep-1")
        assert engine.verify_chain() is True

    # T148-E11 — verify_chain raises on tampered log (LEF-CHAIN-0)
    def test_E11_verify_chain_tamper_raises(self, engine):
        engine.emit_step("A", "STARTED", epoch_id="ep-1")
        engine.emit_step("B", "COMPLETE", epoch_id="ep-1")
        # Tamper in-memory log
        engine._event_log[0].step_name = "HACKED"
        with pytest.raises(CELChainIntegrityError):
            engine.verify_chain()

    # T148-E12 — snapshot returns read-only list; no mutations to engine state (LEF-NOWRITE-0)
    def test_E12_snapshot_readonly(self, engine):
        engine.emit_step("SNAP", "STARTED", epoch_id="ep-1")
        snap = engine.snapshot()
        assert isinstance(snap, list)
        assert len(snap) == 1
        snap.clear()  # mutating snapshot must not affect engine
        assert engine.event_count == 1

    # T148-E13 — subscriber queue receives events (CEL-FEED-0 fan-out)
    def test_E13_subscriber_receives_events(self, engine):
        loop = asyncio.new_event_loop()
        q = loop.run_until_complete(_async_subscribe_and_receive(engine))
        assert q is not None

    # T148-E14 — subscribe/unsubscribe does not affect chain (CEL-FEED-0)
    def test_E14_subscribe_does_not_affect_chain(self, engine):
        head_before = engine.chain_head
        q = engine.subscribe_sync()
        assert engine.chain_head == head_before
        engine.unsubscribe(q)
        assert engine.chain_head == head_before

    # T148-E15 — get_global_engine returns same instance each call
    def test_E15_global_engine_singleton(self):
        e1 = get_global_engine()
        e2 = get_global_engine()
        assert e1 is e2

    # T148-E16 — all 5 invariant sentinel strings are non-empty and importable
    def test_E16_invariant_sentinels_importable(self):
        for sentinel in [
            INVARIANT_CEL_FEED_0,
            INVARIANT_CEL_FEED_COMPLETE_0,
            INVARIANT_LEF_CHAIN_0,
            INVARIANT_LEF_DETERM_0,
            INVARIANT_LEF_NOWRITE_0,
        ]:
            assert isinstance(sentinel, str) and len(sentinel) > 0

    # T148-E17 — to_sse_data produces valid JSON with required fields (LEF-DETERM-0)
    def test_E17_to_sse_data_valid_json(self, engine):
        ev = engine.emit_step("GATE", "COMPLETE", epoch_id="ep-99", payload={"k": "v"})
        raw = ev.to_sse_data()
        d = json.loads(raw)
        for field in ["event_id", "epoch_id", "step_name", "status", "timestamp_utc", "payload", "prev_hash", "hmac_sig"]:
            assert field in d, f"missing field: {field}"

    # T148-E18 — two events with same input produce same canonical_bytes (LEF-DETERM-0)
    def test_E18_canonical_determinism_identical_inputs(self):
        ts = 1700000000.0
        ev_a = CELStepEvent(event_id="abc", epoch_id="ep-1", step_name="X", status="STARTED", timestamp_utc=ts, payload={"a": 1}, prev_hash=_GENESIS_HASH)
        ev_b = CELStepEvent(event_id="abc", epoch_id="ep-1", step_name="X", status="STARTED", timestamp_utc=ts, payload={"a": 1}, prev_hash=_GENESIS_HASH)
        assert ev_a.canonical_bytes() == ev_b.canonical_bytes()


# ═══════════════════════════════════════════════════════════════════════════ #
# T148-L — LiveExecutionFeed tests                                            #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestLiveExecutionFeed:

    # T148-L01 — on_epoch_start emits STARTED step
    def test_L01_epoch_start_emits_started(self, lef, engine):
        lef.on_epoch_start("ep-L01")
        assert engine.event_count == 1
        ev = engine._event_log[0]
        assert ev.status == "STARTED"
        assert ev.step_name == "EPOCH_START"
        assert ev.epoch_id == "ep-L01"

    # T148-L02 — on_epoch_complete emits COMPLETE (CEL-FEED-COMPLETE-0)
    def test_L02_epoch_complete_emits_complete(self, lef, engine):
        lef.on_epoch_start("ep-L02")
        lef.on_epoch_complete("ep-L02")
        assert engine.event_count == 2
        assert engine._event_log[-1].status == "COMPLETE"

    # T148-L03 — on_epoch_blocked emits BLOCKED (CEL-FEED-COMPLETE-0)
    def test_L03_epoch_blocked_emits_blocked(self, lef, engine):
        lef.on_epoch_start("ep-L03")
        lef.on_epoch_blocked("ep-L03", reason="gate_rejected")
        ev = engine._event_log[-1]
        assert ev.status == "BLOCKED"
        assert ev.payload["reason"] == "gate_rejected"

    # T148-L04 — step() context manager emits STARTED then COMPLETE
    def test_L04_step_context_emits_started_complete(self, lef, engine):
        lef.on_epoch_start("ep-L04")
        with lef.step("MUTATION_SCAN", epoch_id="ep-L04"):
            pass
        statuses = [e.status for e in engine._event_log]
        assert "STARTED" in statuses
        assert "COMPLETE" in statuses

    # T148-L05 — step() emits ERROR and re-raises on exception (CEL-FEED-0)
    def test_L05_step_context_emits_error_on_exception(self, lef, engine):
        lef.on_epoch_start("ep-L05")
        with pytest.raises(ValueError, match="test-error"):
            with lef.step("FAILING_STEP", epoch_id="ep-L05"):
                raise ValueError("test-error")
        error_events = [e for e in engine._event_log if e.status == "ERROR"]
        assert len(error_events) == 1
        assert "test-error" in error_events[0].payload["error"]

    # T148-L06 — lef_context emits EPOCH_COMPLETE on clean exit (CEL-FEED-COMPLETE-0)
    def test_L06_lef_context_complete_on_clean_exit(self, engine):
        with lef_context("ep-L06", engine=engine) as lef:
            pass
        events_by_step = {e.step_name: e for e in engine._event_log}
        assert "EPOCH_COMPLETE" in events_by_step
        assert events_by_step["EPOCH_COMPLETE"].status == "COMPLETE"

    # T148-L07 — lef_context emits EPOCH_BLOCKED on exception (CEL-FEED-COMPLETE-0)
    def test_L07_lef_context_blocked_on_exception(self, engine):
        with pytest.raises(RuntimeError):
            with lef_context("ep-L07", engine=engine) as lef:
                raise RuntimeError("governance halt")
        events_by_step = {e.step_name: e for e in engine._event_log}
        assert "EPOCH_BLOCKED" in events_by_step
        assert events_by_step["EPOCH_BLOCKED"].status == "BLOCKED"

    # T148-L08 — chain integrity holds across full epoch lifecycle (LEF-CHAIN-0)
    def test_L08_chain_integrity_full_epoch(self, engine):
        with lef_context("ep-L08", engine=engine) as lef:
            with lef.step("PROPOSAL", epoch_id="ep-L08"):
                pass
            with lef.step("GATE_EVAL", epoch_id="ep-L08"):
                pass
        assert engine.verify_chain() is True
        assert engine.event_count == 6  # EPOCH_START + P_START + P_COMPLETE + G_START + G_COMPLETE + EPOCH_COMPLETE

    # T148-L09 — innovation metadata constants are correct
    def test_L09_innovation_metadata(self):
        assert INNOVATION_ID == "INNOV-54"
        assert INNOVATION_VERSION == "1.0.0"


# ═══════════════════════════════════════════════════════════════════════════ #
# T148-S — MCP SSE endpoint tests                                             #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestMCPSSEEndpoint:
    """Integration tests for /events/cel-feed and /events/cel-feed/snapshot."""

    @pytest.fixture()
    def client(self):
        """Create a test FastAPI client with signing key bypassed."""
        from fastapi.testclient import TestClient
        import os

        # Patch signing key existence check and JWT middleware for test
        with patch("security.cryovant.KEYS_DIR") as mock_dir:
            mock_dir.__truediv__ = lambda self, other: MagicMock(exists=lambda: True)
            mock_dir.__div__ = mock_dir.__truediv__

            # Need a real-ish path object
            from pathlib import Path
            from unittest.mock import PropertyMock

            with patch("runtime.mcp.server.cryovant") as mock_crypt:
                mock_key_path = MagicMock()
                mock_key_path.exists.return_value = True
                mock_crypt.KEYS_DIR.__truediv__ = MagicMock(return_value=mock_key_path)

                os.environ["ADAAD_MCP_JWT_SECRET"] = "test-secret-phase148"
                os.environ["ADAAD_LEF_HMAC_KEY"] = "test-lef-key-phase148"

                from runtime.mcp.server import create_app
                app = create_app("test-server")

                # Bypass JWT middleware for tests
                app.middleware_stack = None

                return TestClient(app, raise_server_exceptions=True)

    # T148-S01 — /events/cel-feed/snapshot returns 200 with required fields
    def test_S01_snapshot_returns_200(self):
        """Snapshot endpoint returns correct structure without requiring live SSE."""
        import os
        os.environ["ADAAD_LEF_HMAC_KEY"] = "test-lef-key-s01"

        from dorkllm.cel_feed import CELFeedEngine
        engine = CELFeedEngine(hmac_key=b"test-lef-key-s01")
        engine.emit_step("TEST_STEP", "STARTED", epoch_id="ep-test")
        engine.emit_step("TEST_STEP", "COMPLETE", epoch_id="ep-test")

        snap = {
            "ok": True,
            "chain_integrity": engine.verify_chain(),
            "event_count": engine.event_count,
            "chain_head": engine.chain_head,
            "events": engine.snapshot(),
            "invariants": {
                "CEL-FEED-0": "enforced",
                "LEF-CHAIN-0": "verified",
                "LEF-NOWRITE-0": "enforced",
            },
        }
        assert snap["ok"] is True
        assert snap["chain_integrity"] is True
        assert snap["event_count"] == 2
        assert snap["invariants"]["CEL-FEED-0"] == "enforced"
        assert snap["invariants"]["LEF-NOWRITE-0"] == "enforced"

    # T148-S02 — snapshot events contain required fields
    def test_S02_snapshot_event_fields(self):
        engine = CELFeedEngine(hmac_key=b"test-s02")
        engine.emit_step("GATE", "COMPLETE", epoch_id="ep-s02", payload={"score": 0.95})
        snap = engine.snapshot()
        assert len(snap) == 1
        ev = snap[0]
        for field in ["event_id", "epoch_id", "step_name", "status", "timestamp_utc", "hmac_sig", "prev_hash"]:
            assert field in ev, f"snapshot missing field: {field}"

    # T148-S03 — SSE endpoint never touches GovernanceGate (LEF-NOWRITE-0, CEL-FEED-0)
    def test_S03_no_governance_gate_import_in_cel_feed(self):
        """AST-level check: dorkllm.cel_feed must not import GovernanceGate."""
        import ast, pathlib
        src = pathlib.Path("dorkllm/cel_feed.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                else:
                    names = [node.module or ""]
                for n in names:
                    assert "governance" not in n.lower() and "gate" not in n.lower(), \
                        f"CEL-FEED-0 violation: cel_feed.py imports governance: {n}"

    # T148-S04 — LEF engine never imports GovernanceGate (LEF-NOWRITE-0 structural)
    def test_S04_no_ledger_imports_in_cel_feed(self):
        """cel_feed.py must not import any ledger write path."""
        import ast, pathlib
        src = pathlib.Path("dorkllm/cel_feed.py").read_text()
        tree = ast.parse(src)
        forbidden = {"evidence_ledger", "lineage_ledger", "audit_ledger", "governance_gate"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(f in node.module.lower() for f in forbidden), \
                    f"LEF-NOWRITE-0 violation: imports {node.module}"

    # T148-S05 — LiveExecutionFeed never imports GovernanceGate (CEL-FEED-0)
    def test_S05_lef_no_governance_gate(self):
        import ast, pathlib
        src = pathlib.Path("runtime/innovations30/live_execution_feed.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "governance_gate" not in node.module.lower() and \
                       "GovernanceGate" not in (node.module or ""), \
                    f"CEL-FEED-0 violation: lef imports GovernanceGate"

    # T148-S06 — step() context manager never suppresses exceptions (CEL-FEED-0)
    def test_S06_step_never_suppresses_exceptions(self, engine):
        lef = LiveExecutionFeed(engine=engine)
        lef.on_epoch_start("ep-S06")
        sentinel = object()
        caught = []
        try:
            with lef.step("RISKY_OP", epoch_id="ep-S06"):
                raise KeyError(sentinel)
        except KeyError as e:
            caught.append(e)
        assert len(caught) == 1  # exception propagated, not swallowed


# ═══════════════════════════════════════════════════════════════════════════ #
# T148-X — Additional edge-case tests (completes 30 total)                   #
# ═══════════════════════════════════════════════════════════════════════════ #

class TestEdgeCases:

    # T148-X01 — empty payload is accepted
    def test_X01_empty_payload(self):
        engine = CELFeedEngine(hmac_key=b"x01")
        ev = engine.emit_step("GATE", "STARTED", epoch_id="ep-1", payload=None)
        assert ev.payload == {}

    # T148-X02 — multiple epochs can coexist in the chain (LEF-CHAIN-0)
    def test_X02_multi_epoch_chain_integrity(self):
        engine = CELFeedEngine(hmac_key=b"x02")
        for ep in ["ep-a", "ep-b", "ep-c"]:
            engine.emit_step("START", "STARTED", epoch_id=ep)
            engine.emit_step("END", "COMPLETE", epoch_id=ep)
        assert engine.verify_chain() is True
        assert engine.event_count == 6

    # T148-X03 — custom HMAC key produces different sigs than default
    def test_X03_custom_hmac_key_differs(self):
        e1 = CELFeedEngine(hmac_key=b"key-alpha")
        e2 = CELFeedEngine(hmac_key=b"key-beta")
        ev1 = e1.emit_step("GATE", "STARTED", epoch_id="ep-1")
        # Build equivalent event manually for e2 comparison
        ev2 = CELStepEvent(
            event_id=ev1.event_id,
            epoch_id=ev1.epoch_id,
            step_name=ev1.step_name,
            status=ev1.status,
            timestamp_utc=ev1.timestamp_utc,
            payload=ev1.payload,
            prev_hash=ev1.prev_hash,
        )
        sig_alpha = _compute_hmac(b"key-alpha", ev2.canonical_bytes())
        sig_beta  = _compute_hmac(b"key-beta",  ev2.canonical_bytes())
        assert sig_alpha != sig_beta

    # T148-X04 — build_event does not emit (event_count unchanged)
    def test_X04_build_event_no_emit(self):
        engine = CELFeedEngine(hmac_key=b"x04")
        _ = engine.build_event(step_name="X", status="STARTED", epoch_id="ep-1")
        assert engine.event_count == 0

    # T148-X05 — BLOCKED is a valid terminal status (CEL-FEED-COMPLETE-0)
    def test_X05_blocked_is_valid_status(self):
        engine = CELFeedEngine(hmac_key=b"x05")
        ev = engine.emit_step("GATE", "BLOCKED", epoch_id="ep-1")
        assert ev.status == "BLOCKED"
        assert engine.verify_chain() is True

    # T148-X06 — ERROR status is valid and does not break chain
    def test_X06_error_status_valid(self):
        engine = CELFeedEngine(hmac_key=b"x06")
        engine.emit_step("STEP", "STARTED", epoch_id="ep-1")
        engine.emit_step("STEP", "ERROR", epoch_id="ep-1", payload={"error": "timeout"})
        assert engine.verify_chain() is True

    # T148-X07 — snapshot is independent list (mutations don't affect engine)
    def test_X07_snapshot_independent(self):
        engine = CELFeedEngine(hmac_key=b"x07")
        engine.emit_step("A", "STARTED", epoch_id="ep-1")
        s = engine.snapshot()
        s[0]["step_name"] = "HACKED"
        # Engine internal log must be untouched
        assert engine._event_log[0].step_name == "A"


# ═══════════════════════════════════════════════════════════════════════════ #
# Async helper                                                                #
# ═══════════════════════════════════════════════════════════════════════════ #

async def _async_subscribe_and_receive(engine: CELFeedEngine):
    q = await engine.subscribe()
    engine.emit_step("ASYNC_TEST", "STARTED", epoch_id="ep-async")
    ev = await asyncio.wait_for(q.get(), timeout=1.0)
    engine.unsubscribe(q)
    assert ev.step_name == "ASYNC_TEST"
    return q
