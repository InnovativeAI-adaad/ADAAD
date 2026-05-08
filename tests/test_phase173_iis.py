# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase173_iis.py — Phase 173 · INNOV-79 · IIS
Innovation Impact Scorer — 30-test acceptance suite

Test IDs: T173-IIS-01 through T173-IIS-30
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from dorkllm.innovation_impact_scorer import (
    HUMAN_0_AUTHORITY,
    IIS_AUTH_0,
    IIS_BOUND_0,
    IIS_CHAIN_0,
    IIS_COVG_0,
    IIS_NONZERO_0,
    IIS_ROLLUP_0,
    ImpactRecord,
    InnovationImpactScorer,
    InnovationMetrics,
    IISAuthError,
    IISBoundError,
    IISCalcError,
    IISChainError,
    IISCoverageError,
    IISRollupError,
    SCORE_MAX,
    SCORE_MIN,
)

pytestmark = pytest.mark.phase173_iis


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _good_metrics(innov_id: str = "INNOV-01", phase: int = 1) -> InnovationMetrics:
    return InnovationMetrics(
        innovation_id=innov_id,
        phase=phase,
        approval_rate_before=0.70,
        approval_rate_after=0.82,
        invariant_violations_before=5,
        invariant_violations_after=2,
        fitness_score_before=0.65,
        fitness_score_after=0.74,
        epochs_observed=3,
    )


def _scorer(tmp_path: Path) -> InnovationImpactScorer:
    ledger = str(tmp_path / "security" / "iis_ledger.jsonl")
    return InnovationImpactScorer(ledger_path=ledger)


# ── T173-IIS-01: Module imports without error ─────────────────────────────────

def test_t173_iis_01_module_imports():
    from dorkllm import innovation_impact_scorer  # noqa: F401
    assert True


# ── T173-IIS-02: InnovationMetrics instantiates ───────────────────────────────

def test_t173_iis_02_metrics_instantiates():
    m = _good_metrics()
    assert m.innovation_id == "INNOV-01"
    assert m.epochs_observed == 3


# ── T173-IIS-03: validate() passes for valid metrics ─────────────────────────

def test_t173_iis_03_validate_passes():
    _good_metrics().validate()  # must not raise


# ── T173-IIS-04: validate() raises IISBoundError for score > 1.0 ─────────────

def test_t173_iis_04_validate_bound_above():
    m = _good_metrics()
    m.approval_rate_after = 1.5
    with pytest.raises(IISBoundError) as exc:
        m.validate()
    assert IIS_BOUND_0 in str(exc.value)


# ── T173-IIS-05: validate() raises IISBoundError for score < 0.0 ─────────────

def test_t173_iis_05_validate_bound_below():
    m = _good_metrics()
    m.fitness_score_before = -0.1
    with pytest.raises(IISBoundError) as exc:
        m.validate()
    assert IIS_BOUND_0 in str(exc.value)


# ── T173-IIS-06: validate() raises IISCalcError for epochs_observed=0 ────────

def test_t173_iis_06_validate_zero_epochs():
    m = _good_metrics()
    m.epochs_observed = 0
    with pytest.raises(IISCalcError) as exc:
        m.validate()
    assert IIS_NONZERO_0 in str(exc.value)


# ── T173-IIS-07: validate() raises IISCalcError for negative violations ───────

def test_t173_iis_07_validate_negative_violations():
    m = _good_metrics()
    m.invariant_violations_after = -1
    with pytest.raises(IISCalcError) as exc:
        m.validate()
    assert IIS_NONZERO_0 in str(exc.value)


# ── T173-IIS-08: ImpactRecord seals and verifies ─────────────────────────────

def test_t173_iis_08_record_seal_verify():
    rec = ImpactRecord(
        innovation_id="INNOV-01",
        phase=1,
        impact_score=0.75,
        approval_delta=0.12,
        violation_delta=-3,
        fitness_delta=0.09,
        epochs_observed=3,
        timestamp_utc="2026-05-07T00:00:00Z",
        governor=HUMAN_0_AUTHORITY,
        prev_digest="GENESIS",
    ).seal()
    assert rec.verify()


# ── T173-IIS-09: Tampered record fails verify ─────────────────────────────────

def test_t173_iis_09_tampered_record_fails():
    rec = ImpactRecord(
        innovation_id="INNOV-01",
        phase=1,
        impact_score=0.75,
        approval_delta=0.12,
        violation_delta=-3,
        fitness_delta=0.09,
        epochs_observed=3,
        timestamp_utc="2026-05-07T00:00:00Z",
        governor=HUMAN_0_AUTHORITY,
        prev_digest="GENESIS",
    ).seal()
    rec.impact_score = 0.99  # tamper
    assert not rec.verify()


# ── T173-IIS-10: scorer.score() returns ImpactRecord ─────────────────────────

def test_t173_iis_10_score_returns_record(tmp_path):
    scorer = _scorer(tmp_path)
    rec = scorer.score(_good_metrics())
    assert isinstance(rec, ImpactRecord)


# ── T173-IIS-11: impact_score is in [0.0, 1.0] ───────────────────────────────

def test_t173_iis_11_score_in_bounds(tmp_path):
    scorer = _scorer(tmp_path)
    rec = scorer.score(_good_metrics())
    assert SCORE_MIN <= rec.impact_score <= SCORE_MAX


# ── T173-IIS-12: positive improvement → score > 0.5 ─────────────────────────

def test_t173_iis_12_positive_improvement_above_neutral(tmp_path):
    scorer = _scorer(tmp_path)
    rec = scorer.score(_good_metrics())  # approval 0.70→0.82, violations 5→2
    assert rec.impact_score > 0.5


# ── T173-IIS-13: negative regression → score < 0.5 ──────────────────────────

def test_t173_iis_13_negative_regression_below_neutral(tmp_path):
    scorer = _scorer(tmp_path)
    m = InnovationMetrics(
        innovation_id="INNOV-BAD",
        phase=99,
        approval_rate_before=0.80,
        approval_rate_after=0.60,
        invariant_violations_before=2,
        invariant_violations_after=8,
        fitness_score_before=0.75,
        fitness_score_after=0.55,
        epochs_observed=3,
    )
    rec = scorer.score(m)
    assert rec.impact_score < 0.5


# ── T173-IIS-14: neutral (no change) → score near 0.5 ───────────────────────

def test_t173_iis_14_neutral_impact_near_half(tmp_path):
    scorer = _scorer(tmp_path)
    m = InnovationMetrics(
        innovation_id="INNOV-NEUT",
        phase=50,
        approval_rate_before=0.70,
        approval_rate_after=0.70,
        invariant_violations_before=3,
        invariant_violations_after=3,
        fitness_score_before=0.65,
        fitness_score_after=0.65,
        epochs_observed=2,
    )
    rec = scorer.score(m)
    assert abs(rec.impact_score - 0.5) < 0.01


# ── T173-IIS-15: ledger file created after first score ───────────────────────

def test_t173_iis_15_ledger_created(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics())
    ledger = tmp_path / "security" / "iis_ledger.jsonl"
    assert ledger.exists()


# ── T173-IIS-16: ledger record contains governor ─────────────────────────────

def test_t173_iis_16_ledger_has_governor(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics())
    ledger = tmp_path / "security" / "iis_ledger.jsonl"
    data = json.loads(ledger.read_text().strip().splitlines()[-1])
    assert data["governor"] == HUMAN_0_AUTHORITY


# ── T173-IIS-17: second score chains off first ────────────────────────────────

def test_t173_iis_17_chain_links(tmp_path):
    scorer = _scorer(tmp_path)
    r1 = scorer.score(_good_metrics("INNOV-01", 1))
    r2 = scorer.score(_good_metrics("INNOV-02", 2))
    assert r2.prev_digest == r1.digest


# ── T173-IIS-18: determinism — same inputs produce same score ────────────────

def test_t173_iis_18_determinism(tmp_path):
    s1 = _scorer(tmp_path / "a")
    s2 = _scorer(tmp_path / "b")
    m = _good_metrics()
    r1 = s1.score(m)
    r2 = s2.score(m)
    assert r1.impact_score == r2.impact_score


# ── T173-IIS-19: rollup raises IISCoverageError on empty ledger ──────────────

def test_t173_iis_19_rollup_empty_raises(tmp_path):
    scorer = _scorer(tmp_path)
    with pytest.raises(IISCoverageError) as exc:
        scorer.rollup()
    assert IIS_COVG_0 in str(exc.value)


# ── T173-IIS-20: rollup returns expected keys ────────────────────────────────

def test_t173_iis_20_rollup_keys(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics("INNOV-01", 1))
    scorer.score(_good_metrics("INNOV-02", 2))
    result = scorer.rollup()
    for key in [
        "total_innovations", "mean_impact", "top_impact_id",
        "bottom_impact_id", "positive_count", "chain_integrity_verified",
    ]:
        assert key in result, f"Missing key: {key}"


# ── T173-IIS-21: rollup total_innovations matches scored count ───────────────

def test_t173_iis_21_rollup_count(tmp_path):
    scorer = _scorer(tmp_path)
    for i in range(5):
        scorer.score(_good_metrics(f"INNOV-{i:02d}", i + 1))
    result = scorer.rollup()
    assert result["total_innovations"] == 5


# ── T173-IIS-22: rollup chain_integrity_verified is True ─────────────────────

def test_t173_iis_22_rollup_chain_flag(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics())
    result = scorer.rollup()
    assert result["chain_integrity_verified"] is True


# ── T173-IIS-23: rollup raises IISRollupError on tampered record ─────────────

def test_t173_iis_23_rollup_detects_tamper(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics())
    ledger = tmp_path / "security" / "iis_ledger.jsonl"
    lines = ledger.read_text().strip().splitlines()
    data = json.loads(lines[0])
    data["impact_score"] = 0.999  # tamper
    ledger.write_text(json.dumps(data) + "\n")
    scorer2 = _scorer(tmp_path)
    with pytest.raises(IISRollupError) as exc:
        scorer2.rollup()
    assert IIS_ROLLUP_0 in str(exc.value)


# ── T173-IIS-24: generate_report requires HUMAN-0 authority ──────────────────

def test_t173_iis_24_report_requires_auth(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics())
    with pytest.raises(IISAuthError) as exc:
        scorer.generate_report(authority="UNKNOWN ACTOR")
    assert IIS_AUTH_0 in str(exc.value)


# ── T173-IIS-25: generate_report succeeds with correct authority ──────────────

def test_t173_iis_25_report_with_authority(tmp_path):
    scorer = _scorer(tmp_path)
    scorer.score(_good_metrics())
    report = scorer.generate_report(authority=HUMAN_0_AUTHORITY)
    assert report["report_type"] == "IIS_FULL_REPORT"


# ── T173-IIS-26: approval_delta recorded correctly ───────────────────────────

def test_t173_iis_26_approval_delta(tmp_path):
    scorer = _scorer(tmp_path)
    m = _good_metrics()
    rec = scorer.score(m)
    expected = round(m.approval_rate_after - m.approval_rate_before, 6)
    assert abs(rec.approval_delta - expected) < 1e-9


# ── T173-IIS-27: violation_delta recorded correctly ──────────────────────────

def test_t173_iis_27_violation_delta(tmp_path):
    scorer = _scorer(tmp_path)
    m = _good_metrics()
    rec = scorer.score(m)
    assert rec.violation_delta == (
        m.invariant_violations_after - m.invariant_violations_before
    )


# ── T173-IIS-28: first record has GENESIS prev_digest ────────────────────────

def test_t173_iis_28_genesis_prev_digest(tmp_path):
    scorer = _scorer(tmp_path)
    rec = scorer.score(_good_metrics())
    assert rec.prev_digest == "GENESIS"


# ── T173-IIS-29: score invariant constants are string type ───────────────────

def test_t173_iis_29_invariant_constants_are_strings():
    from dorkllm.innovation_impact_scorer import (
        IIS_AUDIT_0, IIS_AUTH_0, IIS_BOUND_0, IIS_CHAIN_0,
        IIS_COVG_0, IIS_DELTA_0, IIS_DETERM_0, IIS_NONZERO_0,
        IIS_PERSIST_0, IIS_ROLLUP_0,
    )
    for const in [
        IIS_AUDIT_0, IIS_AUTH_0, IIS_BOUND_0, IIS_CHAIN_0,
        IIS_COVG_0, IIS_DELTA_0, IIS_DETERM_0, IIS_NONZERO_0,
        IIS_PERSIST_0, IIS_ROLLUP_0,
    ]:
        assert isinstance(const, str)


# ── T173-IIS-30: rollup mean_impact is in [0.0, 1.0] ─────────────────────────

def test_t173_iis_30_rollup_mean_in_bounds(tmp_path):
    scorer = _scorer(tmp_path)
    for i in range(4):
        scorer.score(_good_metrics(f"INNOV-{i:02d}", i + 1))
    result = scorer.rollup()
    assert SCORE_MIN <= result["mean_impact"] <= SCORE_MAX
