# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase184_cca.py
Phase 184 · INNOV-89 · CCA — Convergence Certification Auditor
30-test suite · v9.117.0 · Governor: DUSTIN L REID
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

# ── Test markers ───────────────────────────────────────────────────────────────
pytestmark = pytest.mark.phase185


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_data(tmp_path: Path, monkeypatch) -> Generator[Path, None, None]:
    """Redirect all CCA data paths to a temporary directory."""
    import dorkllm.convergence_certification_auditor as mod

    data_dir = tmp_path / "data" / "cca"
    data_dir.mkdir(parents=True)

    monkeypatch.setattr(mod, "_DATA_DIR", data_dir)
    monkeypatch.setattr(mod, "_CERT_LEDGER_PATH", data_dir / "certification_ledger.jsonl")
    monkeypatch.setattr(mod, "_CCA_SNAPSHOT_PATH", data_dir / "cca_snapshot.json")
    monkeypatch.setattr(mod, "_ADVISORY_LOG_PATH", data_dir / "human0_advisory_log.jsonl")
    monkeypatch.setattr(mod, "_GAP_REPORT_PATH", data_dir / "gap_reports.jsonl")
    monkeypatch.setattr(mod, "_TELEMETRY_PATH", data_dir / "outcome_telemetry.jsonl")

    # Redirect upstream paths to non-existent (tests inject via monkeypatch)
    monkeypatch.setattr(mod, "_GIR_SNAPSHOT_PATH", tmp_path / "gir_snapshot.json")
    monkeypatch.setattr(mod, "_CGR_LEDGER_PATH", tmp_path / "grp_ledger.jsonl")
    monkeypatch.setattr(mod, "_CPE_LEDGER_PATH", tmp_path / "execution_ledger.jsonl")
    monkeypatch.setattr(mod, "_CPE_SNAPSHOT_PATH", tmp_path / "cpe_snapshot.json")
    monkeypatch.setattr(mod, "_AGENT_STATE_PATH", tmp_path / "agent_state.json")

    yield tmp_path


def _write_passing_evidence(tmp_path: Path) -> None:
    """Write upstream files that satisfy all V10 criteria."""
    import json

    # GIR
    (tmp_path / "gir_snapshot.json").write_text(
        json.dumps({"readiness_score": 0.95}), encoding="utf-8"
    )
    # CGR — empty ledger means 0 open gaps
    (tmp_path / "grp_ledger.jsonl").write_text("", encoding="utf-8")
    # CPE — all successes
    cpe_records = [{"status": "SUCCESS"}] * 10
    (tmp_path / "execution_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in cpe_records), encoding="utf-8"
    )
    # Agent state — satisfies C4/C5/C6/C7/C8
    agent = {
        "hard_class_invariants": 476,
        "cel_loop_status": "FULLY CLOSED",
        "innovations_shipped": 88,
        "phases_complete": 183,
        "schema_version": "1.5.0",
    }
    (tmp_path / "agent_state.json").write_text(json.dumps(agent), encoding="utf-8")


def _write_failing_evidence(tmp_path: Path) -> None:
    """Write upstream files that fail multiple V10 criteria."""
    import json

    (tmp_path / "gir_snapshot.json").write_text(
        json.dumps({"readiness_score": 0.50}), encoding="utf-8"
    )
    grp_records = [{"status": "OPEN"}] * 5
    (tmp_path / "grp_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in grp_records), encoding="utf-8"
    )
    cpe_records = [{"status": "FAILED"}] * 5
    (tmp_path / "execution_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in cpe_records), encoding="utf-8"
    )
    agent = {
        "hard_class_invariants": 100,
        "cel_loop_status": "OPEN",
        "innovations_shipped": 30,
        "phases_complete": 50,
        "schema_version": "",
    }
    (tmp_path / "agent_state.json").write_text(json.dumps(agent), encoding="utf-8")


# ── Group 1: Module structure ──────────────────────────────────────────────────

def test_cca_t184_01_module_importable():
    """T184-CCA-01: Module imports without error."""
    import dorkllm.convergence_certification_auditor as mod
    assert hasattr(mod, "ConvergenceCertificationAuditor")


def test_cca_t184_02_criteria_count():
    """T184-CCA-02: Exactly 8 V10 criteria defined."""
    from dorkllm.convergence_certification_auditor import _V10_CRITERIA
    assert len(_V10_CRITERIA) == 8


def test_cca_t184_03_criteria_weights_sum():
    """T184-CCA-03: Criteria weights sum to 1.0."""
    from dorkllm.convergence_certification_auditor import _V10_CRITERIA
    total = sum(c.weight for c in _V10_CRITERIA)
    assert abs(total - 1.0) < 1e-9


def test_cca_t184_04_criteria_immutable():
    """T184-CCA-04: CCA-CRITERIA-0 — criteria tuple is frozen (frozenset semantics)."""
    from dorkllm.convergence_certification_auditor import _V10_CRITERIA, V10Criterion
    with pytest.raises((TypeError, AttributeError)):
        _V10_CRITERIA[0].weight = 0.99  # type: ignore[misc]


def test_cca_t184_05_threshold_value():
    """T184-CCA-05: CCA_THRESHOLD == 0.875."""
    from dorkllm.convergence_certification_auditor import CCA_THRESHOLD
    assert CCA_THRESHOLD == 0.875


# ── Group 2: Engine init / snapshot ───────────────────────────────────────────

def test_cca_t184_06_engine_instantiates(tmp_data):
    """T184-CCA-06: Engine instantiates and loads empty state."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    eng = ConvergenceCertificationAuditor()
    status = eng.get_status()
    assert status["total_audits"] == 0


def test_cca_t184_07_snapshot_roundtrip(tmp_data):
    """T184-CCA-07: CCA-PERSIST-0 — snapshot survives re-instantiation."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor, _CCA_SNAPSHOT_PATH
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    eng.audit()
    status_before = eng.get_status()

    eng2 = ConvergenceCertificationAuditor()
    status_after = eng2.get_status()
    assert status_after["total_audits"] == status_before["total_audits"]


# ── Group 3: Evidence gathering ────────────────────────────────────────────────

def test_cca_t184_08_gather_no_upstream(tmp_data):
    """T184-CCA-08: Evidence gathering succeeds with missing upstream files."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    assert ev.gir_readiness_score == 0.0


def test_cca_t184_09_gir_score_read(tmp_data):
    """T184-CCA-09: GIR readiness score parsed from snapshot."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor, _GIR_SNAPSHOT_PATH
    _GIR_SNAPSHOT_PATH.write_text(json.dumps({"readiness_score": 0.92}), encoding="utf-8")
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    assert ev.gir_readiness_score == 0.92


def test_cca_t184_10_cgr_gap_count(tmp_data):
    """T184-CCA-10: Open CGR gaps counted correctly."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor, _CGR_LEDGER_PATH
    records = [{"status": "OPEN"}, {"status": "RESOLVED"}, {"status": "OPEN"}]
    _CGR_LEDGER_PATH.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    assert ev.cgr_open_gap_count == 2


def test_cca_t184_11_cpe_success_rate(tmp_data):
    """T184-CCA-11: CPE success rate computed from ledger."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor, _CPE_LEDGER_PATH
    records = [{"status": "SUCCESS"}] * 9 + [{"status": "FAILED"}]
    _CPE_LEDGER_PATH.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    assert ev.cpe_success_rate == pytest.approx(0.90, abs=1e-4)


def test_cca_t184_12_no_cpe_records_trivially_satisfied(tmp_data):
    """T184-CCA-12: Zero CPE executions → success_rate == 1.0 (trivially satisfied)."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    assert ev.cpe_success_rate == 1.0


# ── Group 4: Criteria scoring ──────────────────────────────────────────────────

def test_cca_t184_13_all_criteria_pass(tmp_data):
    """T184-CCA-13: All 8 criteria pass with ideal evidence."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    results, score = eng._score_criteria(ev)
    assert all(r.passed for r in results)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_cca_t184_14_all_criteria_fail(tmp_data):
    """T184-CCA-14: All 8 criteria fail with worst-case evidence."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_failing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    results, score = eng._score_criteria(ev)
    assert all(not r.passed for r in results)
    assert score == pytest.approx(0.0, abs=1e-6)


def test_cca_t184_15_score_contribution_zero_on_fail(tmp_data):
    """T184-CCA-15: Failed criteria contribute 0.0 to score."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_failing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    ev = eng._gather_evidence()
    results, _ = eng._score_criteria(ev)
    for r in results:
        assert r.score_contribution == 0.0


# ── Group 5: Certificate issuance ─────────────────────────────────────────────

def test_cca_t184_16_v10_certificate_issued_on_full_pass(tmp_data):
    """T184-CCA-16: V10 Certificate issued when score ≥ threshold."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor, _RECORD_CERTIFICATE
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    cert = eng.audit()
    assert cert.v10_ready is True
    assert cert.record_type == _RECORD_CERTIFICATE


def test_cca_t184_17_audit_record_on_fail(tmp_data):
    """T184-CCA-17: CONVERGENCE_AUDIT record type when score < threshold."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor, _RECORD_AUDIT
    _write_failing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    cert = eng.audit()
    assert cert.v10_ready is False
    assert cert.record_type == _RECORD_AUDIT


def test_cca_t184_18_human0_advisory_on_v10(tmp_data):
    """T184-CCA-18: CCA-HUMAN0-0 — advisory emitted for V10 certificate."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _ADVISORY_LOG_PATH
    )
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    cert = eng.audit()
    assert cert.human0_advisory_emitted is True
    assert _ADVISORY_LOG_PATH.exists()
    entries = [json.loads(l) for l in _ADVISORY_LOG_PATH.read_text().splitlines() if l.strip()]
    assert len(entries) >= 1
    assert entries[0]["advisory_type"] == "V10_GRADUATION_READY"


def test_cca_t184_19_no_advisory_on_fail(tmp_data):
    """T184-CCA-19: No HUMAN-0 advisory when V10 not ready."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _ADVISORY_LOG_PATH
    )
    _write_failing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    cert = eng.audit()
    assert cert.human0_advisory_emitted is False
    assert not _ADVISORY_LOG_PATH.exists()


# ── Group 6: Ledger / chain invariants ────────────────────────────────────────

def test_cca_t184_20_ledger_written_before_return(tmp_data):
    """T184-CCA-20: CCA-AUDIT-0 — ledger entry written on every audit()."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _CERT_LEDGER_PATH
    )
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    eng.audit()
    assert _CERT_LEDGER_PATH.exists()
    lines = [l for l in _CERT_LEDGER_PATH.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


def test_cca_t184_21_ledger_appends_multiple(tmp_data):
    """T184-CCA-21: CCA-IMMUT-0 — ledger grows on each audit."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _CERT_LEDGER_PATH
    )
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    for _ in range(3):
        eng.audit()
    lines = [l for l in _CERT_LEDGER_PATH.read_text().splitlines() if l.strip()]
    assert len(lines) == 3


def test_cca_t184_22_chain_valid_after_audits(tmp_data):
    """T184-CCA-22: CCA-CHAIN-0 — chain valid after multiple audits."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    for _ in range(5):
        eng.audit()
    valid, count, err = eng.verify_chain()
    assert valid is True
    assert count == 5
    assert err is None


def test_cca_t184_23_chain_detects_tamper(tmp_data):
    """T184-CCA-23: CCA-CHAIN-0 — tampered ledger detected."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _CERT_LEDGER_PATH
    )
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    eng.audit()

    # Tamper the ledger
    raw = _CERT_LEDGER_PATH.read_text()
    record = json.loads(raw.strip())
    record["hmac_digest"] = "deadbeef" * 8
    _CERT_LEDGER_PATH.write_text(json.dumps(record) + "\n", encoding="utf-8")

    valid, count, err = eng.verify_chain()
    assert valid is False
    assert err is not None


# ── Group 7: Idempotency / deduplication ──────────────────────────────────────

def test_cca_t184_24_duplicate_audit_id_rejected(tmp_data):
    """T184-CCA-24: CCA-IDEMPOTENT-0 — duplicate audit_id raises ValueError."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    fixed_id = "audit-fixed-001"
    eng.audit(audit_id=fixed_id)
    with pytest.raises(ValueError, match="DUPLICATE_AUDIT"):
        eng.audit(audit_id=fixed_id)


def test_cca_t184_25_unique_audit_ids_accepted(tmp_data):
    """T184-CCA-25: Unique audit IDs all accepted without error."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    for i in range(5):
        eng.audit(audit_id=f"unique-{i}")
    assert eng.get_status()["total_audits"] == 5


# ── Group 8: Preview / status / integration ────────────────────────────────────

def test_cca_t184_26_preview_does_not_write_ledger(tmp_data):
    """T184-CCA-26: preview_criteria() does not write to certification ledger."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _CERT_LEDGER_PATH
    )
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    preview = eng.preview_criteria()
    assert preview["preview"] is True
    assert not _CERT_LEDGER_PATH.exists()


def test_cca_t184_27_preview_score_matches_audit(tmp_data):
    """T184-CCA-27: Preview score matches subsequent audit score."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    preview = eng.preview_criteria()
    cert = eng.audit()
    assert preview["convergence_score"] == pytest.approx(cert.convergence_score, abs=1e-6)


def test_cca_t184_28_remediation_gaps_on_fail(tmp_data):
    """T184-CCA-28: Failed criteria appear in remediation_gaps list."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    _write_failing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    cert = eng.audit()
    assert len(cert.remediation_gaps) > 0
    assert any("C1" in g for g in cert.remediation_gaps)


def test_cca_t184_29_telemetry_written(tmp_data):
    """T184-CCA-29: Outcome telemetry written for CAL after each audit."""
    from dorkllm.convergence_certification_auditor import (
        ConvergenceCertificationAuditor, _TELEMETRY_PATH
    )
    _write_passing_evidence(tmp_data)
    eng = ConvergenceCertificationAuditor()
    eng.audit()
    assert _TELEMETRY_PATH.exists()
    entries = [json.loads(l) for l in _TELEMETRY_PATH.read_text().splitlines() if l.strip()]
    assert entries[0]["event"] == "cca_audit_complete"


def test_cca_t184_30_governor_string_in_status(tmp_data):
    """T184-CCA-30: Governor string 'DUSTIN L REID' present in status."""
    from dorkllm.convergence_certification_auditor import ConvergenceCertificationAuditor
    eng = ConvergenceCertificationAuditor()
    status = eng.get_status()
    assert status["governor"] == "DUSTIN L REID"
