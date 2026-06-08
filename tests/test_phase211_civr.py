# SPDX-License-Identifier: Apache-2.0
"""30-test acceptance suite — INNOV-116 · CIVR · Phase 211.

Test codes: T211-CIVR-01 … T211-CIVR-30
Covers: construction, severity validation, violation_id determinism, context
bounding, HMAC sealing, HUMAN-0 escalation, chain append, waiver flow,
verify_chain, history, fail-closed behaviour, status, and API router.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Ensure project root on path ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

import dorkllm.constitutional_invariant_violation_reporter as _mod
from dorkllm.constitutional_invariant_violation_reporter import (
    ConstitutionalInvariantViolationReporter,
    EscalationStatus,
    ViolationSeverity,
    _make_violation_id,
    _record_hmac,
    _validate_context,
)


# ── Fixture: isolated ledger per test ────────────────────────────────────────

@pytest.fixture(autouse=True)
def tmp_ledger(tmp_path, monkeypatch):
    ledger_dir = tmp_path / "civr"
    ledger_file = ledger_dir / "violation_ledger.jsonl"
    monkeypatch.setattr(_mod, "_LEDGER_DIR", ledger_dir)
    monkeypatch.setattr(_mod, "_LEDGER_FILE", ledger_file)
    yield ledger_file


@pytest.fixture
def reporter():
    return ConstitutionalInvariantViolationReporter(phase=211)


# ── T211-CIVR-01: construction with valid args ──────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_01_construction(reporter):
    assert reporter._phase == 211
    assert reporter._adaad_version == "10.22.0"
    assert reporter._governor == "DUSTIN L REID"


# ── T211-CIVR-02: invalid phase raises ──────────────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_02_invalid_phase():
    with pytest.raises(ValueError, match="CIVR-FAILCLOSED-0"):
        ConstitutionalInvariantViolationReporter(phase=0)


# ── T211-CIVR-03: invalid version raises ────────────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_03_invalid_version():
    with pytest.raises(ValueError, match="CIVR-FAILCLOSED-0"):
        ConstitutionalInvariantViolationReporter(phase=211, adaad_version="  ")


# ── T211-CIVR-04: report returns dict with required keys ────────────────────
@pytest.mark.civr
def test_T211_CIVR_04_report_keys(reporter):
    rec = reporter.report("TEST-INV-0", "LOW", "test violation")
    required = {
        "violation_id", "invariant_code", "severity", "phase",
        "detected_at", "description", "hmac_digest", "prev_digest",
        "human0_required", "escalation_status", "governor",
    }
    assert required.issubset(rec.keys())


# ── T211-CIVR-05: LOW severity → human0_required=False ──────────────────────
@pytest.mark.civr
def test_T211_CIVR_05_low_severity_no_human0(reporter):
    rec = reporter.report("X-0", "LOW", "desc")
    assert rec["human0_required"] is False
    assert rec["human0_signal"] is None
    assert rec["escalation_status"] == EscalationStatus.PENDING.value


# ── T211-CIVR-06: CRITICAL severity → human0_required=True ──────────────────
@pytest.mark.civr
def test_T211_CIVR_06_critical_sets_human0(reporter):
    rec = reporter.report("X-0", "CRITICAL", "critical breach")
    assert rec["human0_required"] is True
    assert rec["human0_signal"] == "HUMAN0_REQUIRED"
    assert rec["escalation_status"] == EscalationStatus.ESCALATED.value


# ── T211-CIVR-07: CIVR-SEVERITY-0 rejects unknown severity ──────────────────
@pytest.mark.civr
def test_T211_CIVR_07_unknown_severity_rejected(reporter):
    with pytest.raises(ValueError, match="CIVR-SEVERITY-0"):
        reporter.report("X-0", "EXTREME", "bad severity")


# ── T211-CIVR-08: HIGH severity mapped correctly ────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_08_high_severity(reporter):
    rec = reporter.report("X-0", "HIGH", "high breach")
    assert rec["severity"] == "HIGH"
    assert rec["human0_required"] is False


# ── T211-CIVR-09: MEDIUM severity mapped correctly ──────────────────────────
@pytest.mark.civr
def test_T211_CIVR_09_medium_severity(reporter):
    rec = reporter.report("X-0", "MEDIUM", "medium issue")
    assert rec["severity"] == "MEDIUM"


# ── T211-CIVR-10: ViolationSeverity enum accepted ───────────────────────────
@pytest.mark.civr
def test_T211_CIVR_10_enum_severity(reporter):
    rec = reporter.report("X-0", ViolationSeverity.HIGH, "enum severity")
    assert rec["severity"] == "HIGH"


# ── T211-CIVR-11: CIVR-DETERM-0 — same inputs → same violation_id ───────────
@pytest.mark.civr
def test_T211_CIVR_11_deterministic_id():
    vid1 = _make_violation_id("INV-0", 123456789, {"k": "v"})
    vid2 = _make_violation_id("INV-0", 123456789, {"k": "v"})
    assert vid1 == vid2
    assert len(vid1) == 64  # SHA-256 hex


# ── T211-CIVR-12: different inputs → different violation_id ─────────────────
@pytest.mark.civr
def test_T211_CIVR_12_different_inputs_different_id():
    vid1 = _make_violation_id("INV-0", 1, {})
    vid2 = _make_violation_id("INV-1", 1, {})
    assert vid1 != vid2


# ── T211-CIVR-13: CIVR-CONTEXT-0 — oversized context raises ─────────────────
@pytest.mark.civr
def test_T211_CIVR_13_oversized_context(reporter):
    big_context = {"key": "x" * 3000}
    with pytest.raises(ValueError, match="CIVR-CONTEXT-0"):
        reporter.report("X-0", "LOW", "desc", context=big_context)


# ── T211-CIVR-14: context sanitises non-string keys ─────────────────────────
@pytest.mark.civr
def test_T211_CIVR_14_context_sanitised(reporter):
    rec = reporter.report("X-0", "LOW", "desc", context={"k": "v", 99: "ignored"})
    assert 99 not in rec["context"]
    assert rec["context"].get("k") == "v"


# ── T211-CIVR-15: context complex values are stringified ────────────────────
@pytest.mark.civr
def test_T211_CIVR_15_context_complex_stringified(reporter):
    rec = reporter.report("X-0", "LOW", "desc", context={"obj": [1, 2, 3]})
    assert isinstance(rec["context"]["obj"], str)


# ── T211-CIVR-16: CIVR-CHAIN-0 — second record prev_digest links to first ───
@pytest.mark.civr
def test_T211_CIVR_16_chain_links(reporter):
    r1 = reporter.report("A-0", "LOW", "first")
    r2 = reporter.report("B-0", "LOW", "second")
    assert r2["prev_digest"] == r1["hmac_digest"]


# ── T211-CIVR-17: CIVR-CHAIN-0 — first record has GENESIS prev_digest ────────
@pytest.mark.civr
def test_T211_CIVR_17_genesis_prev(reporter):
    r1 = reporter.report("A-0", "LOW", "first")
    assert r1["prev_digest"] == "GENESIS"


# ── T211-CIVR-18: CIVR-SEAL-0 — hmac_digest is deterministic ────────────────
@pytest.mark.civr
def test_T211_CIVR_18_hmac_deterministic():
    d1 = _record_hmac("INV-0", "LOW", 211, "2026-01-01T00:00:00+00:00", "desc")
    d2 = _record_hmac("INV-0", "LOW", 211, "2026-01-01T00:00:00+00:00", "desc")
    assert d1 == d2
    assert len(d1) == 64


# ── T211-CIVR-19: CIVR-AUDIT-0 — report writes to ledger file ───────────────
@pytest.mark.civr
def test_T211_CIVR_19_ledger_written(reporter, tmp_ledger):
    reporter.report("X-0", "LOW", "desc")
    assert tmp_ledger.exists()
    lines = [l for l in tmp_ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


# ── T211-CIVR-20: multiple reports append correctly ─────────────────────────
@pytest.mark.civr
def test_T211_CIVR_20_multiple_appends(reporter, tmp_ledger):
    for i in range(5):
        reporter.report(f"X-{i}", "LOW", f"desc {i}")
    lines = [l for l in tmp_ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 5


# ── T211-CIVR-21: verify_chain passes on empty ledger ───────────────────────
@pytest.mark.civr
def test_T211_CIVR_21_verify_empty(reporter):
    result = reporter.verify_chain()
    assert result["ok"] is True
    assert result["entry_count"] == 0


# ── T211-CIVR-22: verify_chain passes on valid chain ────────────────────────
@pytest.mark.civr
def test_T211_CIVR_22_verify_valid_chain(reporter):
    for i in range(3):
        reporter.report(f"X-{i}", "LOW", f"desc {i}")
    result = reporter.verify_chain()
    assert result["ok"] is True
    assert result["entry_count"] == 3


# ── T211-CIVR-23: verify_chain detects tampered prev_digest ─────────────────
@pytest.mark.civr
def test_T211_CIVR_23_verify_detects_tamper(reporter, tmp_ledger):
    reporter.report("A-0", "LOW", "first")
    reporter.report("B-0", "LOW", "second")
    lines = tmp_ledger.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["prev_digest"] = "tampered000"
    lines[1] = json.dumps(entry)
    tmp_ledger.write_text("\n".join(lines) + "\n")
    result = reporter.verify_chain()
    assert result["ok"] is False
    assert result["first_break_index"] == 1


# ── T211-CIVR-24: waive records waiver in ledger ────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_24_waive_records(reporter, tmp_ledger):
    rec = reporter.report("X-0", "LOW", "desc")
    waiver = reporter.waive(rec["violation_id"], "test waiver reason")
    assert waiver["event_type"] == "WAIVER"
    assert waiver["violation_id"] == rec["violation_id"]
    lines = [l for l in tmp_ledger.read_text().splitlines() if l.strip()]
    assert len(lines) == 2


# ── T211-CIVR-25: waive missing args raises ──────────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_25_waive_missing_args(reporter):
    with pytest.raises(ValueError, match="CIVR-FAILCLOSED-0"):
        reporter.waive("", "reason")


# ── T211-CIVR-26: history returns entries most-recent first ─────────────────
@pytest.mark.civr
def test_T211_CIVR_26_history_order(reporter):
    for i in range(3):
        reporter.report(f"X-{i}", "LOW", f"desc {i}")
    hist = reporter.history(limit=3)
    assert hist[0]["invariant_code"] == "X-2"
    assert hist[2]["invariant_code"] == "X-0"


# ── T211-CIVR-27: history limit is respected ────────────────────────────────
@pytest.mark.civr
def test_T211_CIVR_27_history_limit(reporter):
    for i in range(10):
        reporter.report(f"X-{i}", "LOW", f"desc {i}")
    hist = reporter.history(limit=3)
    assert len(hist) == 3


# ── T211-CIVR-28: status returns correct module info ────────────────────────
@pytest.mark.civr
def test_T211_CIVR_28_status(reporter):
    s = reporter.status()
    assert s["module"] == "CIVR"
    assert s["innov"] == "INNOV-116"
    assert s["phase"] == 211
    assert len(s["hard_invariants"]) == 10
    assert "CIVR-HUMAN0-0" in s["hard_invariants"]


# ── T211-CIVR-29: CIVR-FAILCLOSED-0 — empty invariant_code raises ───────────
@pytest.mark.civr
def test_T211_CIVR_29_empty_invariant_code(reporter):
    with pytest.raises(ValueError, match="CIVR-FAILCLOSED-0"):
        reporter.report("", "LOW", "desc")


# ── T211-CIVR-30: remediation_hint propagates to record ─────────────────────
@pytest.mark.civr
def test_T211_CIVR_30_remediation_hint(reporter):
    rec = reporter.report(
        "X-0", "HIGH", "desc",
        remediation_hint="Check module initialisation order and invariant wiring."
    )
    assert rec["remediation_hint"] == "Check module initialisation order and invariant wiring."
