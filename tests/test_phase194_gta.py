# SPDX-License-Identifier: Apache-2.0
"""
Phase 194 · INNOV-99 · GTA — Governed Telemetry Aggregator
Acceptance test suite — 30 tests (T194-GTA-01 … T194-GTA-30)

Coverage:
  T01–T05  Invariant registry & constants
  T06–T09  GTA-EMIT-0  — silence detection and escalation
  T10–T13  GTA-CHAIN-0 — HMAC chain sealing and verification
  T14–T16  GTA-HUMAN0-0 — threshold violation, latch, clearance
  T17–T18  GTA-IMMUT-0  — append-only ledger
  T19–T20  GTA-DETERM-0 — deterministic aggregation records
  T21–T22  GTA-SCOPE-0  — out-of-scope rejection
  T23–T25  GTA-AUDIT-0  — lifecycle event logging
  T26–T27  GTA-ATOMIC-0 — partial failure journal unchanged
  T28–T29  GTA-REPLAY-0 — replay attestation
  T30      End-to-end multi-cycle constitutional telemetry pipeline
"""

from __future__ import annotations

import hashlib
import time
import uuid

import pytest

from dorkllm.governed_telemetry_aggregator import (
    CONSTITUTIONAL_SOURCES,
    DEFAULT_THRESHOLDS,
    GENESIS_HMAC,
    HARD_CLASS,
    HMAC_SECRET,
    INVARIANT_COUNT,
    INVARIANTS,
    AggregationRecord,
    AggregationStatus,
    AuditEvent,
    GTAAtomicViolation,
    GTAChainViolation,
    GTAEmitViolation,
    GTAHuman0Flag,
    GTANoModViolation,
    GTAReplayFailure,
    GTAScopeViolation,
    GovernedTelemetryAggregator,
    MetricStatus,
    TelemetryEvent,
    make_event,
    make_gta,
)

pytestmark = pytest.mark.phase194


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def gta():
    return make_gta()


@pytest.fixture
def clean_events():
    return [
        make_event("MSR", "latency_p99_ms", 100.0, "cycle-test"),
        make_event("CMO", "error_rate", 0.01, "cycle-test"),
    ]


@pytest.fixture
def violating_events():
    # error_rate threshold is 0.05 — this exceeds it
    return [make_event("MSR", "error_rate", 0.99, "cycle-bad")]


# ── T01–T05: Invariant registry & constants ───────────────────────────────────

def test_T194_GTA_01_invariant_count():
    """GTA: exactly 10 hard-class invariants registered."""
    assert INVARIANT_COUNT == 10
    assert len(INVARIANTS) == 10


def test_T194_GTA_02_invariant_codes():
    """All 10 canonical GTA invariant codes present."""
    expected = {
        "GTA-EMIT-0", "GTA-CHAIN-0", "GTA-HUMAN0-0", "GTA-IMMUT-0",
        "GTA-DETERM-0", "GTA-SCOPE-0", "GTA-AUDIT-0", "GTA-ATOMIC-0",
        "GTA-NOMOD-0", "GTA-REPLAY-0",
    }
    assert set(INVARIANTS) == expected


def test_T194_GTA_03_hard_class():
    """HARD_CLASS constant is 'Hard'."""
    assert HARD_CLASS == "Hard"


def test_T194_GTA_04_constitutional_sources():
    """CONSTITUTIONAL_SOURCES contains at least the 10 core pipeline modules."""
    required = {"MSR", "MSE", "MRP", "MEX", "MFV", "MCE", "MPG", "CMO", "CIL", "ILV"}
    assert required.issubset(CONSTITUTIONAL_SOURCES)


def test_T194_GTA_05_genesis_hmac():
    """GENESIS_HMAC is the 64-zero-char sentinel."""
    assert GENESIS_HMAC == "0" * 64


# ── T06–T09: GTA-EMIT-0 ───────────────────────────────────────────────────────

def test_T194_GTA_06_registered_silent_source_triggers_violation(gta):
    """GTA-EMIT-0: registered source that emits nothing is flagged as violation."""
    gta.register_source("MSR")
    # Send events from CMO only — MSR is silent
    events = [make_event("CMO", "error_rate", 0.01, "cycle-x")]
    rec = gta.aggregate(events, "cycle-x")
    assert "MSR" in rec.sources_silent
    assert rec.violation_count >= 1


def test_T194_GTA_07_silent_source_escalates_human0(gta):
    """GTA-EMIT-0: silent registered source escalates to HUMAN-0."""
    gta.register_source("MEX")
    events = [make_event("MSR", "latency_p99_ms", 50.0, "cycle-y")]
    gta.aggregate(events, "cycle-y")
    assert gta.human0_flagged


def test_T194_GTA_08_unregistered_source_not_silent(gta):
    """GTA-EMIT-0: unregistered sources are not tracked for silence."""
    # No sources registered — empty registered_sources
    events = [make_event("MSR", "latency_p99_ms", 50.0, "cycle-z")]
    rec = gta.aggregate(events, "cycle-z")
    assert rec.sources_silent == []
    assert rec.violation_count == 0


def test_T194_GTA_09_emitting_registered_source_not_flagged(gta):
    """GTA-EMIT-0: registered source that does emit is not flagged."""
    gta.register_source("CMO")
    events = [make_event("CMO", "error_rate", 0.01, "cycle-ok")]
    rec = gta.aggregate(events, "cycle-ok")
    assert "CMO" not in rec.sources_silent


# ── T10–T13: GTA-CHAIN-0 ─────────────────────────────────────────────────────

def test_T194_GTA_10_first_record_uses_genesis_hmac(gta, clean_events):
    """GTA-CHAIN-0: first ledger entry uses GENESIS_HMAC as prev_hmac."""
    rec = gta.aggregate(clean_events, "cycle-1")
    assert rec.prev_hmac == GENESIS_HMAC


def test_T194_GTA_11_second_record_chains_to_first(gta):
    """GTA-CHAIN-0: second record's prev_hmac equals first record's hmac."""
    e1 = [make_event("MSR", "latency_p99_ms", 10.0, "c1")]
    e2 = [make_event("CMO", "error_rate", 0.01, "c2")]
    r1 = gta.aggregate(e1, "c1")
    r2 = gta.aggregate(e2, "c2")
    assert r2.prev_hmac == r1.hmac


def test_T194_GTA_12_chain_verify_intact(gta):
    """GTA-CHAIN-0: verify_ledger_chain() returns True for intact ledger."""
    for src, cy in [("MSR", "c1"), ("CMO", "c2"), ("MEX", "c3")]:
        gta.aggregate([make_event(src, "error_rate", 0.01, cy)], cy)
    assert gta.verify_ledger_chain() is True


def test_T194_GTA_13_tampered_chain_raises(gta, clean_events):
    """GTA-CHAIN-0: verify_ledger_chain raises GTAChainViolation on tamper."""
    gta.aggregate(clean_events, "c1")
    # Tamper the stored hmac directly
    gta._ledger[0].hmac = "badhmacsignature" * 4
    with pytest.raises(GTAChainViolation):
        gta.verify_ledger_chain()


# ── T14–T16: GTA-HUMAN0-0 ────────────────────────────────────────────────────

def test_T194_GTA_14_threshold_breach_sets_human0_flag(gta, violating_events):
    """GTA-HUMAN0-0: metric exceeding threshold sets HUMAN-0 flag."""
    gta.aggregate(violating_events, "cycle-bad")
    assert gta.human0_flagged


def test_T194_GTA_15_human0_flag_blocks_new_aggregation(gta, violating_events, clean_events):
    """GTA-HUMAN0-0: subsequent aggregate() raises GTAHuman0Flag while set."""
    gta.aggregate(violating_events, "cycle-bad")
    with pytest.raises(GTAHuman0Flag):
        gta.aggregate(clean_events, "cycle-ok")


def test_T194_GTA_16_acknowledge_clears_flag_and_resumes(gta, violating_events, clean_events):
    """GTA-HUMAN0-0: acknowledge_human0() clears flag; aggregation resumes."""
    gta.aggregate(violating_events, "cycle-bad")
    gta.acknowledge_human0("DUSTIN-L-REID-GTA-001")
    assert not gta.human0_flagged
    rec = gta.aggregate(clean_events, "cycle-ok")
    assert rec.status == AggregationStatus.SEALED


# ── T17–T18: GTA-IMMUT-0 ─────────────────────────────────────────────────────

def test_T194_GTA_17_ledger_property_returns_copy(gta, clean_events):
    """GTA-IMMUT-0: ledger property returns a list copy."""
    gta.aggregate(clean_events, "c1")
    assert gta.ledger is not gta.ledger
    assert gta.ledger == gta.ledger


def test_T194_GTA_18_ledger_grows_monotonically(gta):
    """GTA-IMMUT-0: ledger entries accumulate; earlier records unchanged."""
    recs = []
    for src, cy in [("MSR", "c1"), ("CMO", "c2"), ("MEX", "c3")]:
        recs.append(gta.aggregate([make_event(src, "error_rate", 0.01, cy)], cy))
    ledger = gta.ledger
    for i, rec in enumerate(recs):
        assert ledger[i].record_id == rec.record_id
        assert ledger[i].hmac == rec.hmac


# ── T19–T20: GTA-DETERM-0 ────────────────────────────────────────────────────

def test_T194_GTA_19_identical_inputs_identical_hmac():
    """GTA-DETERM-0: identical AggregationRecord fields produce identical HMACs."""
    ts = 1_700_000_000.0

    def make_rec():
        r = AggregationRecord(
            record_id="rid-fixed", cycle_id="c-fixed",
            event_count=1, sources_seen=["MSR"], sources_silent=[],
            violation_count=0, verdicts=[],
            status=AggregationStatus.SEALED,
            constitutional_seal="seal001",
            timestamp=ts, prev_hmac=GENESIS_HMAC,
        )
        r.seal()
        return r

    assert make_rec().hmac == make_rec().hmac


def test_T194_GTA_20_different_cycle_id_different_hmac():
    """GTA-DETERM-0: different cycle_id produces different HMAC."""
    ts = 1_700_000_000.0

    def make_rec(cy):
        r = AggregationRecord(
            record_id="rid-fixed", cycle_id=cy,
            event_count=1, sources_seen=["MSR"], sources_silent=[],
            violation_count=0, verdicts=[],
            status=AggregationStatus.SEALED,
            constitutional_seal="seal001",
            timestamp=ts, prev_hmac=GENESIS_HMAC,
        )
        r.seal()
        return r

    assert make_rec("A").hmac != make_rec("B").hmac


# ── T21–T22: GTA-SCOPE-0 ─────────────────────────────────────────────────────

def test_T194_GTA_21_out_of_scope_event_raises(gta):
    """GTA-SCOPE-0: event from unknown source raises GTAScopeViolation."""
    bad_event = TelemetryEvent(
        event_id=str(uuid.uuid4()), source="ROGUE_MODULE",
        cycle_id="c1", metric_name="error_rate",
        metric_value=0.01, unit="ratio", timestamp=time.time(),
    )
    with pytest.raises(GTAScopeViolation):
        gta.aggregate([bad_event], "c1")


def test_T194_GTA_22_out_of_scope_leaves_ledger_empty(gta):
    """GTA-SCOPE-0: scope rejection leaves ledger unchanged."""
    bad_event = TelemetryEvent(
        event_id=str(uuid.uuid4()), source="EXTERNAL_SERVICE",
        cycle_id="c1", metric_name="error_rate",
        metric_value=0.0, unit="ratio", timestamp=time.time(),
    )
    try:
        gta.aggregate([bad_event], "c1")
    except GTAScopeViolation:
        pass
    assert len(gta.ledger) == 0


# ── T23–T25: GTA-AUDIT-0 ─────────────────────────────────────────────────────

def test_T194_GTA_23_audit_log_populated(gta, clean_events):
    """GTA-AUDIT-0: aggregate() emits audit events."""
    gta.aggregate(clean_events, "c1")
    assert len(gta.audit_log) > 0


def test_T194_GTA_24_audit_contains_received_event(gta, clean_events):
    """GTA-AUDIT-0: RECEIVED event appears for each aggregation."""
    gta.aggregate(clean_events, "c1")
    types = [e.event_type for e in gta.audit_log]
    assert AggregationStatus.RECEIVED in types


def test_T194_GTA_25_violation_audit_contains_escalated(gta, violating_events):
    """GTA-AUDIT-0: ESCALATED event logged for threshold breach."""
    gta.aggregate(violating_events, "cycle-bad")
    types = [e.event_type for e in gta.audit_log]
    assert AggregationStatus.ESCALATED in types


# ── T26–T27: GTA-ATOMIC-0 ────────────────────────────────────────────────────

def test_T194_GTA_26_atomic_failure_leaves_ledger_unchanged(gta, monkeypatch):
    """GTA-ATOMIC-0: _atomic_aggregate failure leaves ledger unchanged."""
    def _bad(*a, **kw):
        raise RuntimeError("simulated mid-aggregate failure")
    monkeypatch.setattr(gta, "_atomic_aggregate", _bad)
    with pytest.raises(GTAAtomicViolation):
        gta.aggregate([make_event("MSR", "error_rate", 0.01, "c1")], "c1")
    assert len(gta.ledger) == 0


def test_T194_GTA_27_atomic_failure_does_not_set_human0(gta, monkeypatch):
    """GTA-ATOMIC-0: atomic failure does not set the HUMAN-0 flag."""
    def _bad(*a, **kw):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(gta, "_atomic_aggregate", _bad)
    with pytest.raises(GTAAtomicViolation):
        gta.aggregate([make_event("MSR", "error_rate", 0.01, "c1")], "c1")
    assert gta.human0_flagged is False


# ── T28–T29: GTA-REPLAY-0 ────────────────────────────────────────────────────

def test_T194_GTA_28_replay_valid_record(gta, clean_events):
    """GTA-REPLAY-0: replay_record() returns True for a genuine record."""
    rec = gta.aggregate(clean_events, "c1")
    assert gta.replay_record(rec) is True


def test_T194_GTA_29_replay_tampered_record_raises(gta, clean_events):
    """GTA-REPLAY-0: replay_record() raises GTAReplayFailure for tampered HMAC."""
    rec = gta.aggregate(clean_events, "c1")
    object.__setattr__(rec, "hmac", "badhmacsignature" * 4)
    with pytest.raises(GTAReplayFailure):
        gta.replay_record(rec)


# ── T30: End-to-end multi-cycle constitutional telemetry pipeline ─────────────

def test_T194_GTA_30_end_to_end_multi_cycle_pipeline():
    """
    End-to-end: 3 clean cycles, 1 threshold breach, HUMAN-0 escalation,
    acknowledgement, resume — chain verified throughout, all records replayable.
    """
    gta = make_gta()
    gta.register_source("MSR")
    gta.register_source("CMO")

    # 1. Three clean cycles
    for i in range(1, 4):
        cy = f"cycle-{i:03d}"
        events = [
            make_event("MSR", "latency_p99_ms", 50.0 * i, cy),
            make_event("CMO", "error_rate", 0.01, cy),
        ]
        rec = gta.aggregate(events, cy)
        assert rec.status == AggregationStatus.SEALED
        assert rec.violation_count == 0

    # 2. Threshold breach — triggers HUMAN-0
    bad_events = [
        make_event("MSR", "error_rate", 0.99, "cycle-bad"),   # >> 0.05 threshold
        make_event("CMO", "error_rate", 0.01, "cycle-bad"),
    ]
    rec_bad = gta.aggregate(bad_events, "cycle-bad")
    assert rec_bad.status == AggregationStatus.ESCALATED
    assert gta.human0_flagged

    # 3. New aggregation blocked
    with pytest.raises(GTAHuman0Flag):
        gta.aggregate([make_event("MSR", "latency_p99_ms", 10.0, "c-x")], "c-x")

    # 4. HUMAN-0 acknowledges
    gta.acknowledge_human0("HUMAN-0-GTA-RATIFICATION-DUSTIN-REID")
    assert not gta.human0_flagged

    # 5. Resume — clean cycle accepted
    clean = [
        make_event("MSR", "latency_p99_ms", 30.0, "cycle-005"),
        make_event("CMO", "error_rate", 0.02, "cycle-005"),
    ]
    rec_clean = gta.aggregate(clean, "cycle-005")
    assert rec_clean.status == AggregationStatus.SEALED

    # 6. Full chain intact across all 5 entries
    assert gta.verify_ledger_chain() is True
    assert len(gta.ledger) == 5

    # 7. All records replayable
    for record in gta.ledger:
        assert gta.replay_record(record) is True

    # 8. Health summary reflects recovered state
    summary = gta.health_summary()
    assert summary["record_count"] == 5
    assert not summary["human0_flagged"]
