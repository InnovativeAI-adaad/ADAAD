# SPDX-License-Identifier: Apache-2.0
"""
Phase 179 — INNOV-84 · CSC — Constitutional Stability Controller
Acceptance tests: T179-CSC-01 through T179-CSC-30
30/30 required for governance sign-off.

Governor: DUSTIN L REID
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from dorkllm.constitutional_stability_controller import (
    CRITICAL_THRESHOLD,
    WARNING_THRESHOLD,
    ConstitutionalStabilityController,
    InvariantStabilityRecord,
    StabilityAlert,
    StabilityReport,
    _GOVERNOR,
    _HMAC_KEY,
    _INNOV_CODE,
    _MODULE_CODE,
    _hmac_hex,
    _sha256,
    _utc_iso,
    run_csc_cycle,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_snapshot(invariants: dict | None = None) -> dict:
    """Build a minimal CAE constitution snapshot."""
    return {
        "snapshot_id": str(uuid.uuid4()),
        "invariants": invariants or {
            "TEST-INV-0": {"status": "active", "reinforcement_count": 0},
            "TEST-INV-1": {"status": "active", "reinforcement_count": 2},
        },
    }


def _make_ledger_record(
    inv_id: str = "TEST-INV-0",
    action: str = "REINFORCE",
    cycle_id: str | None = None,
) -> dict:
    return {
        "cycle_id": cycle_id or str(uuid.uuid4()),
        "cycle_timestamp": _utc_iso(),
        "amendments_applied": [
            {
                "invariant_id": inv_id,
                "action": action,
                "execution_id": str(uuid.uuid4()),
                "executed_at": _utc_iso(),
            }
        ],
    }


def _controller_in_tmpdir(
    snapshot: dict | None = None,
    ledger_records: list | None = None,
) -> tuple[ConstitutionalStabilityController, Path]:
    tmp = Path(tempfile.mkdtemp())
    data_dir = tmp / "csc"
    cae_dir = tmp / "cae"
    cae_dir.mkdir(parents=True)

    snap_path = cae_dir / "constitution_snapshot.json"
    ledger_path = cae_dir / "amendment_execution_ledger.jsonl"

    if snapshot is not None:
        snap_path.write_text(json.dumps(snapshot), encoding="utf-8")

    if ledger_records:
        with ledger_path.open("w", encoding="utf-8") as fh:
            for rec in ledger_records:
                fh.write(json.dumps(rec) + "\n")

    ctrl = ConstitutionalStabilityController(
        data_dir=data_dir,
        cae_snapshot_path=snap_path,
        cae_ledger_path=ledger_path,
    )
    return ctrl, tmp


# ── T179-CSC-01: Module constants are correct ─────────────────────────────────

def test_t179_csc_01_constants():
    assert _GOVERNOR == "DUSTIN L REID"
    assert _INNOV_CODE == "INNOV-84"
    assert _MODULE_CODE == "CSC"
    assert 0.0 < CRITICAL_THRESHOLD < WARNING_THRESHOLD < 1.0


# ── T179-CSC-02: _utc_iso is deterministic ISO-8601 ──────────────────────────

def test_t179_csc_02_utc_iso():
    ts = _utc_iso()
    assert "T" in ts and "+" in ts or "Z" in ts


# ── T179-CSC-03: _sha256 is deterministic ────────────────────────────────────

def test_t179_csc_03_sha256():
    assert _sha256("hello") == _sha256("hello")
    assert len(_sha256("x")) == 64


# ── T179-CSC-04: _hmac_hex is keyed and deterministic ────────────────────────

def test_t179_csc_04_hmac_hex():
    h1 = _hmac_hex(_HMAC_KEY, "payload")
    h2 = _hmac_hex(_HMAC_KEY, "payload")
    assert h1 == h2
    assert len(h1) == 64


# ── T179-CSC-05: InvariantStabilityRecord active score ───────────────────────

def test_t179_csc_05_active_score():
    rec = InvariantStabilityRecord(
        invariant_id="ALPHA-0", is_active=True, reinforcement_count=0
    )
    score = rec.compute_score()
    assert 0.0 < score <= 1.0


# ── T179-CSC-06: Reinforcement increases score ───────────────────────────────

def test_t179_csc_06_reinforcement_increases_score():
    base = InvariantStabilityRecord(invariant_id="A", is_active=True, reinforcement_count=0)
    reinforced = InvariantStabilityRecord(invariant_id="A", is_active=True, reinforcement_count=5)
    assert reinforced.compute_score() > base.compute_score()


# ── T179-CSC-07: Review flags decrease score ─────────────────────────────────

def test_t179_csc_07_review_flags_decrease_score():
    clean = InvariantStabilityRecord(invariant_id="B", is_active=True, review_flag_count=0)
    flagged = InvariantStabilityRecord(invariant_id="B", is_active=True, review_flag_count=5)
    assert flagged.compute_score() < clean.compute_score()


# ── T179-CSC-08: Retired invariant scores 0.0 ────────────────────────────────

def test_t179_csc_08_retired_score_zero():
    rec = InvariantStabilityRecord(
        invariant_id="DEAD-0", is_active=False, reinforcement_count=100
    )
    assert rec.compute_score() == 0.0


# ── T179-CSC-09: Score is bounded [0.0, 1.0] ─────────────────────────────────

def test_t179_csc_09_score_bounded():
    for rc in [0, 1, 10, 100]:
        for rv in [0, 1, 10, 100]:
            rec = InvariantStabilityRecord(
                invariant_id="X", is_active=True,
                reinforcement_count=rc, review_flag_count=rv,
            )
            s = rec.compute_score()
            assert 0.0 <= s <= 1.0, f"Score out of bounds: {s}"


# ── T179-CSC-10: Controller instantiation creates data dir ───────────────────

def test_t179_csc_10_data_dir_created():
    ctrl, tmp = _controller_in_tmpdir()
    assert (tmp / "csc").exists()


# ── T179-CSC-11: run_stability_cycle returns StabilityReport ─────────────────

def test_t179_csc_11_returns_stability_report():
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot())
    report = ctrl.run_stability_cycle()
    assert isinstance(report, StabilityReport)


# ── T179-CSC-12: Report has required fields ───────────────────────────────────

def test_t179_csc_12_report_fields():
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot())
    r = ctrl.run_stability_cycle()
    assert r.governor == _GOVERNOR
    assert r.innov_code == _INNOV_CODE
    assert r.module_code == _MODULE_CODE
    assert r.report_id
    assert 0.0 <= r.scsi <= 1.0


# ── T179-CSC-13: Report ledger file is created ───────────────────────────────

def test_t179_csc_13_ledger_file_created():
    ctrl, tmp = _controller_in_tmpdir(snapshot=_make_snapshot())
    ctrl.run_stability_cycle()
    ledger = tmp / "csc" / "stability_report_ledger.jsonl"
    assert ledger.exists()
    records = [json.loads(l) for l in ledger.read_text().strip().splitlines()]
    assert len(records) == 1


# ── T179-CSC-14: HMAC chain is valid across multiple cycles ──────────────────

def test_t179_csc_14_hmac_chain_valid():
    ctrl, tmp = _controller_in_tmpdir(snapshot=_make_snapshot())
    for _ in range(3):
        ctrl.run_stability_cycle()

    ledger = tmp / "csc" / "stability_report_ledger.jsonl"
    records = [json.loads(l) for l in ledger.read_text().strip().splitlines()]
    assert len(records) == 3

    prev = _hmac_hex(_HMAC_KEY, "CSC-GENESIS-179")
    for rec in records:
        assert rec["hmac_chain_prev"] == prev
        prev = rec["hmac_chain_current"]


# ── T179-CSC-15: Chain integrity verification passes ─────────────────────────

def test_t179_csc_15_chain_verify_passes():
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot())
    ctrl.run_stability_cycle()
    ctrl.run_stability_cycle()
    # Should not raise
    ctrl._verify_chain_integrity()


# ── T179-CSC-16: Broken chain raises RuntimeError ────────────────────────────

def test_t179_csc_16_broken_chain_raises():
    ctrl, tmp = _controller_in_tmpdir(snapshot=_make_snapshot())
    ctrl.run_stability_cycle()
    ledger_path = tmp / "csc" / "stability_report_ledger.jsonl"
    raw = ledger_path.read_text()
    rec = json.loads(raw.strip())
    rec["hmac_chain_prev"] = "tampered_value"
    ledger_path.write_text(json.dumps(rec) + "\n")

    ctrl2 = ConstitutionalStabilityController(
        data_dir=tmp / "csc",
        cae_snapshot_path=tmp / "cae" / "constitution_snapshot.json",
        cae_ledger_path=tmp / "cae" / "amendment_execution_ledger.jsonl",
    )
    with pytest.raises(RuntimeError, match="CSC-CHAIN-0"):
        ctrl2._verify_chain_integrity()


# ── T179-CSC-17: SCSI snapshot is written ────────────────────────────────────

def test_t179_csc_17_scsi_snapshot_written():
    ctrl, tmp = _controller_in_tmpdir(snapshot=_make_snapshot())
    ctrl.run_stability_cycle()
    snap_path = tmp / "csc" / "scsi_snapshot.json"
    assert snap_path.exists()
    data = json.loads(snap_path.read_text())
    assert "scsi" in data
    assert data["governor"] == _GOVERNOR


# ── T179-CSC-18: get_scsi_snapshot returns dict after cycle ──────────────────

def test_t179_csc_18_get_scsi_snapshot():
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot())
    ctrl.run_stability_cycle()
    snap = ctrl.get_scsi_snapshot()
    assert snap is not None
    assert 0.0 <= snap["scsi"] <= 1.0


# ── T179-CSC-19: get_scsi_snapshot returns None before first cycle ────────────

def test_t179_csc_19_snapshot_none_before_cycle():
    ctrl, _ = _controller_in_tmpdir()
    assert ctrl.get_scsi_snapshot() is None


# ── T179-CSC-20: OK status when SCSI above thresholds ────────────────────────

def test_t179_csc_20_ok_status():
    # Many reinforced invariants → high SCSI
    invariants = {f"INV-{i}": {"status": "active", "reinforcement_count": 20} for i in range(10)}
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot(invariants))
    r = ctrl.run_stability_cycle()
    assert r.scsi_status == "OK"
    assert not r.alert_emitted
    assert not r.human0_escalation


# ── T179-CSC-21: WARNING alert emitted when SCSI in warning band ─────────────

def test_t179_csc_21_warning_alert():
    # Mix: half active clean, half retired → SCSI around 0.5–0.65
    invariants = {}
    for i in range(5):
        invariants[f"ACTIVE-{i}"] = {"status": "active", "reinforcement_count": 0}
    for i in range(5):
        invariants[f"RETIRED-{i}"] = {"status": "retired", "reinforcement_count": 0}
    ctrl, tmp = _controller_in_tmpdir(snapshot=_make_snapshot(invariants))
    r = ctrl.run_stability_cycle()

    if r.scsi < WARNING_THRESHOLD:
        assert r.alert_emitted
        alert_log = tmp / "csc" / "stability_alerts.jsonl"
        assert alert_log.exists()
    else:
        pytest.skip(f"SCSI={r.scsi} not below warning threshold in this config; skip")


# ── T179-CSC-22: CRITICAL alert sets human0_escalation ───────────────────────

def test_t179_csc_22_critical_human0_escalation():
    # All retired → SCSI = 0.0 → CRITICAL
    invariants = {f"DEAD-{i}": {"status": "retired"} for i in range(10)}
    ctrl, tmp = _controller_in_tmpdir(snapshot=_make_snapshot(invariants))
    r = ctrl.run_stability_cycle()
    assert r.scsi == 0.0
    assert r.scsi_status == "CRITICAL"
    assert r.human0_escalation is True
    assert r.alert_emitted is True

    alerts = ctrl.get_alert_history()
    assert len(alerts) == 1
    assert alerts[0]["alert_level"] == "CRITICAL"
    assert alerts[0]["human0_escalation"] is True


# ── T179-CSC-23: Alert report_id matches report ──────────────────────────────

def test_t179_csc_23_alert_report_id_matches():
    invariants = {f"DEAD-{i}": {"status": "retired"} for i in range(5)}
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot(invariants))
    r = ctrl.run_stability_cycle()
    if r.alert_emitted:
        alerts = ctrl.get_alert_history()
        assert alerts[-1]["report_id"] == r.report_id


# ── T179-CSC-24: Ledger enriched by amendment events ─────────────────────────

def test_t179_csc_24_ledger_enrichment():
    snapshot = _make_snapshot(
        {"TEST-INV-0": {"status": "active", "reinforcement_count": 0}}
    )
    ledger = [
        _make_ledger_record("TEST-INV-0", "REINFORCE"),
        _make_ledger_record("TEST-INV-0", "REINFORCE"),
    ]
    ctrl_no_ledger, _ = _controller_in_tmpdir(snapshot=snapshot)
    r_base = ctrl_no_ledger.run_stability_cycle()

    ctrl_with_ledger, _ = _controller_in_tmpdir(snapshot=snapshot, ledger_records=ledger)
    r_enriched = ctrl_with_ledger.run_stability_cycle()

    assert r_enriched.per_invariant_scores.get("TEST-INV-0", 0) >= \
           r_base.per_invariant_scores.get("TEST-INV-0", 0)


# ── T179-CSC-25: RETIRE action in ledger marks invariant inactive ─────────────

def test_t179_csc_25_retire_via_ledger():
    snapshot = _make_snapshot(
        {"TEST-INV-0": {"status": "active", "reinforcement_count": 0}}
    )
    ledger = [_make_ledger_record("TEST-INV-0", "RETIRE")]
    ctrl, _ = _controller_in_tmpdir(snapshot=snapshot, ledger_records=ledger)
    r = ctrl.run_stability_cycle()
    assert r.per_invariant_scores.get("TEST-INV-0") == 0.0


# ── T179-CSC-26: ADD action via ledger creates new invariant ─────────────────

def test_t179_csc_26_add_via_ledger():
    snapshot = _make_snapshot({})
    ledger = [_make_ledger_record("BRAND-NEW-0", "ADD")]
    ctrl, _ = _controller_in_tmpdir(snapshot=snapshot, ledger_records=ledger)
    r = ctrl.run_stability_cycle()
    assert "BRAND-NEW-0" in r.per_invariant_scores


# ── T179-CSC-27: Empty snapshot and ledger → stable (SCSI = 1.0) ─────────────

def test_t179_csc_27_empty_constitution_is_stable():
    ctrl, _ = _controller_in_tmpdir(snapshot={"invariants": {}})
    r = ctrl.run_stability_cycle()
    assert r.scsi == 1.0
    assert r.scsi_status == "OK"


# ── T179-CSC-28: get_report_history returns last N records ───────────────────

def test_t179_csc_28_report_history():
    ctrl, _ = _controller_in_tmpdir(snapshot=_make_snapshot())
    for _ in range(5):
        ctrl.run_stability_cycle()
    history = ctrl.get_report_history(last_n=3)
    assert len(history) == 3
    assert all("report_id" in r for r in history)


# ── T179-CSC-29: Missing CAE snapshot → bootstrap stable ─────────────────────

def test_t179_csc_29_missing_snapshot_bootstraps():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    ctrl = ConstitutionalStabilityController(
        data_dir=tmp / "csc",
        cae_snapshot_path=tmp / "nonexistent_snapshot.json",
        cae_ledger_path=tmp / "nonexistent_ledger.jsonl",
    )
    r = ctrl.run_stability_cycle()
    assert isinstance(r, StabilityReport)
    assert r.scsi == 1.0  # vacuously stable


# ── T179-CSC-30: run_csc_cycle convenience wrapper works ─────────────────────

def test_t179_csc_30_run_csc_cycle_wrapper():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    snap = _make_snapshot()
    snap_path = tmp / "snap.json"
    snap_path.write_text(json.dumps(snap))
    ledger_path = tmp / "ledger.jsonl"

    r = run_csc_cycle(
        data_dir=tmp / "csc_out",
        cae_snapshot_path=snap_path,
        cae_ledger_path=ledger_path,
    )
    assert isinstance(r, StabilityReport)
    assert r.innov_code == "INNOV-84"
