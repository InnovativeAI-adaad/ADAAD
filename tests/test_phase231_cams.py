# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase231_cams.py
Phase 231 · INNOV-136 · CAMS — Constitutional Autonomous Monitoring Sentinel
30-test acceptance suite — T231-CAMS-01 through T231-CAMS-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 07
"""
import hmac as _hmac_mod

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_monitoring_sentinel import (
    CAMSEngine,
    CAMSViolation,
    ChainBreakError,
    SampleError,
    ClassScopeViolation,
    WindowError,
    AlertError,
    HUMAN0AckError,
    ImmutabilityViolation,
    TrendClass,
    AlertState,
    CHIMonitor,
    TrendDetector,
    AlertEngine,
    MonitoringLedger,
    CAMSAuditor,
    _TREND_CLASSES,
    _MIN_WINDOW,
)
from app.api.cams import router

pytestmark = pytest.mark.phase231

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def engine() -> CAMSEngine:
    return CAMSEngine()


def _fill_healthy(eng: CAMSEngine, n: int = _MIN_WINDOW):
    last = None
    for _ in range(n):
        last = eng.sample(0.95, "casl-test")
    return last


def _fill_critical(eng: CAMSEngine, n: int = _MIN_WINDOW):
    last = None
    for _ in range(n):
        last = eng.sample(0.05, "casl-test")
    return last


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-01  Module import and engine instantiation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_01_engine_instantiation():
    """T231-CAMS-01: CAMSEngine instantiates without error."""
    eng = CAMSEngine()
    assert eng is not None


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-02  CAMS-CLASS-0: exactly 3 trend classes
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_02_exactly_three_trend_classes():
    """T231-CAMS-02: CAMS-CLASS-0 — exactly HEALTHY/DEGRADING/CRITICAL."""
    assert len(_TREND_CLASSES) == 3
    assert set(_TREND_CLASSES) == {"HEALTHY", "DEGRADING", "CRITICAL"}


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-03  CAMS-SAMPLE-0: valid sample accepted
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_03_valid_sample_accepted():
    """T231-CAMS-03: CAMS-SAMPLE-0 — score in [0,1] with source accepted."""
    sample = CHIMonitor().ingest(0.75, "casl-record-1")
    assert sample.chi_score == 0.75
    assert sample.source_ref == "casl-record-1"
    assert sample.sample_id.startswith("CHI-")


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-04  CAMS-SAMPLE-0: out-of-range score rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_04_out_of_range_score_rejected():
    """T231-CAMS-04: CAMS-SAMPLE-0 — chi_score outside [0,1] raises SampleError."""
    with pytest.raises(SampleError):
        CHIMonitor().ingest(1.5, "casl-record-2")
    with pytest.raises(SampleError):
        CHIMonitor().ingest(-0.1, "casl-record-2")


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-05  CAMS-SAMPLE-0: empty source_ref rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_05_empty_source_rejected():
    """T231-CAMS-05: CAMS-SAMPLE-0 — empty source_ref raises SampleError."""
    with pytest.raises(SampleError):
        CHIMonitor().ingest(0.5, "")
    with pytest.raises(SampleError):
        CHIMonitor().ingest(0.5, "   ")


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-06  CAMS-WINDOW-0: detector rejects window below minimum
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_06_detector_rejects_undersized_window():
    """T231-CAMS-06: CAMS-WINDOW-0 — window below _MIN_WINDOW raises WindowError."""
    with pytest.raises(WindowError):
        TrendDetector(window=_MIN_WINDOW - 1)


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-07  CAMS-WINDOW-0: sparse data always classifies HEALTHY
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_07_sparse_data_classifies_healthy():
    """T231-CAMS-07: CAMS-WINDOW-0 — fewer than min window samples => HEALTHY."""
    detector = TrendDetector()
    monitor = CHIMonitor()
    s = monitor.ingest(0.01, "casl-x")  # would be critical if window were full
    classification = detector.classify(s)
    assert classification.trend == TrendClass.HEALTHY
    assert classification.window_size == 1


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-08  CAMS-DETERM-0: high mean classifies HEALTHY at full window
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_08_high_mean_healthy():
    """T231-CAMS-08: CAMS-DETERM-0 — stable high CHI scores classify HEALTHY."""
    eng = CAMSEngine()
    result = _fill_healthy(eng)
    assert result["trend"] == "HEALTHY"


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-09  CAMS-DETERM-0: mid-range mean classifies DEGRADING
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_09_mid_mean_degrading():
    """T231-CAMS-09: CAMS-DETERM-0 — flat mid-range CHI scores classify DEGRADING."""
    eng = CAMSEngine()
    last = None
    for _ in range(_MIN_WINDOW):
        last = eng.sample(0.55, "casl-test")
    assert last["trend"] == "DEGRADING"


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-10  CAMS-DETERM-0: low mean classifies CRITICAL
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_10_low_mean_critical():
    """T231-CAMS-10: CAMS-DETERM-0 — sustained low CHI scores classify CRITICAL."""
    eng = CAMSEngine()
    result = _fill_critical(eng)
    assert result["trend"] == "CRITICAL"


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-11  CAMS-DETERM-0: sharp slope drop classifies CRITICAL
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_11_sharp_slope_drop_critical():
    """T231-CAMS-11: CAMS-DETERM-0 — steep slope decline forces CRITICAL even
    when mean is still above the critical-mean threshold."""
    eng = CAMSEngine()
    eng.sample(0.95, "casl-test")
    eng.sample(0.95, "casl-test")
    eng.sample(0.90, "casl-test")
    eng.sample(0.85, "casl-test")
    result = eng.sample(0.60, "casl-test")  # drop of 0.35 across window
    assert result["trend"] == "CRITICAL"


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-12  CAMS-DETERM-0: classification is deterministic / repeatable
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_12_deterministic_repeatable():
    """T231-CAMS-12: CAMS-DETERM-0 — identical input sequences classify identically."""
    eng1, eng2 = CAMSEngine(), CAMSEngine()
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
    results1 = [eng1.sample(s, "casl-test")["trend"] for s in scores]
    results2 = [eng2.sample(s, "casl-test")["trend"] for s in scores]
    assert results1 == results2


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-13  CAMS-CLASS-0: classifier never returns unrecognized trend
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_13_classifier_scope_enforced():
    """T231-CAMS-13: CAMS-CLASS-0 — every classification is one of the 3 trend classes."""
    eng = CAMSEngine()
    for score in [0.99, 0.7, 0.5, 0.3, 0.1, 0.6, 0.2]:
        result = eng.sample(score, "casl-test")
        assert result["trend"] in _TREND_CLASSES


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-14  CAMS-ALERT-0: CRITICAL trend raises exactly one alert
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_14_critical_raises_alert():
    """T231-CAMS-14: CAMS-ALERT-0 — CRITICAL classification produces an alert_id."""
    eng = CAMSEngine()
    result = _fill_critical(eng)
    assert "alert_id" in result
    assert len(eng.all_alerts()) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-15  CAMS-ALERT-0: non-CRITICAL classification raises no alert
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_15_healthy_raises_no_alert():
    """T231-CAMS-15: CAMS-ALERT-0 — HEALTHY classification produces no alert."""
    eng = CAMSEngine()
    result = _fill_healthy(eng)
    assert "alert_id" not in result
    assert len(eng.all_alerts()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-16  AlertEngine.raise_alert rejects non-CRITICAL classification
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_16_alert_engine_rejects_non_critical(engine):
    """T231-CAMS-16: CAMS-ALERT-0 — raise_alert() on non-CRITICAL raises AlertError."""
    monitor = CHIMonitor()
    detector = TrendDetector()
    sample = monitor.ingest(0.95, "casl-test")
    classification = detector.classify(sample)  # HEALTHY (window < min)
    with pytest.raises(AlertError):
        AlertEngine().raise_alert(classification)


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-17  CAMS-HUMAN0-0: acknowledgement requires non-empty identity
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_17_ack_requires_human0_identity():
    """T231-CAMS-17: CAMS-HUMAN0-0 — empty acknowledged_by raises HUMAN0AckError."""
    eng = CAMSEngine()
    result = _fill_critical(eng)
    with pytest.raises(HUMAN0AckError):
        eng.acknowledge_alert(result["alert_id"], "")
    with pytest.raises(HUMAN0AckError):
        eng.acknowledge_alert(result["alert_id"], "   ")


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-18  CAMS-HUMAN0-0: valid acknowledgement clears alert
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_18_valid_acknowledgement_clears_alert():
    """T231-CAMS-18: CAMS-HUMAN0-0 — non-empty identity transitions alert to ACKNOWLEDGED."""
    eng = CAMSEngine()
    result = _fill_critical(eng)
    alert = eng.acknowledge_alert(result["alert_id"], "DUSTIN L REID", "reviewed")
    assert alert.state == AlertState.ACKNOWLEDGED
    assert alert.acknowledged_by == "DUSTIN L REID"
    assert len(eng.open_alerts()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-19  CAMS-IMMUT-0: acknowledged alert cannot be re-acknowledged
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_19_double_acknowledge_blocked():
    """T231-CAMS-19: CAMS-IMMUT-0 — re-acknowledging an ACKNOWLEDGED alert raises."""
    eng = CAMSEngine()
    result = _fill_critical(eng)
    eng.acknowledge_alert(result["alert_id"], "DUSTIN L REID")
    with pytest.raises(ImmutabilityViolation):
        eng.acknowledge_alert(result["alert_id"], "DUSTIN L REID")


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-20  CAMS-CHAIN-0: monitoring ledger chain verifies on empty ledger
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_20_empty_ledger_chain_verifies():
    """T231-CAMS-20: CAMS-CHAIN-0 — an empty ledger trivially verifies."""
    assert MonitoringLedger().verify_chain() is True


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-21  CAMS-CHAIN-0: ledger chain verifies after appends
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_21_ledger_chain_verifies_after_appends(engine):
    """T231-CAMS-21: CAMS-CHAIN-0 — chain remains intact after multiple appends."""
    for score in [0.9, 0.8, 0.3, 0.2, 0.1, 0.05]:
        engine.sample(score, "casl-test")
    assert engine.verify_chain() is True
    assert len(engine.ledger_entries()) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-22  CAMS-CHAIN-0: tampered entry hash breaks chain detection
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_22_tampered_hash_detected(engine):
    """T231-CAMS-22: CAMS-CHAIN-0 — mutating a sealed entry's hash is detected."""
    engine.sample(0.9, "casl-test")
    engine.sample(0.8, "casl-test")
    entries = engine.ledger_entries()
    entries[0].entry_hash = "0" * 64  # simulate tamper
    with pytest.raises(ChainBreakError):
        engine.verify_chain()


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-23  CAMS-CHAIN-0: tampered prev_hash link breaks chain detection
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_23_tampered_link_detected(engine):
    """T231-CAMS-23: CAMS-CHAIN-0 — mutating prev_hash linkage is detected."""
    engine.sample(0.9, "casl-test")
    engine.sample(0.8, "casl-test")
    entries = engine.ledger_entries()
    entries[1].prev_hash = "f" * 64
    with pytest.raises(ChainBreakError):
        engine.verify_chain()


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-24  CAMS-APPEND-0: ledger length grows monotonically, never shrinks
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_24_ledger_append_only(engine):
    """T231-CAMS-24: CAMS-APPEND-0 — ledger length strictly increases with sampling."""
    lengths = []
    for score in [0.9, 0.8, 0.7, 0.6, 0.5]:
        engine.sample(score, "casl-test")
        lengths.append(len(engine.ledger_entries()))
    assert lengths == sorted(lengths)
    assert lengths[-1] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-25  CAMS-AUDIT-0: every sample operation is audited
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_25_audit_log_grows_on_sample(engine):
    """T231-CAMS-25: CAMS-AUDIT-0 — audit log records INGEST/CLASSIFY/LEDGER_APPEND per sample."""
    before = len(engine.audit_log())
    engine.sample(0.9, "casl-test")
    after = len(engine.audit_log())
    assert after > before
    ops = {e["operation"] for e in engine.audit_log()}
    assert {"INGEST", "CLASSIFY", "LEDGER_APPEND"}.issubset(ops)


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-26  CAMS-AUDIT-0: audit log HMAC chain is internally consistent
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_26_audit_chain_consistent():
    """T231-CAMS-26: CAMS-AUDIT-0 — auditor's own chain verifies and entry hashes are HMAC-bound."""
    auditor = CAMSAuditor()
    auditor.record("INGEST", "CHI-AAA")
    auditor.record("CLASSIFY", "TC-BBB")
    assert auditor.verify_chain() is True
    entries = auditor.all_entries()
    assert entries[0].prev_hash == "0" * 64
    assert entries[1].prev_hash == entries[0].entry_hash
    for e in entries:
        assert len(e.entry_hash) == 64


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-27  CAMSEngine.status reports expected fields
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_27_status_fields(engine):
    """T231-CAMS-27: status() reports module identity, version, and live counters."""
    engine.sample(0.9, "casl-test")
    status = engine.status()
    assert status["module"] == "CAMS"
    assert status["innov"] == "INNOV-136"
    assert status["phase"] == 231
    assert status["total_samples"] == 1
    assert set(status["trend_classes"]) == {"HEALTHY", "DEGRADING", "CRITICAL"}


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-28  API /cams/sample full round-trip
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_28_api_sample_round_trip():
    """T231-CAMS-28: POST /cams/sample processes a sample end-to-end via the API."""
    resp = _client.post("/cams/sample", json={"chi_score": 0.9, "source_ref": "casl-api-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SAMPLE_PROCESSED"
    assert body["trend"] in _TREND_CLASSES


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-29  API /cams/sample rejects out-of-range score (422)
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_29_api_sample_rejects_invalid_score():
    """T231-CAMS-29: CAMS-SAMPLE-0 — API returns 422 for out-of-range chi_score."""
    resp = _client.post("/cams/sample", json={"chi_score": 5.0, "source_ref": "casl-api-test"})
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# T231-CAMS-30  API /cams/verify-chain and /cams/status respond healthy
# ═══════════════════════════════════════════════════════════════════════════════
def test_T231_CAMS_30_api_verify_chain_and_status():
    """T231-CAMS-30: GET /cams/verify-chain and GET /cams/status both respond 200."""
    chain_resp = _client.get("/cams/verify-chain")
    status_resp = _client.get("/cams/status")
    assert chain_resp.status_code == 200
    assert chain_resp.json()["chain_intact"] is True
    assert status_resp.status_code == 200
    assert status_resp.json()["module"] == "CAMS"
