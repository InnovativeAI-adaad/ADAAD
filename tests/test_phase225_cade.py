# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase225_cade.py
Phase 225 · INNOV-130 · CADE — Constitutional Autonomous Decision Engine
30-test acceptance suite · T225-CADE-01 through T225-CADE-30

Author : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID
Arc III — Autonomous Constitutional Intelligence (ACI) · Module 01
"""

from __future__ import annotations

import time
import uuid
import pytest

from dorkllm.constitutional_autonomous_decision_engine import (
    AttestationEngine,
    CADEEngine,
    CADEViolation,
    ChainBreakError,
    AppendViolation,
    GateBlockError,
    HUMAN0VetoError,
    ImmutabilityViolation,
    OriginViolation,
    ScopeViolation,
    DecisionVerdict,
    DecisionState,
    DecisionLedger,
    DecisionAuditor,
    DecisionMatrix,
    DecisionRecord,
    PROMOTE_THRESHOLD,
    HOLD_THRESHOLD,
    _DECISION_CLASSES,
)

pytestmark = pytest.mark.phase225


# ── Fixtures ───────────────────────────────────────────────────────────────────
@pytest.fixture
def engine() -> CADEEngine:
    return CADEEngine()


@pytest.fixture
def synth_id() -> str:
    return f"CASL-SYNTH-{uuid.uuid4().hex[:12]}"


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-01  Module import and engine instantiation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_01_engine_instantiation():
    """T225-CADE-01: CADEEngine instantiates without error."""
    eng = CADEEngine()
    assert eng is not None


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-02  CADE-SCOPE-0: exactly 3 decision classes
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_02_scope_exactly_three_classes():
    """T225-CADE-02: CADE-SCOPE-0 — exactly 3 decision classes."""
    assert len(_DECISION_CLASSES) == 3
    assert "PROMOTE" in _DECISION_CLASSES
    assert "HOLD" in _DECISION_CLASSES
    assert "REJECT" in _DECISION_CLASSES


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-03  CADE-GATE-0: high CHI → PROMOTE
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_03_promote_on_high_chi(engine, synth_id):
    """T225-CADE-03: CADE-GATE-0 — CHI ≥ PROMOTE_THRESHOLD → PROMOTE."""
    record = engine.evaluate(synth_id, 0.95, "mut-001")
    assert record.verdict == DecisionVerdict.PROMOTE


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-04  CADE-GATE-0: boundary CHI → PROMOTE
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_04_promote_on_boundary_chi(engine, synth_id):
    """T225-CADE-04: CADE-GATE-0 — CHI == PROMOTE_THRESHOLD → PROMOTE."""
    record = engine.evaluate(synth_id, PROMOTE_THRESHOLD, "mut-002")
    assert record.verdict == DecisionVerdict.PROMOTE


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-05  CADE-GATE-0: mid CHI → HOLD
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_05_hold_on_mid_chi(engine, synth_id):
    """T225-CADE-05: CADE-GATE-0 — HOLD_THRESHOLD ≤ CHI < PROMOTE_THRESHOLD → HOLD."""
    record = engine.evaluate(synth_id, 0.65, "mut-003")
    assert record.verdict == DecisionVerdict.HOLD


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-06  CADE-GATE-0: low CHI → REJECT
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_06_reject_on_low_chi(engine, synth_id):
    """T225-CADE-06: CADE-GATE-0 — CHI < HOLD_THRESHOLD → REJECT."""
    record = engine.evaluate(synth_id, 0.20, "mut-004")
    assert record.verdict == DecisionVerdict.REJECT


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-07  CADE-ORIGIN-0: empty synthesis_id rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_07_origin_empty_synthesis_id(engine):
    """T225-CADE-07: CADE-ORIGIN-0 — empty synthesis_id raises OriginViolation."""
    with pytest.raises(OriginViolation):
        engine.evaluate("", 0.90, "mut-005")


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-08  CADE-ORIGIN-0: whitespace-only synthesis_id rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_08_origin_whitespace_synthesis_id(engine):
    """T225-CADE-08: CADE-ORIGIN-0 — whitespace-only synthesis_id rejected."""
    with pytest.raises(OriginViolation):
        engine.evaluate("   ", 0.90, "mut-006")


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-09  CADE-DETERM-0: identical inputs → identical verdict
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_09_determinism(engine, synth_id):
    """T225-CADE-09: CADE-DETERM-0 — identical CHI → identical verdict."""
    r1 = engine.evaluate(synth_id, 0.85, "mut-007")
    r2 = engine.evaluate(synth_id, 0.85, "mut-008")
    assert r1.verdict == r2.verdict == DecisionVerdict.PROMOTE


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-10  CADE-ATTEST-0: PROMOTE carries non-empty attestation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_10_attest_promote_non_empty(engine, synth_id):
    """T225-CADE-10: CADE-ATTEST-0 — PROMOTE decision has non-empty attestation."""
    record = engine.evaluate(synth_id, 0.90, "mut-009")
    assert record.verdict == DecisionVerdict.PROMOTE
    assert len(record.attestation_hmac) == 64   # SHA-256 hex


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-11  CADE-ATTEST-0: HOLD has empty attestation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_11_attest_hold_empty(engine, synth_id):
    """T225-CADE-11: CADE-ATTEST-0 — HOLD decision has empty attestation."""
    record = engine.evaluate(synth_id, 0.65, "mut-010")
    assert record.verdict == DecisionVerdict.HOLD
    assert record.attestation_hmac == ""


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-12  CADE-ATTEST-0: REJECT has empty attestation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_12_attest_reject_empty(engine, synth_id):
    """T225-CADE-12: CADE-ATTEST-0 — REJECT decision has empty attestation."""
    record = engine.evaluate(synth_id, 0.20, "mut-011")
    assert record.verdict == DecisionVerdict.REJECT
    assert record.attestation_hmac == ""


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-13  CADE-ATTEST-0: verify_attestation returns True for PROMOTE
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_13_verify_attestation_promote(engine, synth_id):
    """T225-CADE-13: CADE-ATTEST-0 — verify_attestation True for valid PROMOTE."""
    record = engine.evaluate(synth_id, 0.95, "mut-012")
    assert engine.verify_attestation(record.record_id) is True


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-14  CADE-ATTEST-0: verify_attestation returns False for HOLD
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_14_verify_attestation_hold_false(engine, synth_id):
    """T225-CADE-14: CADE-ATTEST-0 — verify_attestation False for HOLD."""
    record = engine.evaluate(synth_id, 0.65, "mut-013")
    assert engine.verify_attestation(record.record_id) is False


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-15  CADE-CHAIN-0: verify_chain on single entry
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_15_chain_single_entry(engine, synth_id):
    """T225-CADE-15: CADE-CHAIN-0 — chain valid after single evaluate."""
    engine.evaluate(synth_id, 0.90, "mut-014")
    result = engine.verify_chain()
    assert result["overall_valid"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-16  CADE-CHAIN-0: verify_chain across multiple decisions
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_16_chain_multiple_entries(engine, synth_id):
    """T225-CADE-16: CADE-CHAIN-0 — chain valid after multiple evaluations."""
    for i, score in enumerate([0.95, 0.70, 0.30, 0.85, 0.50]):
        engine.evaluate(synth_id, score, f"mut-{i:03d}")
    result = engine.verify_chain()
    assert result["overall_valid"] is True
    assert result["ledger_chain_valid"] is True
    assert result["audit_chain_valid"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-17  CADE-APPEND-0: duplicate record_id raises AppendViolation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_17_append_duplicate_blocked():
    """T225-CADE-17: CADE-APPEND-0 — sealing duplicate record_id raises AppendViolation."""
    ledger = DecisionLedger()
    record = DecisionRecord(
        record_id="test-dup",
        synthesis_id="syn-001",
        chi_score=0.9,
        verdict=DecisionVerdict.PROMOTE,
        mutation_ref="mut-dup",
        attestation_hmac="abc",
        sealed_ts=time.time(),
    )
    ledger.seal(record)
    with pytest.raises(AppendViolation):
        ledger.seal(record)


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-18  CADE-HUMAN0-0: veto empty veto_by raises HUMAN0VetoError
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_18_human0_veto_empty_veto_by(engine, synth_id):
    """T225-CADE-18: CADE-HUMAN0-0 — empty veto_by raises HUMAN0VetoError."""
    record = engine.evaluate(synth_id, 0.90, "mut-015")
    with pytest.raises(HUMAN0VetoError):
        engine.veto(record.record_id, "", "reason")


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-19  CADE-HUMAN0-0: veto non-PROMOTE raises HUMAN0VetoError
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_19_human0_veto_non_promote_blocked(engine, synth_id):
    """T225-CADE-19: CADE-HUMAN0-0 — vetoing a HOLD raises HUMAN0VetoError."""
    record = engine.evaluate(synth_id, 0.65, "mut-016")
    assert record.verdict == DecisionVerdict.HOLD
    with pytest.raises(HUMAN0VetoError):
        engine.veto(record.record_id, "DUSTIN L REID", "reason")


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-20  CADE-HUMAN0-0: valid veto transitions state to VETOED
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_20_human0_veto_valid(engine, synth_id):
    """T225-CADE-20: CADE-HUMAN0-0 — valid veto transitions state to VETOED."""
    record = engine.evaluate(synth_id, 0.90, "mut-017")
    assert record.verdict == DecisionVerdict.PROMOTE
    entry = engine.veto(record.record_id, "DUSTIN L REID", "test veto")
    assert entry.record.state == DecisionState.VETOED
    assert entry.record.veto_by == "DUSTIN L REID"


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-21  CADE-HUMAN0-0: double veto raises HUMAN0VetoError
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_21_human0_double_veto_blocked(engine, synth_id):
    """T225-CADE-21: CADE-HUMAN0-0 — double veto raises HUMAN0VetoError."""
    record = engine.evaluate(synth_id, 0.90, "mut-018")
    engine.veto(record.record_id, "DUSTIN L REID", "first veto")
    with pytest.raises(HUMAN0VetoError):
        engine.veto(record.record_id, "DUSTIN L REID", "second veto")


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-22  CADE-AUDIT-0: evaluate logged to audit
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_22_audit_evaluate_logged(engine, synth_id):
    """T225-CADE-22: CADE-AUDIT-0 — evaluate logs an EVALUATE audit entry."""
    before = len(engine.all_audit_entries())
    engine.evaluate(synth_id, 0.85, "mut-019")
    after = len(engine.all_audit_entries())
    assert after > before
    ops = [e.operation for e in engine.all_audit_entries()]
    assert "EVALUATE" in ops


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-23  CADE-AUDIT-0: veto logged to audit
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_23_audit_veto_logged(engine, synth_id):
    """T225-CADE-23: CADE-AUDIT-0 — veto logs a HUMAN0_VETO audit entry."""
    record = engine.evaluate(synth_id, 0.90, "mut-020")
    engine.veto(record.record_id, "DUSTIN L REID", "audit test")
    ops = [e.operation for e in engine.all_audit_entries()]
    assert "HUMAN0_VETO" in ops


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-24  CADE-AUDIT-0: verify_chain logged to audit
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_24_audit_verify_chain_logged(engine, synth_id):
    """T225-CADE-24: CADE-AUDIT-0 — verify_chain logs a VERIFY_CHAIN audit entry."""
    engine.evaluate(synth_id, 0.85, "mut-021")
    engine.verify_chain()
    ops = [e.operation for e in engine.all_audit_entries()]
    assert "VERIFY_CHAIN" in ops


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-25  CADE-IMMUT-0: record_id preserved in ledger
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_25_immutability_record_id(engine, synth_id):
    """T225-CADE-25: CADE-IMMUT-0 — record_id preserved unchanged in ledger."""
    record = engine.evaluate(synth_id, 0.90, "mut-022")
    retrieved = engine.get_decision(record.record_id)
    assert retrieved is not None
    assert retrieved.record_id == record.record_id
    assert retrieved.chi_score == record.chi_score


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-26  all_decisions returns correct count
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_26_all_decisions_count(engine, synth_id):
    """T225-CADE-26: all_decisions returns all sealed records."""
    n = 5
    for i in range(n):
        engine.evaluate(synth_id, 0.85, f"mut-{i:03d}")
    decisions = engine.all_decisions()
    assert len(decisions) == n


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-27  status endpoint returns invariant roster
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_27_status_invariant_roster(engine):
    """T225-CADE-27: status() reports exactly 10 Hard-class invariants."""
    st = engine.status()
    assert "invariants" in st
    assert len(st["invariants"]) == 10


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-28  matrix thresholds correct
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_28_matrix_thresholds(engine):
    """T225-CADE-28: matrix() returns correct PROMOTE and HOLD thresholds."""
    m = engine.matrix()
    assert m["promote_threshold"] == PROMOTE_THRESHOLD
    assert m["hold_threshold"] == HOLD_THRESHOLD
    assert len(m["rules"]) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-29  AttestationEngine: direct verify round-trip
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_29_attestation_engine_roundtrip():
    """T225-CADE-29: CADE-ATTEST-0 — AttestationEngine verify round-trips correctly."""
    record_id = str(uuid.uuid4())
    synth_id = "CASL-TEST-001"
    chi = 0.92
    hmac_val = AttestationEngine.attest(record_id, synth_id, chi)
    assert len(hmac_val) == 64
    assert AttestationEngine.verify(record_id, synth_id, chi, hmac_val) is True
    assert AttestationEngine.verify(record_id, synth_id, 0.50, hmac_val) is False


# ═══════════════════════════════════════════════════════════════════════════════
# T225-CADE-30  CADE-CHAIN-0: DecisionAuditor chain verifies standalone
# ═══════════════════════════════════════════════════════════════════════════════
def test_T225_CADE_30_auditor_chain_standalone():
    """T225-CADE-30: CADE-CHAIN-0 — DecisionAuditor standalone chain verification."""
    auditor = DecisionAuditor()
    for i in range(5):
        auditor.record("TEST_OP", decision_id=None, detail={"i": i})
    ok, msg = auditor.verify_chain()
    assert ok is True
    assert "VALID" in msg
