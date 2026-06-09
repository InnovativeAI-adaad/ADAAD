# SPDX-License-Identifier: Apache-2.0
# Phase 218 · INNOV-123 · ACAM — Autonomous Constitutional Amendment Monitor
# 30-test acceptance suite · T218-ACAM-01..30
# Governor: DUSTIN L REID · Agent: DEVADAAD · InnovativeAI LLC

"""
Acceptance tests for ACAM (Autonomous Constitutional Amendment Monitor).
All 30 tests must pass (30/30) before phase promotion.

Test categories:
  INIT  — Module import and singleton instantiation (01-03)
  SCAN  — scan() full pipeline (04-09)
  STALE — Stale proposal detection ACAM-STALE-0 (10-13)
  CONF  — Conflict detection ACAM-CONFLICT-0 (14-17)
  COV   — Coverage report ACAM-COVERAGE-0 (18-21)
  CHAIN — HMAC chain ACAM-CHAIN-0 / ACAM-INTEGRITY-0 (22-25)
  HUMAN0— ACAM-HUMAN0-0 gate (26-27)
  SCOPE — ACAM-SCOPE-0 read-only enforcement (28)
  STATUS— status() health check (29)
  ATOMIC— ACAM-ATOMIC-0 ledger write (30)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root on path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dorkllm.autonomous_constitutional_amendment_monitor as acam_mod
from dorkllm.autonomous_constitutional_amendment_monitor import (
    AutonomousConstitutionalAmendmentMonitor,
    AmendmentRecord,
    AmendmentState,
    MonitorRecord,
    MonitorEventType,
    AlertSeverity,
    CoverageReport,
    ACAMError,
    ACAMHuman0Error,
    ACAMIntegrityError,
    ACAMScopeError,
    ACAMStaleError,
    ACAMAtomicError,
    ACAM_CHAIN_0,
    ACAM_HUMAN0_0,
    ACAM_IMMUT_0,
    ACAM_SCOPE_0,
    ACAM_INTEGRITY_0,
    ACAM_STALE_0,
    ACAM_CONFLICT_0,
    ACAM_COVERAGE_0,
    ACAM_ATOMIC_0,
    ACAM_ALERT_0,
    GOVERNOR,
    scan,
    verify_chain,
    coverage_report,
    status,
    update_config,
    _verify_chain_integrity,
    _compute_coverage,
    _detect_conflicts,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Redirect all ledger paths to a tmp directory for each test."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    monkeypatch.setattr(acam_mod, "_LEDGER_PATH", ledger_dir / "acam_monitor_ledger.jsonl")
    monkeypatch.setattr(acam_mod, "_ACSA_LEDGER", ledger_dir / "acsa_amendments_ledger.jsonl")
    monkeypatch.setattr(acam_mod, "_ACPA_LEDGER", ledger_dir / "acpa_proposals_ledger.jsonl")
    monkeypatch.setattr(acam_mod, "_STALE_THRESHOLD_HOURS", 72.0)
    yield


def _make_amendment_record(
    amendment_id: str = "A-001",
    section: str = "SEC-1",
    state: AmendmentState = AmendmentState.PROPOSED,
    age_hours: float = 0,
) -> AmendmentRecord:
    now = time.time_ns()
    created = now - int(age_hours * 3_600_000_000_000)
    return AmendmentRecord(
        amendment_id=amendment_id,
        section=section,
        state=state,
        created_at_ns=created,
        updated_at_ns=now,
        proposed_by="TEST",
        source="TEST",
    )


def _write_acsa_ledger(records: List[Dict], ledger_path: Path) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# T218-ACAM-01  INIT — Module imports without error
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_01_module_imports():
    """T218-ACAM-01: module imports cleanly."""
    import dorkllm.autonomous_constitutional_amendment_monitor as m
    assert m is not None


# ---------------------------------------------------------------------------
# T218-ACAM-02  INIT — Singleton instantiates
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_02_singleton_instantiates():
    """T218-ACAM-02: AutonomousConstitutionalAmendmentMonitor instantiates."""
    engine = AutonomousConstitutionalAmendmentMonitor()
    assert engine is not None


# ---------------------------------------------------------------------------
# T218-ACAM-03  INIT — All 10 invariant IDs are defined
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_03_invariant_ids_defined():
    """T218-ACAM-03: all 10 Hard-class invariant IDs are defined."""
    invariants = [
        ACAM_CHAIN_0, ACAM_HUMAN0_0, ACAM_IMMUT_0, ACAM_SCOPE_0,
        ACAM_INTEGRITY_0, ACAM_STALE_0, ACAM_CONFLICT_0,
        ACAM_COVERAGE_0, ACAM_ATOMIC_0, ACAM_ALERT_0,
    ]
    assert len(invariants) == 10
    for inv in invariants:
        assert inv.startswith("ACAM-")


# ---------------------------------------------------------------------------
# T218-ACAM-04  SCAN — scan() returns ok=True on empty ledgers
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_04_scan_empty_ledgers():
    """T218-ACAM-04: scan() succeeds with empty ACSA/ACPA ledgers."""
    result = scan()
    assert result["ok"] is True
    assert "scan_id" in result
    assert result["total_amendments"] == 0


# ---------------------------------------------------------------------------
# T218-ACAM-05  SCAN — scan() returns expected keys
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_05_scan_keys_present():
    """T218-ACAM-05: scan() result contains all required keys."""
    result = scan()
    required = [
        "ok", "scan_id", "total_amendments", "stale_count",
        "conflict_count", "coverage_score", "coverage", "alerts",
        "critical_alert_count", "invariants_enforced",
    ]
    for key in required:
        assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# T218-ACAM-06  SCAN — scan() appends to monitor ledger
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_06_scan_appends_ledger():
    """T218-ACAM-06: scan() appends a record to the monitor ledger."""
    ledger = acam_mod._LEDGER_PATH
    assert not ledger.exists() or ledger.stat().st_size == 0
    scan()
    assert ledger.exists()
    lines = [l for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# T218-ACAM-07  SCAN — scan() reads ACSA ledger data
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_07_scan_reads_acsa():
    """T218-ACAM-07: scan() correctly counts amendments from ACSA ledger."""
    _write_acsa_ledger(
        [{"amendment_id": "A1", "section": "SEC-1", "state": "PROPOSED",
          "created_at_ns": time.time_ns(), "updated_at_ns": time.time_ns()}],
        acam_mod._ACSA_LEDGER,
    )
    result = scan()
    assert result["acsa_count"] >= 1
    assert result["total_amendments"] >= 1


# ---------------------------------------------------------------------------
# T218-ACAM-08  SCAN — scan() reports coverage_score in [0, 1]
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_08_scan_coverage_score_range():
    """T218-ACAM-08: coverage_score is always between 0.0 and 1.0."""
    result = scan()
    assert 0.0 <= result["coverage_score"] <= 1.0


# ---------------------------------------------------------------------------
# T218-ACAM-09  SCAN — singleton.scan() mirrors module scan()
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_09_singleton_scan_mirrors_module():
    """T218-ACAM-09: engine.scan() returns the same structure as scan()."""
    engine = AutonomousConstitutionalAmendmentMonitor()
    result = engine.scan()
    assert result["ok"] is True
    assert "scan_id" in result


# ---------------------------------------------------------------------------
# T218-ACAM-10  STALE — ACAM-STALE-0: fresh proposals not flagged
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_10_fresh_proposal_not_stale():
    """T218-ACAM-10: PROPOSED amendment under threshold is not stale."""
    a = _make_amendment_record(age_hours=10.0)
    assert not a.is_stale(threshold_hours=72.0)


# ---------------------------------------------------------------------------
# T218-ACAM-11  STALE — ACAM-STALE-0: old proposals flagged
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_11_old_proposal_stale():
    """T218-ACAM-11: PROPOSED amendment over threshold is stale."""
    a = _make_amendment_record(age_hours=100.0)
    assert a.is_stale(threshold_hours=72.0)


# ---------------------------------------------------------------------------
# T218-ACAM-12  STALE — ACAM-STALE-0: RATIFIED proposals never stale
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_12_ratified_never_stale():
    """T218-ACAM-12: RATIFIED amendments are never considered stale."""
    a = _make_amendment_record(state=AmendmentState.RATIFIED, age_hours=9999)
    assert not a.is_stale(threshold_hours=72.0)


# ---------------------------------------------------------------------------
# T218-ACAM-13  STALE — scan() stale count reflects actual stale records
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_13_scan_stale_count_accurate():
    """T218-ACAM-13: scan() stale_count matches amendments over threshold."""
    old_ts = time.time_ns() - int(100 * 3_600_000_000_000)
    _write_acsa_ledger(
        [
            {"amendment_id": "A1", "section": "SEC-1", "state": "PROPOSED",
             "created_at_ns": old_ts, "updated_at_ns": old_ts},
            {"amendment_id": "A2", "section": "SEC-2", "state": "RATIFIED",
             "created_at_ns": old_ts, "updated_at_ns": old_ts},
        ],
        acam_mod._ACSA_LEDGER,
    )
    result = scan()
    assert result["stale_count"] == 1


# ---------------------------------------------------------------------------
# T218-ACAM-14  CONFLICT — ACAM-CONFLICT-0: no conflict on distinct sections
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_14_no_conflict_distinct_sections():
    """T218-ACAM-14: distinct sections produce no conflicts."""
    amendments = [
        _make_amendment_record("A1", "SEC-1", AmendmentState.PROPOSED),
        _make_amendment_record("A2", "SEC-2", AmendmentState.PROPOSED),
    ]
    conflicts = _detect_conflicts(amendments)
    assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# T218-ACAM-15  CONFLICT — ACAM-CONFLICT-0: same section flagged
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_15_conflict_same_section():
    """T218-ACAM-15: two PROPOSED amendments on same section → conflict."""
    amendments = [
        _make_amendment_record("A1", "SEC-1", AmendmentState.PROPOSED),
        _make_amendment_record("A2", "SEC-1", AmendmentState.PROPOSED),
    ]
    conflicts = _detect_conflicts(amendments)
    assert len(conflicts) == 1
    assert conflicts[0].section == "SEC-1"


# ---------------------------------------------------------------------------
# T218-ACAM-16  CONFLICT — ACAM-CONFLICT-0: dual RATIFIED is CRITICAL
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_16_dual_ratified_critical():
    """T218-ACAM-16: two RATIFIED amendments on same section → CRITICAL severity."""
    amendments = [
        _make_amendment_record("A1", "SEC-X", AmendmentState.RATIFIED),
        _make_amendment_record("A2", "SEC-X", AmendmentState.RATIFIED),
    ]
    conflicts = _detect_conflicts(amendments)
    assert len(conflicts) == 1
    assert conflicts[0].severity == AlertSeverity.CRITICAL


# ---------------------------------------------------------------------------
# T218-ACAM-17  CONFLICT — scan() conflict_count reflects detected conflicts
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_17_scan_conflict_count():
    """T218-ACAM-17: scan() conflict_count matches _detect_conflicts count."""
    _write_acsa_ledger(
        [
            {"amendment_id": "A1", "section": "SEC-1", "state": "PROPOSED",
             "created_at_ns": time.time_ns(), "updated_at_ns": time.time_ns()},
            {"amendment_id": "A2", "section": "SEC-1", "state": "PROPOSED",
             "created_at_ns": time.time_ns(), "updated_at_ns": time.time_ns()},
        ],
        acam_mod._ACSA_LEDGER,
    )
    result = scan()
    assert result["conflict_count"] == 1


# ---------------------------------------------------------------------------
# T218-ACAM-18  COV — ACAM-COVERAGE-0: coverage_report() ok=True
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_18_coverage_report_ok():
    """T218-ACAM-18: coverage_report() returns ok=True."""
    result = coverage_report()
    assert result["ok"] is True
    assert "coverage" in result


# ---------------------------------------------------------------------------
# T218-ACAM-19  COV — ACAM-COVERAGE-0: 100% coverage on all-ratified
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_19_full_coverage_all_ratified():
    """T218-ACAM-19: 100% coverage when every section has a RATIFIED amendment."""
    amendments = [
        _make_amendment_record("A1", "SEC-1", AmendmentState.RATIFIED),
        _make_amendment_record("A2", "SEC-2", AmendmentState.RATIFIED),
    ]
    report = _compute_coverage(amendments)
    assert report.coverage_score == 1.0


# ---------------------------------------------------------------------------
# T218-ACAM-20  COV — ACAM-COVERAGE-0: 0% coverage on all-proposed
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_20_zero_coverage_all_proposed():
    """T218-ACAM-20: 0.0 coverage_score when no amendments are RATIFIED."""
    amendments = [
        _make_amendment_record("A1", "SEC-1", AmendmentState.PROPOSED),
        _make_amendment_record("A2", "SEC-2", AmendmentState.PROPOSED),
    ]
    report = _compute_coverage(amendments)
    assert report.coverage_score == 0.0


# ---------------------------------------------------------------------------
# T218-ACAM-21  COV — ACAM-COVERAGE-0: coverage_report appends ledger
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_21_coverage_appends_ledger():
    """T218-ACAM-21: coverage_report() appends a record to monitor ledger."""
    coverage_report()
    ledger = acam_mod._LEDGER_PATH
    assert ledger.exists()
    lines = [l for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1


# ---------------------------------------------------------------------------
# T218-ACAM-22  CHAIN — ACAM-CHAIN-0: sealed record has hmac_digest
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_22_sealed_record_has_hmac():
    """T218-ACAM-22: sealed MonitorRecord has non-empty hmac_digest."""
    record = MonitorRecord(
        record_id="TEST-001",
        event_type=MonitorEventType.SCAN,
        timestamp_ns=time.time_ns(),
        payload={"test": True},
        alerts=[],
        prev_digest="GENESIS",
    ).seal()
    assert len(record.hmac_digest) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# T218-ACAM-23  CHAIN — ACAM-CHAIN-0: second record chains to first
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_23_chain_linkage():
    """T218-ACAM-23: second scan prev_digest equals first scan hmac_digest."""
    scan()
    scan()
    ledger = acam_mod._LEDGER_PATH
    lines = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[1]["prev_digest"] == lines[0]["hmac_digest"]


# ---------------------------------------------------------------------------
# T218-ACAM-24  CHAIN — ACAM-INTEGRITY-0: verify_chain() succeeds on valid chain
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_24_verify_chain_valid():
    """T218-ACAM-24: verify_chain() returns chain_valid=True on a correct chain."""
    scan()
    scan()
    result = verify_chain()
    assert result["ok"] is True
    assert result["chain_valid"] is True


# ---------------------------------------------------------------------------
# T218-ACAM-25  CHAIN — ACAM-INTEGRITY-0: tampered ledger raises ACAMIntegrityError
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_25_tampered_chain_raises():
    """T218-ACAM-25: tampered ledger record triggers ACAMIntegrityError."""
    scan()
    ledger = acam_mod._LEDGER_PATH
    content = ledger.read_text()
    # Corrupt the first HMAC digest
    lines = content.splitlines()
    rec = json.loads(lines[0])
    rec["hmac_digest"] = "0" * 64
    lines[0] = json.dumps(rec)
    ledger.write_text("\n".join(lines) + "\n")

    with pytest.raises(ACAMIntegrityError):
        verify_chain()


# ---------------------------------------------------------------------------
# T218-ACAM-26  HUMAN0 — ACAM-HUMAN0-0: update_config without auth raises
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_26_update_config_requires_human0():
    """T218-ACAM-26: update_config without human0_authorized=True raises ACAMHuman0Error."""
    with pytest.raises(ACAMHuman0Error) as exc_info:
        update_config(new_stale_threshold_hours=48.0, human0_authorized=False)
    assert ACAM_HUMAN0_0 in str(exc_info.value)


# ---------------------------------------------------------------------------
# T218-ACAM-27  HUMAN0 — ACAM-HUMAN0-0: authorized config update succeeds
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_27_update_config_authorized_succeeds():
    """T218-ACAM-27: update_config with human0_authorized=True succeeds."""
    result = update_config(new_stale_threshold_hours=48.0, human0_authorized=True)
    assert result["ok"] is True
    assert "stale_threshold_hours" in result["changes"]
    assert result["changes"]["stale_threshold_hours"]["new"] == 48.0


# ---------------------------------------------------------------------------
# T218-ACAM-28  SCOPE — ACAM-SCOPE-0: no write functions on constitution paths
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_28_scope_read_only():
    """T218-ACAM-28: ACAM module exposes no constitution/proposal write APIs."""
    import dorkllm.autonomous_constitutional_amendment_monitor as m
    # Must NOT have write-to-constitution or write-to-proposal functions
    forbidden = ["write_constitution", "mutate_constitution",
                 "write_proposal", "submit_proposal", "ratify_amendment"]
    for name in forbidden:
        assert not hasattr(m, name), f"Forbidden write function exposed: {name}"


# ---------------------------------------------------------------------------
# T218-ACAM-29  STATUS — status() returns all required fields
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_29_status_fields():
    """T218-ACAM-29: status() contains module, version, governor, invariants."""
    result = status()
    assert result["ok"] is True
    assert result["module"] == "ACAM"
    assert result["governor"] == GOVERNOR
    assert len(result["invariants"]) == 10
    assert result["version"] == "10.29.0"


# ---------------------------------------------------------------------------
# T218-ACAM-30  ATOMIC — ACAM-ATOMIC-0: ledger content is valid JSONL after scan
# ---------------------------------------------------------------------------
@pytest.mark.phase218
@pytest.mark.acam
def test_T218_ACAM_30_atomic_write_produces_valid_jsonl():
    """T218-ACAM-30: monitor ledger is valid JSONL after multiple scan() calls."""
    for _ in range(3):
        scan()
    ledger = acam_mod._LEDGER_PATH
    lines = [l.strip() for l in ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    for line in lines:
        obj = json.loads(line)
        assert "record_id" in obj
        assert "hmac_digest" in obj
        assert len(obj["hmac_digest"]) == 64
