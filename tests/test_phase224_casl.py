# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase224_casl.py
Phase 224 · INNOV-129 · CASL — Constitutional Arc Synthesis Layer
30-test acceptance suite · T224-CASL-01 through T224-CASL-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import time
import uuid
from pathlib import Path

import pytest

from dorkllm.constitutional_arc_synthesis_layer import (
    ARC_II_DOMAINS,
    ArcSynthesisCollector,
    CASLEngine,
    CASLViolation,
    ChainBreakError,
    CHIComputationError,
    ConstitutionalHealthIndexEngine,
    DomainSignal,
    DomainSignalStatus,
    ImmutabilityViolation,
    OriginViolation,
    ScopeViolation,
    SynthesisGateError,
    SynthesisLedger,
    CASLAuditor,
    VerificationFailure,
    _HMAC_SECRET,
)

pytestmark = pytest.mark.phase224


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_ledger(tmp_path):
    return tmp_path / "test_synthesis_ledger.jsonl"


@pytest.fixture
def tmp_audit(tmp_path):
    return tmp_path / "test_audit_ledger.jsonl"


@pytest.fixture
def engine(tmp_ledger, tmp_audit):
    return CASLEngine(ledger_path=tmp_ledger, audit_path=tmp_audit)


@pytest.fixture
def collector():
    return ArcSynthesisCollector()


@pytest.fixture
def chi_engine():
    return ConstitutionalHealthIndexEngine()


@pytest.fixture
def fully_loaded_engine(engine):
    """Engine with all 9 Arc II domains ingested at HEALTHY status."""
    for domain in ARC_II_DOMAINS:
        signal = ArcSynthesisCollector.make_signal(
            domain=domain,
            status=DomainSignalStatus.HEALTHY,
            health_score=1.0,
            invariant_count=10,
        )
        engine.ingest_signal(signal)
    return engine


# ── T224-CASL-01 : Arc II domain registry contains exactly 9 domains ──────────
def test_T224_CASL_01_domain_count():
    """T224-CASL-01: ARC_II_DOMAINS must contain exactly 9 entries (CASL-SCOPE-0)."""
    assert len(ARC_II_DOMAINS) == 9


# ── T224-CASL-02 : All 9 required domains present in registry ─────────────────
def test_T224_CASL_02_required_domains():
    """T224-CASL-02: All 9 Arc II domains present in registry."""
    required = {"ACSA", "ACPA", "ACAM", "CARE", "CEICC", "CGML", "ACDR", "CPVE", "CASL"}
    assert required == set(ARC_II_DOMAINS)


# ── T224-CASL-03 : make_signal factory produces valid DomainSignal ─────────────
def test_T224_CASL_03_make_signal_factory():
    """T224-CASL-03: ArcSynthesisCollector.make_signal produces a DomainSignal with HMAC."""
    signal = ArcSynthesisCollector.make_signal(
        domain="CGML", status=DomainSignalStatus.HEALTHY, health_score=0.95, invariant_count=12
    )
    assert isinstance(signal, DomainSignal)
    assert signal.domain == "CGML"
    assert len(signal.signal_hmac) == 64  # SHA-256 hex


# ── T224-CASL-04 : ingest_signal verifies HMAC (CASL-VERIFY-0) ────────────────
def test_T224_CASL_04_ingest_verifies_hmac(collector):
    """T224-CASL-04: ingest_signal sets verified=True on good HMAC."""
    signal = ArcSynthesisCollector.make_signal(
        domain="ACSA", status=DomainSignalStatus.HEALTHY, health_score=1.0, invariant_count=5
    )
    collector.ingest_signal(signal)
    assert signal.verified is True


# ── T224-CASL-05 : ingest_signal rejects tampered HMAC (CASL-VERIFY-0) ────────
def test_T224_CASL_05_ingest_rejects_tampered_hmac(collector):
    """T224-CASL-05: ingest_signal raises VerificationFailure for tampered HMAC."""
    signal = ArcSynthesisCollector.make_signal(
        domain="ACPA", status=DomainSignalStatus.HEALTHY, health_score=1.0, invariant_count=5
    )
    signal.signal_hmac = "deadbeef" * 8  # corrupt
    with pytest.raises(VerificationFailure):
        collector.ingest_signal(signal)


# ── T224-CASL-06 : ingest_signal rejects unknown domain (CASL-SCOPE-0) ─────────
def test_T224_CASL_06_ingest_rejects_unknown_domain(collector):
    """T224-CASL-06: ingest_signal raises ScopeViolation for unregistered domain."""
    signal = DomainSignal(
        domain="UNKNOWN",
        status=DomainSignalStatus.HEALTHY,
        health_score=1.0,
        invariant_count=0,
        last_event_ts=time.time(),
        signal_hmac="x" * 64,
        verified=False,
    )
    with pytest.raises(ScopeViolation):
        collector.ingest_signal(signal)


# ── T224-CASL-07 : collect_all fills missing domains with synthetic signals ────
def test_T224_CASL_07_collect_all_fills_missing(collector):
    """T224-CASL-07: collect_all returns 9 signals even with zero ingestions."""
    signals = collector.collect_all()
    assert len(signals) == 9
    domains_covered = {s.domain for s in signals}
    assert domains_covered == set(ARC_II_DOMAINS)


# ── T224-CASL-08 : gate_check passes for all-verified signals (CASL-GATE-0) ───
def test_T224_CASL_08_gate_check_passes(collector):
    """T224-CASL-08: gate_check passes when all signals are verified."""
    signals = collector.collect_all()  # synthetic signals pre-verified
    collector.gate_check(signals)  # must not raise


# ── T224-CASL-09 : gate_check fails for unverified signal (CASL-GATE-0) ───────
def test_T224_CASL_09_gate_check_fails_unverified(collector):
    """T224-CASL-09: gate_check raises SynthesisGateError when signal unverified."""
    signals = collector.collect_all()
    signals[0].verified = False
    with pytest.raises(SynthesisGateError):
        collector.gate_check(signals)


# ── T224-CASL-10 : CHI computation covers all 9 domains (CASL-CHI-0) ──────────
def test_T224_CASL_10_chi_covers_all_domains(chi_engine, collector):
    """T224-CASL-10: compute_chi succeeds only when all 9 domains present."""
    signals = collector.collect_all()
    chi, matrix = chi_engine.compute_chi(signals)
    assert len(matrix) == 9
    assert 0.0 <= chi <= 1.0


# ── T224-CASL-11 : CHI is deterministic (CASL-DETERM-0) ───────────────────────
def test_T224_CASL_11_chi_deterministic(chi_engine, collector):
    """T224-CASL-11: identical signals produce identical CHI."""
    signals = collector.collect_all()
    chi1, matrix1 = chi_engine.compute_chi(signals)
    chi2, matrix2 = chi_engine.compute_chi(signals)
    assert chi1 == chi2
    assert matrix1 == matrix2


# ── T224-CASL-12 : CHI fails when domain missing (CASL-CHI-0) ─────────────────
def test_T224_CASL_12_chi_fails_missing_domain(chi_engine, collector):
    """T224-CASL-12: compute_chi raises CHIComputationError when a domain is missing."""
    signals = collector.collect_all()[:8]  # drop one domain
    with pytest.raises(CHIComputationError):
        chi_engine.compute_chi(signals)


# ── T224-CASL-13 : CHI anchor is deterministic ────────────────────────────────
def test_T224_CASL_13_chi_anchor_deterministic(chi_engine, collector):
    """T224-CASL-13: chi_anchor returns identical string for identical chi/matrix."""
    signals = collector.collect_all()
    chi, matrix = chi_engine.compute_chi(signals)
    anchor1 = chi_engine.chi_anchor(chi, matrix)
    anchor2 = chi_engine.chi_anchor(chi, matrix)
    assert anchor1 == anchor2
    assert len(anchor1) == 64


# ── T224-CASL-14 : VIOLATED domains reduce CHI ────────────────────────────────
def test_T224_CASL_14_violated_domain_reduces_chi(chi_engine):
    """T224-CASL-14: domain with VIOLATED status lowers CHI below all-HEALTHY baseline."""
    healthy_signals = [
        ArcSynthesisCollector.build_synthetic_signal(None, d)  # type: ignore
        for d in ARC_II_DOMAINS
    ]
    # Use collect_all via collector for proper synthetic signals
    coll = ArcSynthesisCollector()
    all_healthy = coll.collect_all()
    chi_healthy, _ = chi_engine.compute_chi(all_healthy)

    coll2 = ArcSynthesisCollector()
    signals_with_violation = coll2.collect_all()
    signals_with_violation[0].status = DomainSignalStatus.VIOLATED
    signals_with_violation[0].health_score = 0.1
    chi_violated, _ = chi_engine.compute_chi(signals_with_violation)

    assert chi_violated < chi_healthy


# ── T224-CASL-15 : SynthesisLedger append-only (CASL-APPEND-0) ────────────────
def test_T224_CASL_15_ledger_append_only(tmp_ledger):
    """T224-CASL-15: SynthesisLedger raises ImmutabilityViolation on re-append."""
    from dorkllm.constitutional_arc_synthesis_layer import SynthesisRecord
    ledger = SynthesisLedger(tmp_ledger)
    coll = ArcSynthesisCollector()
    chi_eng = ConstitutionalHealthIndexEngine()
    signals = coll.collect_all()
    chi, matrix = chi_eng.compute_chi(signals)
    record = SynthesisRecord(
        synthesis_id=str(uuid.uuid4()),
        chi=chi,
        domain_signals=signals,
        arc_health_matrix=matrix,
        provenance_ref="test-ref",
        timestamp=time.time(),
        ledger_hmac="",
        prev_hmac="",
        sealed=False,
    )
    ledger.append(record)
    assert record.sealed is True
    with pytest.raises(ImmutabilityViolation):
        ledger.append(record)


# ── T224-CASL-16 : SynthesisLedger verify_chain passes on empty ledger ─────────
def test_T224_CASL_16_verify_chain_empty(tmp_ledger):
    """T224-CASL-16: verify_chain returns True for empty ledger."""
    ledger = SynthesisLedger(tmp_ledger)
    assert ledger.verify_chain() is True


# ── T224-CASL-17 : SynthesisLedger chain integrity maintained after appends ───
def test_T224_CASL_17_chain_integrity_multi_append(tmp_path):
    """T224-CASL-17: HMAC chain intact after multiple appends (CASL-CHAIN-0)."""
    from dorkllm.constitutional_arc_synthesis_layer import SynthesisRecord
    ledger = SynthesisLedger(tmp_path / "ledger.jsonl")
    coll = ArcSynthesisCollector()
    chi_eng = ConstitutionalHealthIndexEngine()
    signals = coll.collect_all()
    chi, matrix = chi_eng.compute_chi(signals)

    for _ in range(3):
        rec = SynthesisRecord(
            synthesis_id=str(uuid.uuid4()),
            chi=chi,
            domain_signals=signals,
            arc_health_matrix=dict(matrix),
            provenance_ref="test-prov",
            timestamp=time.time(),
            ledger_hmac="",
            prev_hmac="",
            sealed=False,
        )
        ledger.append(rec)

    assert ledger.verify_chain() is True
    assert len(ledger.records) == 3


# ── T224-CASL-18 : CASLAuditor records operations (CASL-AUDIT-0) ───────────────
def test_T224_CASL_18_auditor_records_operations(tmp_audit):
    """T224-CASL-18: CASLAuditor appends entries for every recorded operation."""
    auditor = CASLAuditor(tmp_audit)
    auditor.record("TEST_OP", "DEVADAAD", {"key": "val"})
    auditor.record("ANOTHER_OP", "CASL", {"n": 2})
    assert len(auditor.entries) == 2
    assert auditor.entries[0].operation == "TEST_OP"
    assert auditor.entries[1].operation == "ANOTHER_OP"


# ── T224-CASL-19 : CASLAuditor HMAC chain is valid ─────────────────────────────
def test_T224_CASL_19_auditor_hmac_chain(tmp_audit):
    """T224-CASL-19: Audit log entry HMACs form a valid chain."""
    auditor = CASLAuditor(tmp_audit)
    e1 = auditor.record("OP1", "CASL", {})
    e2 = auditor.record("OP2", "CASL", {})
    assert e2.prev_hmac == e1.entry_hmac


# ── T224-CASL-20 : synthesize requires provenance_ref (CASL-ORIGIN-0) ──────────
def test_T224_CASL_20_synthesize_requires_provenance_ref(engine):
    """T224-CASL-20: synthesize raises OriginViolation with empty provenance_ref."""
    with pytest.raises(OriginViolation):
        engine.synthesize(provenance_ref="")


# ── T224-CASL-21 : synthesize succeeds and returns sealed record ───────────────
def test_T224_CASL_21_synthesize_returns_sealed_record(fully_loaded_engine):
    """T224-CASL-21: synthesize returns a sealed SynthesisRecord."""
    record = fully_loaded_engine.synthesize(provenance_ref="test-prov-ref")
    assert record.sealed is True
    assert record.synthesis_id is not None
    assert 0.0 <= record.chi <= 1.0


# ── T224-CASL-22 : synthesize CHI is 1.0 for all-HEALTHY domains ──────────────
def test_T224_CASL_22_synthesize_chi_all_healthy(fully_loaded_engine):
    """T224-CASL-22: CHI approaches 1.0 when all domains report HEALTHY with score=1.0."""
    record = fully_loaded_engine.synthesize(provenance_ref="healthy-test")
    assert record.chi >= 0.95


# ── T224-CASL-23 : synthesize writes to synthesis ledger ──────────────────────
def test_T224_CASL_23_synthesize_writes_ledger(fully_loaded_engine):
    """T224-CASL-23: After synthesize, ledger contains one record."""
    fully_loaded_engine.synthesize(provenance_ref="ledger-write-test")
    records = fully_loaded_engine.get_synthesis_records()
    assert len(records) == 1


# ── T224-CASL-24 : synthesize writes audit entries (CASL-AUDIT-0) ─────────────
def test_T224_CASL_24_synthesize_writes_audit(fully_loaded_engine):
    """T224-CASL-24: synthesize records SYNTHESIS_START and SYNTHESIS_COMPLETE in audit."""
    fully_loaded_engine.synthesize(provenance_ref="audit-test")
    audit = fully_loaded_engine.get_audit_log()
    ops = [e["operation"] for e in audit]
    assert "SYNTHESIS_START" in ops
    assert "SYNTHESIS_COMPLETE" in ops


# ── T224-CASL-25 : verify_chain returns intact after synthesis ─────────────────
def test_T224_CASL_25_verify_chain_after_synthesis(fully_loaded_engine):
    """T224-CASL-25: verify_chain returns chain_intact=True after synthesis."""
    fully_loaded_engine.synthesize(provenance_ref="chain-verify-test")
    result = fully_loaded_engine.verify_chain()
    assert result["chain_intact"] is True


# ── T224-CASL-26 : get_status returns correct phase and invariant list ─────────
def test_T224_CASL_26_get_status_returns_correct_metadata(engine):
    """T224-CASL-26: get_status returns phase=224 and 10 invariants."""
    status = engine.get_status()
    assert status["phase"] == 224
    assert status["innovation"] == "INNOV-129"
    assert len(status["invariants"]) == 10
    assert "CASL-CHAIN-0" in status["invariants"]


# ── T224-CASL-27 : multiple synthesize calls maintain chain integrity ──────────
def test_T224_CASL_27_multiple_synthesize_chain_integrity(fully_loaded_engine):
    """T224-CASL-27: Three sequential synthesize calls maintain HMAC chain integrity."""
    for i in range(3):
        fully_loaded_engine.synthesize(provenance_ref=f"multi-synth-{i}")
    result = fully_loaded_engine.verify_chain()
    assert result["chain_intact"] is True
    assert result["record_count"] == 3


# ── T224-CASL-28 : get_synthesis_records returns ledger_hmac prefix ───────────
def test_T224_CASL_28_records_include_hmac_prefix(fully_loaded_engine):
    """T224-CASL-28: get_synthesis_records includes truncated ledger_hmac."""
    fully_loaded_engine.synthesize(provenance_ref="hmac-prefix-test")
    records = fully_loaded_engine.get_synthesis_records()
    assert records[0]["ledger_hmac"] != ""
    assert len(records[0]["ledger_hmac"]) == 24


# ── T224-CASL-29 : arc_health_matrix has entry for all 9 domains ──────────────
def test_T224_CASL_29_arc_health_matrix_covers_all_domains(fully_loaded_engine):
    """T224-CASL-29: arc_health_matrix in synthesis record covers all 9 Arc II domains."""
    record = fully_loaded_engine.synthesize(provenance_ref="matrix-coverage-test")
    assert set(record.arc_health_matrix.keys()) == set(ARC_II_DOMAINS)


# ── T224-CASL-30 : CASLViolation is base for all CASL exceptions ──────────────
def test_T224_CASL_30_exception_hierarchy():
    """T224-CASL-30: All CASL exceptions subclass CASLViolation and RuntimeError."""
    exc_classes = [
        ChainBreakError, CHIComputationError, SynthesisGateError,
        ImmutabilityViolation, OriginViolation, VerificationFailure, ScopeViolation,
    ]
    for cls in exc_classes:
        assert issubclass(cls, CASLViolation), f"{cls} must subclass CASLViolation"
        assert issubclass(cls, RuntimeError), f"{cls} must subclass RuntimeError"
