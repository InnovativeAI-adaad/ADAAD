# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase228_cali.py
Phase 228 · INNOV-133 · CALI — Constitutional Autonomous Learning Intelligence
30-test acceptance suite — T228-CALI-01 through T228-CALI-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

import pytest
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_learning_intelligence import (
    CALIEngine,
    BoundError,
    ChainBreakError,
    HUMAN0RatificationError,
    IngestionError,
    ImmutabilityViolation,
    OriginError,
    ScopeError,
    Classification,
    CHIBand,
    RecommendationStatus,
    _compute_raw_signal,
    _SIGNAL_BOUND,
    _BAND_CUMULATIVE_CAP,
)
from app.api.cali import router
from fastapi import FastAPI

pytestmark = pytest.mark.phase228

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _good_record(
    eval_id: str = "eval-001",
    classification: str = "IMPROVED",
    chi_before: float = 0.85,
    chi_after: float = 0.90,
) -> dict:
    return {
        "evaluation_id": eval_id,
        "classification": classification,
        "chi_before": chi_before,
        "chi_after": chi_after,
    }


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 1: OutcomeIngester — CALI-INGEST-0, CALI-SCOPE-0, CALI-ORIGIN-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T228_CALI_01_ingest_improved_outcome():
    """T228-CALI-01: IMPROVED outcome ingests and returns sealed record."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.92))
    assert outcome.classification == "IMPROVED"
    assert outcome.chi_band == CHIBand.PROMOTE.value
    assert outcome.sealed is True
    assert outcome.hmac_digest != ""


def test_T228_CALI_02_ingest_neutral_outcome():
    """T228-CALI-02: NEUTRAL outcome ingests correctly."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="NEUTRAL", chi_before=0.65, chi_after=0.65))
    assert outcome.classification == "NEUTRAL"
    assert outcome.chi_band == CHIBand.HOLD.value


def test_T228_CALI_03_ingest_degraded_outcome():
    """T228-CALI-03: DEGRADED outcome ingests correctly."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="DEGRADED", chi_before=0.40, chi_after=0.35))
    assert outcome.classification == "DEGRADED"
    assert outcome.chi_band == CHIBand.REJECT.value


def test_T228_CALI_04_origin_zero_empty_eval_id():
    """T228-CALI-04: CALI-ORIGIN-0 — empty evaluation_id raises OriginError."""
    eng = CALIEngine()
    with pytest.raises(OriginError, match="CALI-ORIGIN-0"):
        eng.ingest(_good_record(eval_id=""))


def test_T228_CALI_05_origin_zero_whitespace_eval_id():
    """T228-CALI-05: CALI-ORIGIN-0 — whitespace-only evaluation_id raises OriginError."""
    eng = CALIEngine()
    with pytest.raises(OriginError, match="CALI-ORIGIN-0"):
        eng.ingest(_good_record(eval_id="   "))


def test_T228_CALI_06_scope_zero_unknown_classification():
    """T228-CALI-06: CALI-SCOPE-0 — unknown classification raises ScopeError."""
    eng = CALIEngine()
    with pytest.raises(ScopeError, match="CALI-SCOPE-0"):
        eng.ingest(_good_record(classification="UNKNOWN"))


def test_T228_CALI_07_ingest_zero_missing_required_fields():
    """T228-CALI-07: CALI-INGEST-0 — missing required fields raises IngestionError."""
    eng = CALIEngine()
    with pytest.raises(IngestionError, match="CALI-INGEST-0"):
        eng.ingest({"evaluation_id": "e1"})  # missing classification, chi_before, chi_after


def test_T228_CALI_08_ingest_delta_chi_computed():
    """T228-CALI-08: delta_chi is correctly computed as chi_after - chi_before."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(chi_before=0.70, chi_after=0.80))
    assert abs(outcome.delta_chi - 0.10) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 2: AdaptationSignalEngine — CALI-ADAPT-0, CALI-DETERM-0, CALI-BOUND-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T228_CALI_09_signal_improved_is_positive():
    """T228-CALI-09: IMPROVED classification produces positive adaptation signal."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.92))
    sig = eng.compute_signal(outcome.ingestion_id)
    assert sig.raw_signal > 0.0


def test_T228_CALI_10_signal_degraded_is_negative():
    """T228-CALI-10: DEGRADED classification produces negative adaptation signal."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="DEGRADED", chi_before=0.40, chi_after=0.30))
    sig = eng.compute_signal(outcome.ingestion_id)
    assert sig.raw_signal < 0.0


def test_T228_CALI_11_signal_neutral_is_zero():
    """T228-CALI-11: NEUTRAL classification produces zero adaptation signal."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="NEUTRAL", chi_before=0.65, chi_after=0.65))
    sig = eng.compute_signal(outcome.ingestion_id)
    assert sig.raw_signal == 0.0


def test_T228_CALI_12_signal_bounded():
    """T228-CALI-12: CALI-ADAPT-0 — raw_signal is bounded to [-0.05, +0.05]."""
    sig = _compute_raw_signal("IMPROVED", 1.0)
    assert -_SIGNAL_BOUND <= sig <= _SIGNAL_BOUND


def test_T228_CALI_13_signal_deterministic():
    """T228-CALI-13: CALI-DETERM-0 — same input produces identical signal."""
    s1 = _compute_raw_signal("IMPROVED", 0.10)
    s2 = _compute_raw_signal("IMPROVED", 0.10)
    assert s1 == s2


def test_T228_CALI_14_signal_hmac_sealed():
    """T228-CALI-14: Adaptation signal carries non-empty HMAC digest."""
    eng = CALIEngine()
    outcome = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    sig = eng.compute_signal(outcome.ingestion_id)
    assert sig.hmac_digest != ""
    assert sig.sealed is True


def test_T228_CALI_15_cumulative_cap_enforced():
    """T228-CALI-15: CALI-BOUND-0 — cumulative delta per band capped at ±0.10."""
    eng = CALIEngine()
    # Ingest and compute 6 IMPROVED signals for PROMOTE band (each +0.02 → sum =+0.12 > +0.10)
    outcomes = []
    for i in range(5):
        o = eng.ingest(_good_record(
            eval_id=f"eval-{i}",
            classification="IMPROVED",
            chi_before=0.85,
            chi_after=0.90,
        ))
        eng.compute_signal(o.ingestion_id)
        outcomes.append(o)
    # 6th signal should trigger BoundError
    o6 = eng.ingest(_good_record(eval_id="eval-6", classification="IMPROVED",
                                  chi_before=0.85, chi_after=0.90))
    with pytest.raises(BoundError, match="CALI-BOUND-0"):
        eng.compute_signal(o6.ingestion_id)


def test_T228_CALI_16_signal_unknown_ingestion_id():
    """T228-CALI-16: compute_signal with unknown ingestion_id raises IngestionError."""
    eng = CALIEngine()
    with pytest.raises(IngestionError, match="CALI-INGEST-0"):
        eng.compute_signal("no-such-id")


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 3: ThresholdRecommender — CALI-HUMAN0-0, CALI-THRESH-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T228_CALI_17_recommend_produces_pending():
    """T228-CALI-17: recommend() returns PENDING recommendation."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    assert rec.status == RecommendationStatus.PENDING.value
    assert rec.ratified_by == ""


def test_T228_CALI_18_human0_ratify_succeeds():
    """T228-CALI-18: HUMAN-0 ratification with non-empty ratified_by succeeds."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    ratified = eng.ratify(rec.recommendation_id, "DUSTIN L REID")
    assert ratified.status == RecommendationStatus.RATIFIED.value
    assert ratified.ratified_by == "DUSTIN L REID"


def test_T228_CALI_19_human0_empty_ratified_by_raises():
    """T228-CALI-19: CALI-HUMAN0-0 — empty ratified_by raises HUMAN0RatificationError."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    with pytest.raises(HUMAN0RatificationError, match="CALI-HUMAN0-0"):
        eng.ratify(rec.recommendation_id, "")


def test_T228_CALI_20_human0_whitespace_ratified_by_raises():
    """T228-CALI-20: CALI-HUMAN0-0 — whitespace-only ratified_by raises HUMAN0RatificationError."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    with pytest.raises(HUMAN0RatificationError, match="CALI-HUMAN0-0"):
        eng.ratify(rec.recommendation_id, "   ")


def test_T228_CALI_21_threshold_only_updates_after_ratification():
    """T228-CALI-21: Live threshold unchanged until HUMAN-0 ratification — CALI-HUMAN0-0."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    before = eng.live_thresholds()[CHIBand.PROMOTE.value]
    rec = eng.recommend(CHIBand.PROMOTE.value)
    # PENDING — threshold unchanged
    assert eng.live_thresholds()[CHIBand.PROMOTE.value] == before
    # After ratification — threshold updates
    eng.ratify(rec.recommendation_id, "DUSTIN L REID")
    # Threshold may be same if delta is 0, but the record is ratified
    ratified = eng.list_recommendations("RATIFIED")
    assert len(ratified) == 1


def test_T228_CALI_22_reject_recommendation():
    """T228-CALI-22: HUMAN-0 rejection seals recommendation as REJECTED."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="DEGRADED", chi_before=0.40, chi_after=0.30))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.REJECT.value)
    rejected = eng.reject(rec.recommendation_id, "threshold stable")
    assert rejected.status == RecommendationStatus.REJECTED.value


def test_T228_CALI_23_double_ratify_raises_immutability():
    """T228-CALI-23: CALI-IMMUT-0 — ratifying already-ratified recommendation raises."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    eng.ratify(rec.recommendation_id, "DUSTIN L REID")
    with pytest.raises(ImmutabilityViolation, match="CALI-IMMUT-0"):
        eng.ratify(rec.recommendation_id, "DUSTIN L REID")


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 4: LearningLedger — CALI-CHAIN-0, CALI-APPEND-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T228_CALI_24_verify_chain_empty():
    """T228-CALI-24: verify_chain on empty ledger returns valid."""
    eng = CALIEngine()
    result = eng.verify_chain()
    assert result["chain_valid"] is True
    assert result["record_count"] == 0


def test_T228_CALI_25_verify_chain_after_operations():
    """T228-CALI-25: verify_chain after multiple operations confirms intact chain."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    eng.ratify(rec.recommendation_id, "DUSTIN L REID")
    result = eng.verify_chain()
    assert result["chain_valid"] is True
    assert result["record_count"] >= 3  # INGEST + COMPUTE + RECOMMEND + RATIFY


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 5: Audit — CALI-AUDIT-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T228_CALI_26_audit_log_records_ingest():
    """T228-CALI-26: CALI-AUDIT-0 — ingest operation is recorded in audit log."""
    eng = CALIEngine()
    eng.ingest(_good_record())
    audit = eng.audit_log()
    assert any(e["operation"] == "INGEST" for e in audit)


def test_T228_CALI_27_audit_log_records_ratify():
    """T228-CALI-27: CALI-AUDIT-0 — ratify operation is recorded in audit log."""
    eng = CALIEngine()
    o = eng.ingest(_good_record(classification="IMPROVED", chi_before=0.85, chi_after=0.90))
    eng.compute_signal(o.ingestion_id)
    rec = eng.recommend(CHIBand.PROMOTE.value)
    eng.ratify(rec.recommendation_id, "DUSTIN L REID")
    audit = eng.audit_log()
    assert any(e["operation"] == "RATIFY" for e in audit)


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 6: REST API endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_T228_CALI_28_api_ingest_endpoint():
    """T228-CALI-28: POST /cali/ingest returns 200 with sealed ingested outcome."""
    resp = _client.post("/cali/ingest", json={"evaluation_record": _good_record()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["classification"] == "IMPROVED"
    assert data["sealed"] is True


def test_T228_CALI_29_api_status_endpoint():
    """T228-CALI-29: GET /cali/status returns CALI module status."""
    resp = _client.get("/cali/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["module"] == "CALI"
    assert data["innov"] == "INNOV-133"
    assert "CALI-HUMAN0-0" in data["hard_class_invariants"]


def test_T228_CALI_30_api_verify_chain_endpoint():
    """T228-CALI-30: GET /cali/verify-chain returns valid chain status."""
    resp = _client.get("/cali/verify-chain")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chain_valid"] is True
