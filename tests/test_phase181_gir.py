# SPDX-License-Identifier: Apache-2.0
"""
Phase 181 · INNOV-86 · GIR — Governance Implementation Readiness
Test suite: T181-GIR-01..30  (30/30 required)
Governor: DUSTIN L REID
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Isolate all file I/O to a temp directory ─────────────────────────────────
@pytest.fixture(autouse=True)
def isolated_fs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield tmp_path


import importlib
import dorkllm.governance_implementation_readiness as gir_mod


def reload_gir(tmp_path):
    """Reload module so Path constants resolve relative to tmp_path cwd."""
    importlib.reload(gir_mod)
    return gir_mod


# ── T181-GIR-01: Basic assessment returns dict ───────────────────────────────
def test_T181_GIR_01_returns_dict(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v9.114.0")
    assert isinstance(result, dict)


# ── T181-GIR-02: assessment_id is a UUID string ──────────────────────────────
def test_T181_GIR_02_assessment_id_uuid(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v9.114.0")
    import uuid
    uuid.UUID(result["assessment_id"])  # raises if invalid


# ── T181-GIR-03: All 6 dimensions present ────────────────────────────────────
def test_T181_GIR_03_all_dimensions_present(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("milestone-A")
    for dim in g.DIMENSIONS:
        assert dim in result["dimension_scores"]


# ── T181-GIR-04: GRS is float in [0, 1] ─────────────────────────────────────
def test_T181_GIR_04_grs_bounded(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("milestone-B")
    assert 0.0 <= result["grs"] <= 1.0


# ── T181-GIR-05: promotion_threshold constant is 0.75 ────────────────────────
def test_T181_GIR_05_promotion_threshold_constant(tmp_path):
    g = reload_gir(tmp_path)
    assert g.PROMOTION_THRESHOLD == 0.75


# ── T181-GIR-06: Without human0_token, status is READY or NOT_READY ─────────
def test_T181_GIR_06_no_token_status(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v-test")
    assert result["promotion_status"] in {"READY", "NOT_READY"}


# ── T181-GIR-07: With token and GRS >= threshold → PROMOTED ─────────────────
def test_T181_GIR_07_promoted_with_token(tmp_path):
    g = reload_gir(tmp_path)
    # All defaults → no pressure, no rollbacks → high GRS
    result = g.run_readiness_assessment("v-milestone", human0_token="APPROVED DUSTIN L REID")
    if result["grs"] >= g.PROMOTION_THRESHOLD:
        assert result["promotion_status"] == "PROMOTED"


# ── T181-GIR-08: With token but GRS < threshold → PROMOTION_DENIED ───────────
def test_T181_GIR_08_promotion_denied_low_grs(tmp_path):
    g = reload_gir(tmp_path)
    # Force critical SCSI alert → stability score 0 → low GRS
    snap = {"scsi": 0.3}
    (tmp_path / "data" / "csc").mkdir(parents=True)
    (tmp_path / "data" / "csc" / "scsi_snapshot.json").write_text(json.dumps(snap))
    importlib.reload(g)
    result = g.run_readiness_assessment("v-fail", human0_token="APPROVED DUSTIN L REID")
    assert result["promotion_status"] == "PROMOTION_DENIED"


# ── T181-GIR-09: Rejected promotions written to rejected ledger ──────────────
def test_T181_GIR_09_rejected_ledger_written(tmp_path):
    g = reload_gir(tmp_path)
    snap = {"scsi": 0.3}
    (tmp_path / "data" / "csc").mkdir(parents=True)
    (tmp_path / "data" / "csc" / "scsi_snapshot.json").write_text(json.dumps(snap))
    importlib.reload(g)
    g.run_readiness_assessment("v-rej", human0_token="APPROVED DUSTIN L REID")
    rejected = tmp_path / "data" / "gir" / "rejected_promotions.jsonl"
    assert rejected.exists()
    lines = [l for l in rejected.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1


# ── T181-GIR-10: Ledger file created after assessment ────────────────────────
def test_T181_GIR_10_ledger_created(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-ledger")
    assert (tmp_path / "data" / "gir" / "readiness_attestation_ledger.jsonl").exists()


# ── T181-GIR-11: Snapshot file created and parseable ─────────────────────────
def test_T181_GIR_11_snapshot_created(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-snap")
    snap = tmp_path / "data" / "gir" / "readiness_snapshot.json"
    assert snap.exists()
    data = json.loads(snap.read_text())
    assert "grs" in data


# ── T181-GIR-12: HMAC chain valid after single write ─────────────────────────
def test_T181_GIR_12_chain_valid_single(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-chain1")
    report = g.verify_ledger_integrity()
    assert report["chain_valid"] is True


# ── T181-GIR-13: HMAC chain valid after multiple writes ──────────────────────
def test_T181_GIR_13_chain_valid_multiple(tmp_path):
    g = reload_gir(tmp_path)
    for i in range(5):
        g.run_readiness_assessment(f"v-iter-{i}")
    report = g.verify_ledger_integrity()
    assert report["chain_valid"] is True
    assert report["entry_count"] == 5


# ── T181-GIR-14: Tampered ledger detected ────────────────────────────────────
def test_T181_GIR_14_tamper_detected(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-tamper")
    ledger = tmp_path / "data" / "gir" / "readiness_attestation_ledger.jsonl"
    content = ledger.read_text()
    ledger.write_text(content.replace('"grs":', '"grs_tampered":'))
    report = g.verify_ledger_integrity()
    assert report["chain_valid"] is False


# ── T181-GIR-15: GIR-CHAIN-0 violation raised on corrupt chain ───────────────
def test_T181_GIR_15_chain_violation_on_corrupt(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-corrupt")
    ledger = tmp_path / "data" / "gir" / "readiness_attestation_ledger.jsonl"
    ledger.write_text('{"chain_digest":"badhash","attestation":{"grs":0.5}}\n')
    with pytest.raises(g.GIRViolation):
        g.run_readiness_assessment("v-post-corrupt")


# ── T181-GIR-16: Stability dimension reads CSC SCSI correctly ────────────────
def test_T181_GIR_16_stability_reads_scsi(tmp_path):
    g = reload_gir(tmp_path)
    (tmp_path / "data" / "csc").mkdir(parents=True)
    (tmp_path / "data" / "csc" / "scsi_snapshot.json").write_text(json.dumps({"scsi": 0.9}))
    importlib.reload(g)
    result = g.run_readiness_assessment("v-stab")
    assert result["subsystem_signals"]["scsi"] == 0.9
    assert result["dimension_scores"]["stability"] == pytest.approx(0.9, abs=0.01)


# ── T181-GIR-17: Critical SCSI alert → stability score 0.0 ──────────────────
def test_T181_GIR_17_critical_scsi_zero_stability(tmp_path):
    g = reload_gir(tmp_path)
    (tmp_path / "data" / "csc").mkdir(parents=True)
    (tmp_path / "data" / "csc" / "scsi_snapshot.json").write_text(json.dumps({"scsi": 0.3}))
    importlib.reload(g)
    result = g.run_readiness_assessment("v-critical")
    assert result["dimension_scores"]["stability"] == 0.0
    assert result["subsystem_signals"]["critical_alert"] is True


# ── T181-GIR-18: Pressure score: 0 high-pressure events → 1.0 ───────────────
def test_T181_GIR_18_zero_pressure_score_1(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v-nopress")
    # No CPI ledger → pressure ratio 0.0 → score 1.0
    assert result["dimension_scores"]["pressure"] == 1.0


# ── T181-GIR-19: Pressure score decays with high-tension events ──────────────
def test_T181_GIR_19_pressure_decays(tmp_path):
    g = reload_gir(tmp_path)
    (tmp_path / "data" / "cpi").mkdir(parents=True)
    # 10 high-tension events out of 10 → ratio 1.0 → pressure score 0.0
    ledger = tmp_path / "data" / "cpi" / "pressure_ledger.jsonl"
    with open(ledger, "w") as fh:
        for _ in range(10):
            entry = {"attestation": {"tension_delta": 0.8}, "prev_digest": "x", "chain_digest": "y"}
            fh.write(json.dumps(entry) + "\n")
    importlib.reload(g)
    result = g.run_readiness_assessment("v-press")
    assert result["dimension_scores"]["pressure"] == 0.0


# ── T181-GIR-20: Amendment score decays with pending recs ────────────────────
def test_T181_GIR_20_amendment_score_decays(tmp_path):
    g = reload_gir(tmp_path)
    (tmp_path / "data" / "cal").mkdir(parents=True)
    recs = [{"status": "PENDING"} for _ in range(5)]
    (tmp_path / "data" / "cal" / "cal_amendment_recommendations.json").write_text(
        json.dumps({"recommendations": recs})
    )
    importlib.reload(g)
    result = g.run_readiness_assessment("v-amend")
    # 5 pending → 1.0 - 0.5 = 0.5
    assert result["dimension_scores"]["amendment"] == pytest.approx(0.5, abs=0.01)


# ── T181-GIR-21: 0 pending amendments → amendment score 1.0 ─────────────────
def test_T181_GIR_21_zero_amendments_score_1(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v-no-amend")
    assert result["dimension_scores"]["amendment"] == 1.0


# ── T181-GIR-22: Active rollbacks decay rollback score ───────────────────────
def test_T181_GIR_22_rollback_score_decays(tmp_path):
    g = reload_gir(tmp_path)
    (tmp_path / "data" / "car").mkdir(parents=True)
    ledger = tmp_path / "data" / "car" / "rollback_execution_ledger.jsonl"
    with open(ledger, "w") as fh:
        for _ in range(2):
            entry = {"attestation": {"status": "EXECUTED"}, "prev_digest": "x", "chain_digest": "y"}
            fh.write(json.dumps(entry) + "\n")
    importlib.reload(g)
    result = g.run_readiness_assessment("v-rollback")
    # 2 active → 1.0 - 0.5 = 0.5
    assert result["dimension_scores"]["rollback"] == pytest.approx(0.5, abs=0.01)


# ── T181-GIR-23: 0 active rollbacks → rollback score 1.0 ────────────────────
def test_T181_GIR_23_zero_rollbacks_score_1(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v-no-rollback")
    assert result["dimension_scores"]["rollback"] == 1.0


# ── T181-GIR-24: Integrity score uses invariant count ───────────────────────
def test_T181_GIR_24_integrity_uses_invariant_count(tmp_path):
    g = reload_gir(tmp_path)
    state = {"hard_class_invariants": 400}
    (tmp_path / ".adaad_agent_state.json").write_text(json.dumps(state))
    importlib.reload(g)
    result = g.run_readiness_assessment("v-integrity")
    assert result["dimension_scores"]["integrity"] == 1.0


# ── T181-GIR-25: GRS weighted mean is deterministic ─────────────────────────
def test_T181_GIR_25_grs_deterministic(tmp_path):
    g = reload_gir(tmp_path)
    r1 = g.run_readiness_assessment("v-det-1")
    (tmp_path / "data" / "gir" / "readiness_attestation_ledger.jsonl").write_text("")
    importlib.reload(g)
    r2 = g.run_readiness_assessment("v-det-2")
    # Same subsystem signals → same GRS (assessment_id differs, GRS must match)
    assert r1["grs"] == r2["grs"]


# ── T181-GIR-26: seal_hash present and is SHA-256 hex ───────────────────────
def test_T181_GIR_26_seal_hash_present(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v-seal")
    assert "seal_hash" in result
    assert len(result["seal_hash"]) == 64
    int(result["seal_hash"], 16)  # raises if not hex


# ── T181-GIR-27: human0_token_present flag is accurate ──────────────────────
def test_T181_GIR_27_human0_token_flag(tmp_path):
    g = reload_gir(tmp_path)
    r_no  = g.run_readiness_assessment("v-flag-no")
    r_yes = g.run_readiness_assessment("v-flag-yes", human0_token="APPROVED DUSTIN L REID")
    assert r_no["human0_token_present"]  is False
    assert r_yes["human0_token_present"] is True


# ── T181-GIR-28: get_readiness_history returns list ──────────────────────────
def test_T181_GIR_28_history_returns_list(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-hist-1")
    g.run_readiness_assessment("v-hist-2")
    history = g.get_readiness_history()
    assert isinstance(history, list)
    assert len(history) == 2


# ── T181-GIR-29: get_readiness_snapshot returns latest ──────────────────────
def test_T181_GIR_29_snapshot_is_latest(tmp_path):
    g = reload_gir(tmp_path)
    g.run_readiness_assessment("v-snap-1")
    g.run_readiness_assessment("v-snap-2")
    snap = g.get_readiness_snapshot()
    assert snap["milestone_label"] == "v-snap-2"


# ── T181-GIR-30: INNOV and governor fields present in attestation ────────────
def test_T181_GIR_30_governance_metadata(tmp_path):
    g = reload_gir(tmp_path)
    result = g.run_readiness_assessment("v-gov-meta")
    assert result["innov"] == "INNOV-86"
    assert result["governor"] == "DUSTIN L REID"
    assert result["schema_version"] == "1.0"
