# SPDX-License-Identifier: Apache-2.0
"""Phase 203 · INNOV-108 · CGDR — Acceptance tests.
30 tests organised by invariant group.
T203-CGDR-01 … T203-CGDR-10  CGDR-CHAIN-0 / CGDR-IMMUT-0 / CGDR-SEAL-0
T203-CGDR-11 … T203-CGDR-15  CGDR-DETERM-0
T203-CGDR-16 … T203-CGDR-20  CGDR-BASELINE-0 / CGDR-FAILCLOSED-0
T203-CGDR-21 … T203-CGDR-25  CGDR-HUMAN0-0 / CGDR-GATE-0
T203-CGDR-26 … T203-CGDR-30  CGDR-AUDIT-0 / CGDR-SCOPE-0 / integration
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dorkllm.convergence_governance_drift_reporter import (
    CCA_CRITERIA,
    CGDRDriftGateError,
    CGDRHuman0Error,
    CGDRViolation,
    ConvergenceGovernanceDriftReporter,
    _assess_criteria,
)

# ── helpers ───────────────────────────────────────────────────────────────────
PASSING_SNAPSHOT: dict = {
    "gir_snapshot": {"readiness_score": 1.0},
    "hard_invariant_count": 647,
    "innovations_shipped": 107,
    "hard_class_invariants": 647,
    "cel_loop_status": "FULLY CLOSED",
    "v10_ready": True,
    "schema_version": "1.0",
}

DRIFTED_SNAPSHOT: dict = {
    "gir_snapshot": {"readiness_score": 0.5},
    "hard_invariant_count": 200,
    "innovations_shipped": 50,
    "hard_class_invariants": None,
    "cel_loop_status": "OPEN",
    "v10_ready": False,
    "schema_version": "",
}


def _engine(tmp_path: Path) -> ConvergenceGovernanceDriftReporter:
    return ConvergenceGovernanceDriftReporter(
        ledger_path=tmp_path / "drift_ledger.jsonl",
        baseline_path=tmp_path / "baseline.json",
    )


# ── T203-CGDR-01 … 10 — CHAIN / IMMUT / SEAL ─────────────────────────────────
def test_t203_cgdr_01_chain_link_present(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", PASSING_SNAPSHOT)
    assert r.chain_link.startswith("hmac-sha256:")


def test_t203_cgdr_02_prev_digest_genesis_on_first(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", PASSING_SNAPSHOT)
    assert r.prev_digest.startswith("sha256:")


def test_t203_cgdr_03_chain_links_sequential(tmp_path):
    eng = _engine(tmp_path)
    r1 = eng.assess("ep1", PASSING_SNAPSHOT)
    r2 = eng.assess("ep2", PASSING_SNAPSHOT)
    assert r2.prev_digest == r1.chain_link


def test_t203_cgdr_04_verify_chain_passes_on_clean_ledger(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    eng.assess("ep2", PASSING_SNAPSHOT)
    assert eng.verify_chain() is True


def test_t203_cgdr_05_verify_chain_empty_ledger(tmp_path):
    eng = _engine(tmp_path)
    assert eng.verify_chain() is True


def test_t203_cgdr_06_ledger_is_append_only(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    size_after_first = (tmp_path / "drift_ledger.jsonl").stat().st_size
    eng.assess("ep2", PASSING_SNAPSHOT)
    size_after_second = (tmp_path / "drift_ledger.jsonl").stat().st_size
    assert size_after_second > size_after_first


def test_t203_cgdr_07_report_digest_present(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", PASSING_SNAPSHOT)
    assert r.report_digest.startswith("sha256:")
    assert len(r.report_digest) > 16


def test_t203_cgdr_08_seal_covers_all_criteria(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", PASSING_SNAPSHOT)
    assert len(r.criteria_results) == 8


def test_t203_cgdr_09_ledger_records_parseable_json(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    eng.assess("ep2", DRIFTED_SNAPSHOT)
    lines = (tmp_path / "drift_ledger.jsonl").read_text().strip().splitlines()
    for line in lines:
        rec = json.loads(line)
        assert "event_type" in rec


def test_t203_cgdr_10_chain_link_tamper_detected(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    ledger = tmp_path / "drift_ledger.jsonl"
    data = ledger.read_text()
    # Tamper chain_link
    tampered = data.replace("hmac-sha256:", "hmac-sha256:xx")
    ledger.write_text(tampered)
    eng2 = _engine(tmp_path)
    assert eng2.verify_chain() is False


# ── T203-CGDR-11 … 15 — DETERM ───────────────────────────────────────────────
def test_t203_cgdr_11_identical_inputs_same_report_id(tmp_path):
    eng1 = _engine(tmp_path)
    eng2 = ConvergenceGovernanceDriftReporter(
        ledger_path=tmp_path / "drift2.jsonl",
        baseline_path=tmp_path / "base2.json",
    )
    r1 = eng1.assess("epX", PASSING_SNAPSHOT)
    r2 = eng2.assess("epX", PASSING_SNAPSHOT)
    assert r1.report_id == r2.report_id


def test_t203_cgdr_12_identical_inputs_same_digest(tmp_path):
    eng1 = _engine(tmp_path)
    eng2 = ConvergenceGovernanceDriftReporter(
        ledger_path=tmp_path / "drift2.jsonl",
        baseline_path=tmp_path / "base2.json",
    )
    r1 = eng1.assess("epX", PASSING_SNAPSHOT)
    r2 = eng2.assess("epX", PASSING_SNAPSHOT)
    assert r1.report_digest == r2.report_digest


def test_t203_cgdr_13_different_epoch_different_id(tmp_path):
    eng = _engine(tmp_path)
    r1 = eng.assess("ep-A", PASSING_SNAPSHOT)
    r2 = eng.assess("ep-B", PASSING_SNAPSHOT)
    assert r1.report_id != r2.report_id


def test_t203_cgdr_14_different_snapshot_different_id(tmp_path):
    eng = _engine(tmp_path)
    snap2 = {**PASSING_SNAPSHOT, "innovations_shipped": 110}
    r1 = eng.assess("ep1", PASSING_SNAPSHOT)
    r2 = eng.assess("ep1", snap2)
    assert r1.report_id != r2.report_id


def test_t203_cgdr_15_report_id_prefix(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", PASSING_SNAPSHOT)
    assert r.report_id.startswith("cgdr:")


# ── T203-CGDR-16 … 20 — BASELINE / FAILCLOSED ────────────────────────────────
def test_t203_cgdr_16_baseline_saved_on_passing(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    assert (tmp_path / "baseline.json").exists()


def test_t203_cgdr_17_baseline_not_updated_on_drifted(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    mtime1 = (tmp_path / "baseline.json").stat().st_mtime
    eng.assess("ep2", DRIFTED_SNAPSHOT)
    mtime2 = (tmp_path / "baseline.json").stat().st_mtime
    assert mtime1 == mtime2


def test_t203_cgdr_18_failclosed_on_bad_snapshot(tmp_path):
    eng = _engine(tmp_path)
    # Pass a snapshot that causes _assess_criteria to handle gracefully
    r = eng.assess("ep1", {})  # all fields missing → all criteria fail
    assert r.status == "DRIFTED"
    assert len(r.drifted_criteria) == 8


def test_t203_cgdr_19_passing_score_is_1_0(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", PASSING_SNAPSHOT)
    assert r.overall_score == 1.0
    assert r.status == "PASSING"


def test_t203_cgdr_20_drifted_score_less_than_1(tmp_path):
    eng = _engine(tmp_path)
    r = eng.assess("ep1", DRIFTED_SNAPSHOT)
    assert r.overall_score < 1.0
    assert r.status == "DRIFTED"


# ── T203-CGDR-21 … 25 — HUMAN0 / GATE ───────────────────────────────────────
def test_t203_cgdr_21_gate_raises_on_drifted(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", DRIFTED_SNAPSHOT)
    with pytest.raises(CGDRDriftGateError):
        eng.assert_no_drift("test-phase")


def test_t203_cgdr_22_gate_passes_on_passing(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    eng.assert_no_drift("test-phase")  # should not raise


def test_t203_cgdr_23_clear_drift_requires_human_id(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", DRIFTED_SNAPSHOT)
    with pytest.raises(CGDRHuman0Error):
        eng.clear_drift("")


def test_t203_cgdr_24_clear_drift_clears_flag(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", DRIFTED_SNAPSHOT)
    assert eng.is_drifted() is True
    eng.clear_drift("HUMAN-0-dustin")
    assert eng.is_drifted() is False


def test_t203_cgdr_25_gate_passes_after_clear(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", DRIFTED_SNAPSHOT)
    eng.clear_drift("HUMAN-0-dustin", note="manual review passed")
    eng.assert_no_drift("post-clear-phase")  # should not raise


# ── T203-CGDR-26 … 30 — AUDIT / SCOPE / INTEGRATION ─────────────────────────
def test_t203_cgdr_26_clear_drift_ledgered(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", DRIFTED_SNAPSHOT)
    eng.clear_drift("HUMAN-0-dustin")
    lines = (tmp_path / "drift_ledger.jsonl").read_text().strip().splitlines()
    events = [json.loads(l)["event_type"] for l in lines]
    assert "clear_drift" in events


def test_t203_cgdr_27_scope_exactly_8_criteria(tmp_path):
    assert len(CCA_CRITERIA) == 8


def test_t203_cgdr_28_summary_keys_present(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    s = eng.summary()
    for key in ("system_drifted", "latest_status", "latest_score", "assessed_at"):
        assert key in s


def test_t203_cgdr_29_latest_report_returns_most_recent(tmp_path):
    eng = _engine(tmp_path)
    eng.assess("ep1", PASSING_SNAPSHOT)
    eng.assess("ep2", DRIFTED_SNAPSHOT)
    r = eng.latest_report()
    assert r.epoch_id == "ep2"
    assert r.status == "DRIFTED"


def test_t203_cgdr_30_end_to_end_convergence_assessment(tmp_path):
    """Integration: assess passing V10 state → verify chain → no drift → summary."""
    eng = _engine(tmp_path)
    report = eng.assess("phase203-integration", PASSING_SNAPSHOT)
    assert report.status == "PASSING"
    assert report.overall_score == 1.0
    assert eng.verify_chain() is True
    eng.assert_no_drift("phase203-integration")
    s = eng.summary()
    assert s["system_drifted"] is False
    assert s["latest_score"] == 1.0
