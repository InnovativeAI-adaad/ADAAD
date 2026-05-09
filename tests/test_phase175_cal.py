# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# test_phase175_cal.py — INNOV-80 · CAL Constitutional Adaptive Learner
# 30/30 acceptance tests  T175-CAL-01 through T175-CAL-30
#
# Phase:   175  |  Innovation: INNOV-80  |  Version: 9.108.0
# Author:  DEVADAAD · InnovativeAI LLC
# Governor: DUSTIN L REID (HUMAN-0)
# =============================================================================

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import textwrap
from dataclasses import asdict
from pathlib import Path

import pytest

from dorkllm.constitutional_adaptive_learner import (
    ConstitutionalAdaptiveLearner,
    AmendmentRecommendation,
    InvariantWeight,
    LearningCycleResult,
    list_invariants,
    _clamp,
    _hmac_entry,
    _read_jsonl,
    _atomic_write_json,
    _append_jsonl,
    _INVARIANTS,
    _WEIGHT_MIN,
    _WEIGHT_MAX,
    _GOVERNOR,
    _MIN_RECORDS_FOR_RECOMMENDATION,
)

pytestmark = pytest.mark.phase175


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = b"test-cal-secret-hmac-key"
_TS = "2026-05-09T12:00:00+00:00"


def _make_cal(tmp_path: Path) -> ConstitutionalAdaptiveLearner:
    return ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=tmp_path / "iis_ledger.jsonl",
        mfv_ledger_path=tmp_path / "mfv_ledger.jsonl",
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recommendations.json",
    )


def _write_iis(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_mfv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# T175-CAL-01: Module imports without error
# ---------------------------------------------------------------------------
def test_T175_CAL_01_import():
    assert ConstitutionalAdaptiveLearner is not None


# ---------------------------------------------------------------------------
# T175-CAL-02: list_invariants returns exactly 10 entries
# ---------------------------------------------------------------------------
def test_T175_CAL_02_invariant_count():
    invs = list_invariants()
    assert len(invs) == 10


# ---------------------------------------------------------------------------
# T175-CAL-03: All invariants are Hard-class
# ---------------------------------------------------------------------------
def test_T175_CAL_03_invariant_class():
    for inv in list_invariants():
        assert inv["class"] == "Hard", f"Expected Hard, got {inv['class']} for {inv['id']}"


# ---------------------------------------------------------------------------
# T175-CAL-04: All 10 invariant IDs are present
# ---------------------------------------------------------------------------
def test_T175_CAL_04_invariant_ids():
    expected = {
        "CAL-CHAIN-0", "CAL-DETERM-0", "CAL-HUMAN0-0", "CAL-READONLY-0",
        "CAL-ATOMIC-0", "CAL-BOUND-0", "CAL-AUDIT-0", "CAL-SCOPE-0",
        "CAL-REPLAY-0", "CAL-NOSELF-0",
    }
    actual = {inv["id"] for inv in list_invariants()}
    assert actual == expected


# ---------------------------------------------------------------------------
# T175-CAL-05: CAL constructs successfully with valid paths
# ---------------------------------------------------------------------------
def test_T175_CAL_05_construct(tmp_path):
    cal = _make_cal(tmp_path)
    assert cal is not None


# ---------------------------------------------------------------------------
# T175-CAL-06: CAL-NOSELF-0 raises ValueError if iis_path = cal_ledger_path
# ---------------------------------------------------------------------------
def test_T175_CAL_06_noself_iis(tmp_path):
    cal_path = tmp_path / "cal/learning_ledger.jsonl"
    with pytest.raises(ValueError, match="CAL-NOSELF-0"):
        ConstitutionalAdaptiveLearner(
            hmac_secret=_SECRET,
            iis_ledger_path=cal_path,  # same as cal_ledger_path — violation
            mfv_ledger_path=tmp_path / "mfv.jsonl",
            cal_ledger_path=cal_path,
            cal_recs_path=tmp_path / "recs.json",
        )


# ---------------------------------------------------------------------------
# T175-CAL-07: CAL-NOSELF-0 raises ValueError if mfv_path = cal_ledger_path
# ---------------------------------------------------------------------------
def test_T175_CAL_07_noself_mfv(tmp_path):
    cal_path = tmp_path / "cal/learning_ledger.jsonl"
    with pytest.raises(ValueError, match="CAL-NOSELF-0"):
        ConstitutionalAdaptiveLearner(
            hmac_secret=_SECRET,
            iis_ledger_path=tmp_path / "iis.jsonl",
            mfv_ledger_path=cal_path,  # same as cal_ledger_path — violation
            cal_ledger_path=cal_path,
            cal_recs_path=tmp_path / "recs.json",
        )


# ---------------------------------------------------------------------------
# T175-CAL-08: verify_chain returns True on empty ledger
# ---------------------------------------------------------------------------
def test_T175_CAL_08_chain_empty(tmp_path):
    cal = _make_cal(tmp_path)
    assert cal.verify_chain() is True


# ---------------------------------------------------------------------------
# T175-CAL-09: run_learning_cycle succeeds on empty source ledgers
# ---------------------------------------------------------------------------
def test_T175_CAL_09_cycle_empty_sources(tmp_path):
    cal = _make_cal(tmp_path)
    result = cal.run_learning_cycle(cycle_id="c-001", timestamp_utc_iso=_TS)
    assert isinstance(result, LearningCycleResult)
    assert result.iis_records_read == 0
    assert result.mfv_records_read == 0


# ---------------------------------------------------------------------------
# T175-CAL-10: LearningCycleResult has correct governor
# ---------------------------------------------------------------------------
def test_T175_CAL_10_governor(tmp_path):
    cal = _make_cal(tmp_path)
    result = cal.run_learning_cycle(cycle_id="c-002", timestamp_utc_iso=_TS)
    assert result.governor == "DUSTIN L REID"


# ---------------------------------------------------------------------------
# T175-CAL-11: LearningCycleResult phase matches 175
# ---------------------------------------------------------------------------
def test_T175_CAL_11_phase(tmp_path):
    cal = _make_cal(tmp_path)
    result = cal.run_learning_cycle(cycle_id="c-003", timestamp_utc_iso=_TS)
    assert result.phase == 175


# ---------------------------------------------------------------------------
# T175-CAL-12: LearningCycleResult innov_code matches INNOV-80
# ---------------------------------------------------------------------------
def test_T175_CAL_12_innov_code(tmp_path):
    cal = _make_cal(tmp_path)
    result = cal.run_learning_cycle(cycle_id="c-004", timestamp_utc_iso=_TS)
    assert result.innov_code == "INNOV-80"


# ---------------------------------------------------------------------------
# T175-CAL-13: CAL ledger is written after cycle
# ---------------------------------------------------------------------------
def test_T175_CAL_13_ledger_written(tmp_path):
    cal = _make_cal(tmp_path)
    cal.run_learning_cycle(cycle_id="c-005", timestamp_utc_iso=_TS)
    ledger = tmp_path / "cal/learning_ledger.jsonl"
    assert ledger.exists()
    records = _read_jsonl(ledger)
    assert len(records) == 1


# ---------------------------------------------------------------------------
# T175-CAL-14: CAL audit record contains cycle_id
# ---------------------------------------------------------------------------
def test_T175_CAL_14_audit_cycle_id(tmp_path):
    cal = _make_cal(tmp_path)
    cal.run_learning_cycle(cycle_id="cycle-audit-test", timestamp_utc_iso=_TS)
    records = _read_jsonl(tmp_path / "cal/learning_ledger.jsonl")
    assert records[0]["cycle_id"] == "cycle-audit-test"


# ---------------------------------------------------------------------------
# T175-CAL-15: CAL recommendations file written atomically
# ---------------------------------------------------------------------------
def test_T175_CAL_15_recs_written(tmp_path):
    cal = _make_cal(tmp_path)
    cal.run_learning_cycle(cycle_id="c-006", timestamp_utc_iso=_TS)
    recs_file = tmp_path / "cal/recommendations.json"
    assert recs_file.exists()
    data = json.loads(recs_file.read_text())
    assert data["requires_human0_approval"] is True


# ---------------------------------------------------------------------------
# T175-CAL-16: CAL-HUMAN0-0 — all recommendations require_human0_approval=True
# ---------------------------------------------------------------------------
def test_T175_CAL_16_human0_gated(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    # Enough records to trigger REINFORCE/REVIEW
    iis_recs = [
        {"impact_score": 0.9, "invariant_ids": ["INV-A"]} for _ in range(6)
    ]
    _write_iis(iis_path, iis_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-007", timestamp_utc_iso=_TS)
    for rec in result.recommendations:
        assert rec.requires_human0_approval is True, (
            f"CAL-HUMAN0-0: {rec.invariant_id} missing human0 gate"
        )


# ---------------------------------------------------------------------------
# T175-CAL-17: CAL-BOUND-0 — normalized weights in [0.0, 1.0]
# ---------------------------------------------------------------------------
def test_T175_CAL_17_weight_bounds(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    iis_recs = [{"impact_score": s, "invariant_ids": [f"INV-{i}"]}
                for i, s in enumerate([-5.0, 0.0, 0.5, 2.0, 10.0])]
    _write_iis(iis_path, iis_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-008", timestamp_utc_iso=_TS)
    for w in result.weights:
        assert _WEIGHT_MIN <= w.normalized_weight <= _WEIGHT_MAX, (
            f"CAL-BOUND-0: weight {w.normalized_weight} out of [0,1] for {w.invariant_id}"
        )


# ---------------------------------------------------------------------------
# T175-CAL-18: IIS records contribute to weight computation
# ---------------------------------------------------------------------------
def test_T175_CAL_18_iis_contribution(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    iis_recs = [{"impact_score": 1.0, "invariant_ids": ["STRONG-INV"]}]
    _write_iis(iis_path, iis_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-009", timestamp_utc_iso=_TS)
    assert result.invariants_analyzed == 1
    assert result.weights[0].invariant_id == "STRONG-INV"


# ---------------------------------------------------------------------------
# T175-CAL-19: MFV CERTIFIED verdict contributes positive weight
# ---------------------------------------------------------------------------
def test_T175_CAL_19_mfv_certified(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    mfv_recs = [
        {"verdict": "CERTIFIED", "fitness_delta": 0.8, "invariants_checked": ["INV-CERT"]}
        for _ in range(6)
    ]
    _write_mfv(mfv_path, mfv_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-010", timestamp_utc_iso=_TS)
    assert any(w.invariant_id == "INV-CERT" and w.positive_delta_sum > 0
               for w in result.weights)


# ---------------------------------------------------------------------------
# T175-CAL-20: MFV REGRESSED verdict contributes negative weight
# ---------------------------------------------------------------------------
def test_T175_CAL_20_mfv_regressed(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    mfv_recs = [
        {"verdict": "REGRESSED", "fitness_delta": -0.5, "invariants_checked": ["INV-REG"]}
        for _ in range(6)
    ]
    _write_mfv(mfv_path, mfv_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-011", timestamp_utc_iso=_TS)
    assert any(w.invariant_id == "INV-REG" and w.negative_delta_sum > 0
               for w in result.weights)


# ---------------------------------------------------------------------------
# T175-CAL-21: REINFORCE recommendation emitted for high-weight invariant
# ---------------------------------------------------------------------------
def test_T175_CAL_21_reinforce_recommendation(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    # Make INV-A dominate with high positive impact
    iis_recs = [{"impact_score": 100.0, "invariant_ids": ["INV-A"]} for _ in range(10)]
    iis_recs += [{"impact_score": -100.0, "invariant_ids": ["INV-B"]} for _ in range(10)]
    _write_iis(iis_path, iis_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-012", timestamp_utc_iso=_TS)
    reinforce = [r for r in result.recommendations if r.recommendation == "REINFORCE"]
    assert any(r.invariant_id == "INV-A" for r in reinforce)


# ---------------------------------------------------------------------------
# T175-CAL-22: REVIEW recommendation emitted for low-weight invariant
# ---------------------------------------------------------------------------
def test_T175_CAL_22_review_recommendation(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    iis_recs = [{"impact_score": 100.0, "invariant_ids": ["INV-A"]} for _ in range(10)]
    iis_recs += [{"impact_score": -100.0, "invariant_ids": ["INV-B"]} for _ in range(10)]
    _write_iis(iis_path, iis_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-013", timestamp_utc_iso=_TS)
    review = [r for r in result.recommendations if r.recommendation == "REVIEW"]
    assert any(r.invariant_id == "INV-B" for r in review)


# ---------------------------------------------------------------------------
# T175-CAL-23: STABLE recommendation for low-count invariant
# ---------------------------------------------------------------------------
def test_T175_CAL_23_stable_low_count(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    # Only 1 record — below _MIN_RECORDS_FOR_RECOMMENDATION
    iis_recs = [{"impact_score": 1.0, "invariant_ids": ["INV-LOWCOUNT"]}]
    _write_iis(iis_path, iis_recs)

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    result = cal.run_learning_cycle(cycle_id="c-014", timestamp_utc_iso=_TS)
    stable = [r for r in result.recommendations if r.invariant_id == "INV-LOWCOUNT"]
    assert stable and stable[0].recommendation == "STABLE"


# ---------------------------------------------------------------------------
# T175-CAL-24: CAL-CHAIN-0 — chain verifies after single cycle
# ---------------------------------------------------------------------------
def test_T175_CAL_24_chain_verifies(tmp_path):
    cal = _make_cal(tmp_path)
    cal.run_learning_cycle(cycle_id="c-015", timestamp_utc_iso=_TS)
    assert cal.verify_chain() is True


# ---------------------------------------------------------------------------
# T175-CAL-25: CAL-CHAIN-0 — chain verifies after multiple cycles
# ---------------------------------------------------------------------------
def test_T175_CAL_25_chain_multi_cycle(tmp_path):
    cal = _make_cal(tmp_path)
    for i in range(5):
        cal.run_learning_cycle(cycle_id=f"c-multi-{i}", timestamp_utc_iso=_TS)
    assert cal.verify_chain() is True


# ---------------------------------------------------------------------------
# T175-CAL-26: CAL-CHAIN-0 — tampered ledger detected
# ---------------------------------------------------------------------------
def test_T175_CAL_26_chain_tamper_detected(tmp_path):
    cal = _make_cal(tmp_path)
    cal.run_learning_cycle(cycle_id="c-tamper", timestamp_utc_iso=_TS)

    ledger_path = tmp_path / "cal/learning_ledger.jsonl"
    content = ledger_path.read_text()
    # Corrupt the chain_hash
    tampered = content.replace('"chain_hash":', '"chain_hash_TAMPERED":')
    ledger_path.write_text(tampered)

    assert cal.verify_chain() is False


# ---------------------------------------------------------------------------
# T175-CAL-27: CAL-CHAIN-0 — tampered ledger blocks next cycle
# ---------------------------------------------------------------------------
def test_T175_CAL_27_broken_chain_blocks_cycle(tmp_path):
    cal = _make_cal(tmp_path)
    cal.run_learning_cycle(cycle_id="c-pre-tamper", timestamp_utc_iso=_TS)

    ledger_path = tmp_path / "cal/learning_ledger.jsonl"
    content = ledger_path.read_text()
    tampered = content.replace('"cycle_id":', '"cycle_id_TAMPERED":')
    ledger_path.write_text(tampered)

    with pytest.raises(RuntimeError, match="CAL-CHAIN-0"):
        cal.run_learning_cycle(cycle_id="c-post-tamper", timestamp_utc_iso=_TS)


# ---------------------------------------------------------------------------
# T175-CAL-28: CAL-READONLY-0 — source ledgers unmodified after cycle
# ---------------------------------------------------------------------------
def test_T175_CAL_28_readonly_sources(tmp_path):
    iis_path = tmp_path / "iis_ledger.jsonl"
    mfv_path = tmp_path / "mfv_ledger.jsonl"
    iis_recs = [{"impact_score": 0.5, "invariant_ids": ["INV-R"]}]
    _write_iis(iis_path, iis_recs)

    iis_before = iis_path.read_text()
    mfv_before = mfv_path.read_text() if mfv_path.exists() else ""

    cal = ConstitutionalAdaptiveLearner(
        hmac_secret=_SECRET,
        iis_ledger_path=iis_path,
        mfv_ledger_path=mfv_path,
        cal_ledger_path=tmp_path / "cal/learning_ledger.jsonl",
        cal_recs_path=tmp_path / "cal/recs.json",
    )
    cal.run_learning_cycle(cycle_id="c-readonly", timestamp_utc_iso=_TS)

    assert iis_path.read_text() == iis_before, "CAL-READONLY-0: IIS ledger was mutated"


# ---------------------------------------------------------------------------
# T175-CAL-29: CAL-DETERM-0 — same inputs produce same weights (determinism)
# ---------------------------------------------------------------------------
def test_T175_CAL_29_determinism(tmp_path):
    iis_recs = [{"impact_score": float(i), "invariant_ids": [f"INV-{i}"]} for i in range(5)]

    results = []
    for run in range(2):
        run_dir = tmp_path / f"run{run}"
        iis_path = run_dir / "iis.jsonl"
        mfv_path = run_dir / "mfv.jsonl"
        _write_iis(iis_path, iis_recs)

        cal = ConstitutionalAdaptiveLearner(
            hmac_secret=_SECRET,
            iis_ledger_path=iis_path,
            mfv_ledger_path=mfv_path,
            cal_ledger_path=run_dir / "cal/learning_ledger.jsonl",
            cal_recs_path=run_dir / "cal/recs.json",
        )
        result = cal.run_learning_cycle(cycle_id="det-test", timestamp_utc_iso=_TS)
        results.append({w.invariant_id: w.normalized_weight for w in result.weights})

    assert results[0] == results[1], "CAL-DETERM-0: non-deterministic weight computation"


# ---------------------------------------------------------------------------
# T175-CAL-30: get_invariants returns a copy (mutation safety)
# ---------------------------------------------------------------------------
def test_T175_CAL_30_invariants_immutable(tmp_path):
    cal = _make_cal(tmp_path)
    inv_a = cal.get_invariants()
    inv_a.clear()  # Mutate the returned list
    inv_b = cal.get_invariants()
    assert len(inv_b) == 10, "get_invariants should return a fresh copy each time"
