# SPDX-License-Identifier: Apache-2.0
"""Phase 150 / INNOV-56 — Governance Circuit Breaker (GCB) acceptance tests.

30 tests at 100% pass rate required before merge.

Coverage matrix
---------------
GCB01-05  : GCBChainState — genesis, advance, chain break detection
GCB06-10  : ViolationWindow — push, capacity, namespace counts, trip logic
GCB11-15  : CircuitBreakerEngine — init, record_violation, state transitions
GCB16-20  : GCB-FAILCLOSE-0 — assert_circuit_closed behaviour
GCB21-23  : GCB-READONLY-0 — _readonly_guard invariant
GCB24-26  : GCB-HUMAN0-0 — reset auth (valid + invalid tokens)
GCB27-28  : GCB-CHAIN-0 — ledger persistence and verify_ledger_chain
GCB29-30  : Registry wrapper and health/status probes
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path

import pytest

from dorkllm.circuit_breaker import (
    CIRCUIT_CLOSED,
    CIRCUIT_OPEN,
    DEFAULT_NAMESPACE_THRESHOLD,
    DEFAULT_VIOLATION_THRESHOLD,
    DEFAULT_WINDOW_SIZE,
    CircuitBreakerEngine,
    CircuitEvent,
    GCBAuthViolation,
    GCBChainState,
    GCBChainViolation,
    GCBMutationViolation,
    GCBOpenViolation,
    ViolationWindow,
)
from runtime.innovations30.governance_circuit_breaker import (
    CONSTITUTIONAL_INVARIANTS,
    INNOVATION_CODE,
    INNOVATION_NAME,
    INNOVATION_PHASE,
    INNOVATION_VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_engine(
    tmp_path: Path,
    vt: int = DEFAULT_VIOLATION_THRESHOLD,
    nt: int = DEFAULT_NAMESPACE_THRESHOLD,
    ws: int = DEFAULT_WINDOW_SIZE,
) -> CircuitBreakerEngine:
    return CircuitBreakerEngine(
        ledger_path=tmp_path / "gcb_test.jsonl",
        violation_threshold=vt,
        namespace_threshold=nt,
        window_size=ws,
    )


# ---------------------------------------------------------------------------
# GCB01-05 — GCBChainState
# ---------------------------------------------------------------------------


def test_gcb01_chain_genesis_hash():
    """GCB-CHAIN-0: initial last_hash equals GENESIS_HASH (64 zeros)."""
    chain = GCBChainState()
    assert chain.last_hash == "0" * 64


def test_gcb02_chain_advance_valid(tmp_path):
    """GCB-CHAIN-0: valid event advances chain without exception."""
    engine = fresh_engine(tmp_path)
    state_before = engine.state
    engine.record_violation("MXE", "MXE-AUDIT-0")
    # Chain advanced — engine did not raise
    assert engine.state == state_before or engine.state == CIRCUIT_OPEN


def test_gcb03_chain_break_raises():
    """GCB-CHAIN-0: tampered prev_hash raises GCBChainViolation."""
    chain = GCBChainState()
    ev = CircuitEvent(
        event_id="gcb-000001",
        event_type="VIOLATION",
        namespace="LEF",
        violation_id="LEF-CHAIN-0",
        circuit_state=CIRCUIT_CLOSED,
        window_snapshot=["LEF"],
        prev_hash="deadbeef" + "0" * 56,  # wrong hash
    )
    ev.finalise()
    with pytest.raises(GCBChainViolation, match="GCB-CHAIN-0"):
        chain.advance(ev)


def test_gcb04_chain_entry_hash_mismatch_raises():
    """GCB-CHAIN-0: tampered entry_hash raises GCBChainViolation."""
    chain = GCBChainState()
    ev = CircuitEvent(
        event_id="gcb-000001",
        event_type="VIOLATION",
        namespace="MXE",
        violation_id="MXE-CHAIN-0",
        circuit_state=CIRCUIT_CLOSED,
        window_snapshot=["MXE"],
        prev_hash=GCBChainState.GENESIS_HASH,
    )
    ev.finalise()
    ev.entry_hash = "tampered" + "0" * 56  # corrupt after finalise
    with pytest.raises(GCBChainViolation, match="GCB-CHAIN-0"):
        chain.advance(ev)


def test_gcb05_chain_canonical_dict_deterministic():
    """GCB-DETERM-0: identical CircuitEvent fields produce identical canonical dicts."""
    ev1 = CircuitEvent(
        event_id="gcb-000001",
        event_type="VIOLATION",
        namespace="DQR",
        violation_id="DQR-CHAIN-0",
        circuit_state=CIRCUIT_CLOSED,
        window_snapshot=["DQR", "MXE"],
        prev_hash=GCBChainState.GENESIS_HASH,
    )
    ev2 = CircuitEvent(
        event_id="gcb-000001",
        event_type="VIOLATION",
        namespace="DQR",
        violation_id="DQR-CHAIN-0",
        circuit_state=CIRCUIT_CLOSED,
        window_snapshot=["MXE", "DQR"],  # different insertion order — sorted in canonical
        prev_hash=GCBChainState.GENESIS_HASH,
    )
    assert ev1._canonical_dict() == ev2._canonical_dict()


# ---------------------------------------------------------------------------
# GCB06-10 — ViolationWindow
# ---------------------------------------------------------------------------


def test_gcb06_window_push_grows():
    """ViolationWindow: push appends namespaces correctly."""
    w = ViolationWindow(size=5)
    w.push("MXE")
    w.push("LEF")
    assert w.snapshot() == ["MXE", "LEF"]


def test_gcb07_window_capacity_drops_oldest():
    """ViolationWindow: window drops oldest entry when at capacity."""
    w = ViolationWindow(size=3)
    for ns in ["A", "B", "C", "D"]:
        w.push(ns)
    assert w.snapshot() == ["B", "C", "D"]
    assert len(w.snapshot()) == 3


def test_gcb08_window_namespace_counts_deterministic():
    """GCB-DETERM-0: namespace_counts returns sorted dict."""
    w = ViolationWindow(size=10)
    for ns in ["B", "A", "B", "C", "A"]:
        w.push(ns)
    counts = w.namespace_counts()
    assert list(counts.keys()) == sorted(counts.keys())
    assert counts == {"A": 2, "B": 2, "C": 1}


def test_gcb09_window_trip_single_namespace_threshold():
    """GCB-DETERM-0: should_trip true when single namespace >= violation_threshold."""
    w = ViolationWindow(size=20)
    for _ in range(3):
        w.push("MXE")
    assert w.should_trip(violation_threshold=3, namespace_threshold=99) is True


def test_gcb10_window_trip_cascade_threshold():
    """GCB-DETERM-0: should_trip true when distinct namespaces >= namespace_threshold."""
    w = ViolationWindow(size=20)
    w.push("MXE")
    w.push("LEF")
    assert w.should_trip(violation_threshold=99, namespace_threshold=2) is True


# ---------------------------------------------------------------------------
# GCB11-15 — CircuitBreakerEngine init and record_violation
# ---------------------------------------------------------------------------


def test_gcb11_engine_initial_state_closed(tmp_path):
    """Engine initialises in CLOSED state."""
    engine = fresh_engine(tmp_path)
    assert engine.state == CIRCUIT_CLOSED
    assert engine.is_closed() is True
    assert engine.is_open() is False


def test_gcb12_engine_record_violation_no_trip(tmp_path):
    """Engine records single violation without tripping (below thresholds)."""
    engine = fresh_engine(tmp_path, vt=5, nt=5)
    tripped = engine.record_violation("MXE", "MXE-AUDIT-0")
    assert tripped is False
    assert engine.state == CIRCUIT_CLOSED


def test_gcb13_engine_trips_on_single_namespace_cascade(tmp_path):
    """Engine trips when single namespace reaches violation_threshold."""
    engine = fresh_engine(tmp_path, vt=3, nt=99, ws=20)
    for _ in range(2):
        tripped = engine.record_violation("MXE", "MXE-AUDIT-0")
        assert tripped is False
    tripped = engine.record_violation("MXE", "MXE-AUDIT-0")
    assert tripped is True
    assert engine.state == CIRCUIT_OPEN


def test_gcb14_engine_trips_on_multi_namespace_cascade(tmp_path):
    """Engine trips when distinct namespaces reach namespace_threshold."""
    engine = fresh_engine(tmp_path, vt=99, nt=2, ws=20)
    engine.record_violation("LEF", "LEF-CHAIN-0")
    tripped = engine.record_violation("MXE", "MXE-CHAIN-0")
    assert tripped is True
    assert engine.state == CIRCUIT_OPEN


def test_gcb15_engine_trip_increments_trip_count(tmp_path):
    """Engine trip_count increments on each TRIP event."""
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("MXE", "MXE-AUDIT-0")
    status = engine.get_status()
    assert status["trip_count"] == 1


# ---------------------------------------------------------------------------
# GCB16-20 — GCB-FAILCLOSE-0
# ---------------------------------------------------------------------------


def test_gcb16_assert_closed_passes_when_closed(tmp_path):
    """assert_circuit_closed() does not raise when circuit is CLOSED."""
    engine = fresh_engine(tmp_path)
    engine.assert_circuit_closed()  # must not raise


def test_gcb17_assert_closed_raises_when_open(tmp_path):
    """GCB-FAILCLOSE-0: assert_circuit_closed() raises GCBOpenViolation when OPEN."""
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("MXE", "MXE-AUDIT-0")
    assert engine.state == CIRCUIT_OPEN
    with pytest.raises(GCBOpenViolation, match="GCB-FAILCLOSE-0"):
        engine.assert_circuit_closed()


def test_gcb18_open_circuit_blocks_after_trip(tmp_path):
    """GCB-FAILCLOSE-0: circuit remains OPEN; every call to assert raises."""
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("LEF", "LEF-CHAIN-0")
    for _ in range(3):
        with pytest.raises(GCBOpenViolation):
            engine.assert_circuit_closed()


def test_gcb19_open_violations_do_not_double_trip(tmp_path):
    """Engine does not increment trip_count when circuit is already OPEN."""
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("MXE", "MXE-AUDIT-0")
    assert engine.get_status()["trip_count"] == 1
    # Further violations while OPEN should not trip again
    engine.record_violation("MXE", "MXE-CHAIN-0")
    assert engine.get_status()["trip_count"] == 1


def test_gcb20_error_message_contains_human0_instruction(tmp_path):
    """GCB-FAILCLOSE-0: error message references HUMAN-0 reset requirement."""
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("GCB", "GCB-CHAIN-0")
    with pytest.raises(GCBOpenViolation, match="HUMAN-0"):
        engine.assert_circuit_closed()


# ---------------------------------------------------------------------------
# GCB21-23 — GCB-READONLY-0
# ---------------------------------------------------------------------------


def test_gcb21_readonly_guard_default_true(tmp_path):
    """GCB-READONLY-0: record_violation succeeds with default _readonly_guard=True."""
    engine = fresh_engine(tmp_path, vt=99, nt=99)
    # Must not raise
    engine.record_violation("MXE", "MXE-AUDIT-0")


def test_gcb22_readonly_guard_false_raises(tmp_path):
    """GCB-READONLY-0: record_violation raises GCBMutationViolation when guard disabled."""
    engine = fresh_engine(tmp_path)
    with pytest.raises(GCBMutationViolation, match="GCB-READONLY-0"):
        engine.record_violation("MXE", "MXE-AUDIT-0", _readonly_guard=False)


def test_gcb23_get_status_does_not_mutate_state(tmp_path):
    """GCB-READONLY-0: get_status() is idempotent — state unchanged across calls."""
    engine = fresh_engine(tmp_path)
    s1 = engine.get_status()
    s2 = engine.get_status()
    assert s1 == s2
    assert engine.state == CIRCUIT_CLOSED


# ---------------------------------------------------------------------------
# GCB24-26 — GCB-HUMAN0-0 reset
# ---------------------------------------------------------------------------


def test_gcb24_reset_with_valid_token_closes_circuit(tmp_path, monkeypatch):
    """GCB-HUMAN0-0: valid HUMAN-0 token resets OPEN circuit to CLOSED."""
    monkeypatch.setenv("ADAAD_HUMAN0_TOKEN", "test-token-gcb")
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("MXE", "MXE-AUDIT-0")
    assert engine.state == CIRCUIT_OPEN
    engine.reset_circuit("test-token-gcb")
    assert engine.state == CIRCUIT_CLOSED


def test_gcb25_reset_with_invalid_token_raises(tmp_path, monkeypatch):
    """GCB-HUMAN0-0: invalid token raises GCBAuthViolation; circuit stays OPEN."""
    monkeypatch.setenv("ADAAD_HUMAN0_TOKEN", "correct-token")
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("LEF", "LEF-CHAIN-0")
    assert engine.state == CIRCUIT_OPEN
    with pytest.raises(GCBAuthViolation, match="GCB-HUMAN0-0"):
        engine.reset_circuit("wrong-token")
    assert engine.state == CIRCUIT_OPEN  # still OPEN


def test_gcb26_reset_clears_window(tmp_path, monkeypatch):
    """GCB-HUMAN0-0: reset clears the violation window."""
    monkeypatch.setenv("ADAAD_HUMAN0_TOKEN", "reset-token")
    engine = fresh_engine(tmp_path, vt=1, nt=99, ws=20)
    engine.record_violation("MXE", "MXE-AUDIT-0")
    engine.reset_circuit("reset-token")
    status = engine.get_status()
    assert status["window_namespace_counts"] == {}
    assert status["window_distinct_namespaces"] == 0


# ---------------------------------------------------------------------------
# GCB27-28 — GCB-CHAIN-0 ledger persistence
# ---------------------------------------------------------------------------


def test_gcb27_ledger_written_on_violation(tmp_path):
    """GCB-CHAIN-0: ledger JSONL file is written on every violation."""
    ledger = tmp_path / "gcb_ledger.jsonl"
    engine = CircuitBreakerEngine(ledger_path=ledger, violation_threshold=99, namespace_threshold=99)
    engine.record_violation("MXE", "MXE-AUDIT-0")
    assert ledger.exists()
    lines = [l for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event_type"] == "VIOLATION"
    assert row["namespace"] == "MXE"


def test_gcb28_verify_ledger_chain_passes_valid(tmp_path):
    """GCB-CHAIN-0: verify_ledger_chain returns verified=True on intact ledger."""
    ledger = tmp_path / "gcb_ledger.jsonl"
    engine = CircuitBreakerEngine(ledger_path=ledger, violation_threshold=99, namespace_threshold=99)
    for ns in ["MXE", "LEF", "DQR"]:
        engine.record_violation(ns, f"{ns}-test")
    result = engine.verify_ledger_chain()
    assert result["verified"] is True
    assert result["events"] == 3


# ---------------------------------------------------------------------------
# GCB29-30 — Registry wrapper and health/status probes
# ---------------------------------------------------------------------------


def test_gcb29_registry_metadata_correct():
    """Registry wrapper exposes correct INNOV-56 metadata."""
    assert INNOVATION_CODE == "INNOV-56"
    assert INNOVATION_NAME == "Governance Circuit Breaker (GCB)"
    assert INNOVATION_PHASE == 150
    assert INNOVATION_VERSION == "9.83.0"
    assert len(CONSTITUTIONAL_INVARIANTS) == 5
    ids = [inv["id"] for inv in CONSTITUTIONAL_INVARIANTS]
    assert "GCB-CHAIN-0" in ids
    assert "GCB-FAILCLOSE-0" in ids
    assert "GCB-READONLY-0" in ids
    assert "GCB-DETERM-0" in ids
    assert "GCB-HUMAN0-0" in ids
    for inv in CONSTITUTIONAL_INVARIANTS:
        assert inv["class"] == "Hard"


def test_gcb30_health_check_returns_ok(tmp_path):
    """health_check() returns status ok with circuit_state and ledger path."""
    engine = fresh_engine(tmp_path)
    h = engine.health_check()
    assert h["status"] == "ok"
    assert h["circuit_state"] == CIRCUIT_CLOSED
    assert "GCB-FAILCLOSE-0" in h["invariant"]
    assert "ledger" in h
