# SPDX-License-Identifier: Apache-2.0
"""Phase 33 — Certifier Scan Ledger & Rejection Rate Health Signal.

Tests
-----
Ledger tests (T33-L-*)
  T33-L-01  Inactive ledger (path=None) — emit() is a no-op, no file created
  T33-L-02  emit() creates file and appends JSONL record
  T33-L-03  CERTIFIED scan persists passed=True
  T33-L-04  REJECTED scan persists passed=False
  T33-L-05  Chain verifies after multiple emits
  T33-L-06  Chain resumes correctly on reopen
  T33-L-07  record_hash differs between CERTIFIED and REJECTED records
  T33-L-08  chain_verify_on_open raises CertifierScanChainError on tampered record
  T33-L-09  emit() I/O failure is swallowed — never raises
  T33-L-10  sequence increments monotonically
  T33-L-11  Timestamp excluded from record_hash (same hash on deterministic fields)
  T33-L-12  Parent directory auto-created

Reader tests (T33-R-*)
  T33-R-01  rejection_rate() == 0.0 on empty history
  T33-R-02  rejection_rate() == 1.0 when all scans rejected
  T33-R-03  rejection_rate() == 0.5 for 50% rejection
  T33-R-04  certification_rate() == 1.0 - rejection_rate()
  T33-R-05  history(rejected_only=True) returns only REJECTED records
  T33-R-06  mutation_blocked_count() correct
  T33-R-07  escalation_breakdown() correct
  T33-R-08  verify_chain() returns True on intact chain

Signal integration tests (T33-S-*)
  T33-S-01  No reader wired → signal defaults to 1.0 (fail-safe)
  T33-S-02  Empty scan history → rejection_rate == 0.0 → signal == 1.0
  T33-S-03  100% rejection → signal == 0.0
  T33-S-04  50% rejection → signal == 0.5
  T33-S-05  Exception in reader is swallowed, returns 1.0
  T33-S-06  certifier_rejection_rate_score in signal_breakdown
  T33-S-07  SIGNAL_WEIGHTS contains certifier_rejection_rate_score key
  T33-S-08  SIGNAL_WEIGHTS sum == 1.0 (weight invariant preserved after Ph.33 rebalance)
  T33-S-09  All Phase 33 weights individually in (0.0, 1.0)
  T33-S-10  HealthSnapshot.certifier_report populated when reader is wired
  T33-S-11  HealthSnapshot.certifier_report is None when no reader wired
  T33-S-12  certifier_report contains required fields
  T33-S-13  Determinism: identical scan history → identical certifier_rejection_rate_score
  T33-S-14  Full rejection reduces composite h below no-certifier baseline
  T33-S-15  GovernanceHealthAggregator accepts certifier_scan_reader kwarg
  T33-S-16  Backward compat: old callers without certifier_scan_reader unchanged
  T33-S-17  Weight rebalance: avg_reviewer_reputation is 0.18 (was 0.19)
  T33-S-18  Weight rebalance: governance_debt_health_score is 0.08 (was 0.09)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
pytestmark = pytest.mark.governance_gate

from runtime.governance.certifier_scan_ledger import (
    CERTIFIER_SCAN_LEDGER_GENESIS_PREV_HASH,
    CertifierScanChainError,
    CertifierScanLedger,
    CertifierScanReader,
)
from runtime.governance.health_aggregator import (
    SIGNAL_WEIGHTS,
    GovernanceHealthAggregator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _certified_scan(file_path: str = "runtime/governance/gate.py") -> dict[str, Any]:
    return {
        "status": "CERTIFIED", "passed": True, "file": file_path,
        "escalation": "advisory", "mutation_blocked": False, "fail_closed": False,
        "checks": {"import_ok": True, "token_ok": True, "ast_ok": True, "auth_ok": True},
    }


def _rejected_scan(
    file_path: str = "runtime/governance/gate.py",
    escalation: str = "critical",
    mutation_blocked: bool = True,
) -> dict[str, Any]:
    return {
        "status": "REJECTED", "passed": False, "file": file_path,
        "escalation": escalation, "mutation_blocked": mutation_blocked, "fail_closed": False,
        "checks": {"import_ok": False, "token_ok": True, "ast_ok": True, "auth_ok": False},
    }


def _make_reader_with_scans(tmp_path: Path, scans: list[dict]) -> CertifierScanReader:
    ledger_path = tmp_path / "certifier.jsonl"
    ledger = CertifierScanLedger(ledger_path)
    for scan in scans:
        ledger.emit(scan)
    return CertifierScanReader(ledger_path)


def _minimal_agg(**extra) -> GovernanceHealthAggregator:
    return GovernanceHealthAggregator(journal_emit=lambda *_: None, **extra)


# ===========================================================================
# LEDGER TESTS
# ===========================================================================

class TestCertifierScanLedger:

    def test_t33_l_01_inactive_no_file(self, tmp_path):
        ledger = CertifierScanLedger(path=None)
        ledger.emit(_certified_scan())
        assert not (tmp_path / "certifier.jsonl").exists()

    def test_t33_l_02_emit_creates_file(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        ledger.emit(_certified_scan())
        assert path.exists()
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(records) == 1

    def test_t33_l_03_certified_persists_passed_true(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        ledger.emit(_certified_scan())
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert records[0]["passed"] is True
        assert records[0]["status"] == "CERTIFIED"

    def test_t33_l_04_rejected_persists_passed_false(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        ledger.emit(_rejected_scan())
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert records[0]["passed"] is False
        assert records[0]["status"] == "REJECTED"

    def test_t33_l_05_chain_verifies_after_multiple(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        for scan in [_certified_scan(), _rejected_scan(), _certified_scan()]:
            ledger.emit(scan)
        assert ledger.verify_chain() is True

    def test_t33_l_06_chain_resumes_on_reopen(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger1 = CertifierScanLedger(path)
        ledger1.emit(_certified_scan())

        ledger2 = CertifierScanLedger(path)
        ledger2.emit(_rejected_scan())

        assert ledger2.verify_chain() is True
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(records) == 2
        assert records[1]["sequence"] == 1

    def test_t33_l_07_record_hash_differs_between_certified_rejected(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        ledger.emit(_certified_scan("a.py"))
        ledger.emit(_rejected_scan("a.py"))
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert records[0]["record_hash"] != records[1]["record_hash"]

    def test_t33_l_08_chain_verify_raises_on_tamper(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        ledger.emit(_certified_scan())
        ledger.emit(_rejected_scan())

        # Tamper: overwrite record_hash of first record
        lines = path.read_text().splitlines()
        first = json.loads(lines[0])
        first["record_hash"] = "sha256:" + "f" * 64
        lines[0] = json.dumps(first)
        path.write_text("\n".join(lines) + "\n")

        with pytest.raises(CertifierScanChainError):
            CertifierScanLedger(path, chain_verify_on_open=True)

    def test_t33_l_09_emit_io_failure_swallowed(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        # Make path a directory to force I/O error
        path.mkdir(exist_ok=True)
        # Should not raise
        ledger.emit(_certified_scan())

    def test_t33_l_10_sequence_increments(self, tmp_path):
        path = tmp_path / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        for scan in [_certified_scan(), _rejected_scan(), _certified_scan()]:
            ledger.emit(scan)
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert [r["sequence"] for r in records] == [0, 1, 2]

    def test_t33_l_11_timestamp_excluded_from_record_hash(self, tmp_path):
        """Two ledgers with same scan input produce same record_hash (timestamps differ)."""
        path_a = tmp_path / "a.jsonl"
        path_b = tmp_path / "b.jsonl"
        scan = _certified_scan()
        CertifierScanLedger(path_a).emit(scan)
        CertifierScanLedger(path_b).emit(scan)
        rec_a = json.loads(path_a.read_text().strip())
        rec_b = json.loads(path_b.read_text().strip())
        assert rec_a["record_hash"] == rec_b["record_hash"]

    def test_t33_l_12_parent_dir_auto_created(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "certifier.jsonl"
        ledger = CertifierScanLedger(path)
        ledger.emit(_certified_scan())
        assert path.exists()


# ===========================================================================
# READER TESTS
# ===========================================================================

class TestCertifierScanReader:

    def test_t33_r_01_rejection_rate_empty(self, tmp_path):
        reader = CertifierScanReader(tmp_path / "nonexistent.jsonl")
        assert reader.rejection_rate() == 0.0

    def test_t33_r_02_rejection_rate_all_rejected(self, tmp_path):
        reader = _make_reader_with_scans(tmp_path, [_rejected_scan(), _rejected_scan()])
        assert reader.rejection_rate() == pytest.approx(1.0)

    def test_t33_r_03_rejection_rate_half(self, tmp_path):
        reader = _make_reader_with_scans(
            tmp_path, [_certified_scan(), _rejected_scan()]
        )
        assert reader.rejection_rate() == pytest.approx(0.5)

    def test_t33_r_04_certification_rate_complement(self, tmp_path):
        reader = _make_reader_with_scans(
            tmp_path, [_certified_scan(), _certified_scan(), _rejected_scan()]
        )
        assert reader.certification_rate() == pytest.approx(1.0 - reader.rejection_rate())

    def test_t33_r_05_history_rejected_only(self, tmp_path):
        reader = _make_reader_with_scans(
            tmp_path, [_certified_scan(), _rejected_scan(), _certified_scan()]
        )
        rejected = reader.history(rejected_only=True)
        assert len(rejected) == 1
        assert rejected[0]["passed"] is False

    def test_t33_r_06_mutation_blocked_count(self, tmp_path):
        reader = _make_reader_with_scans(
            tmp_path, [
                _rejected_scan(mutation_blocked=True),
                _rejected_scan(mutation_blocked=False),
                _certified_scan(),
            ]
        )
        assert reader.mutation_blocked_count() == 1

    def test_t33_r_07_escalation_breakdown(self, tmp_path):
        reader = _make_reader_with_scans(
            tmp_path, [
                _certified_scan(),           # advisory
                _rejected_scan(escalation="critical"),
                _rejected_scan(escalation="critical"),
            ]
        )
        breakdown = reader.escalation_breakdown()
        assert breakdown.get("critical", 0) == 2
        assert breakdown.get("advisory", 0) == 1

    def test_t33_r_08_verify_chain_intact(self, tmp_path):
        reader = _make_reader_with_scans(
            tmp_path, [_certified_scan(), _rejected_scan()]
        )
        assert reader.verify_chain() is True


# ===========================================================================
# SIGNAL INTEGRATION TESTS
# ===========================================================================

class TestCertifierHealthSignal:

    def test_t33_s_01_no_reader_defaults_to_1(self):
        agg = _minimal_agg()
        assert agg._collect_certifier_health("test-epoch") == 1.0

    def test_t33_s_02_empty_history_defaults_to_1(self, tmp_path):
        reader = CertifierScanReader(tmp_path / "empty.jsonl")
        agg = _minimal_agg(certifier_scan_reader=reader)
        assert agg._collect_certifier_health("test-epoch") == pytest.approx(1.0)

    def test_t33_s_03_full_rejection_gives_0(self, tmp_path):
        reader = _make_reader_with_scans(tmp_path, [_rejected_scan(), _rejected_scan()])
        agg = _minimal_agg(certifier_scan_reader=reader)
        assert agg._collect_certifier_health("test-epoch") == pytest.approx(0.0)

    def test_t33_s_04_half_rejection_gives_half(self, tmp_path):
        reader = _make_reader_with_scans(tmp_path, [_certified_scan(), _rejected_scan()])
        agg = _minimal_agg(certifier_scan_reader=reader)
        assert agg._collect_certifier_health("test-epoch") == pytest.approx(0.5)

    def test_t33_s_05_exception_swallowed_returns_1(self):
        class BrokenReader:
            def rejection_rate(self):
                raise RuntimeError("boom")

        agg = _minimal_agg(certifier_scan_reader=BrokenReader())
        assert agg._collect_certifier_health("test-epoch") == 1.0

    def test_t33_s_06_signal_in_breakdown(self, tmp_path):
        reader = _make_reader_with_scans(tmp_path, [_certified_scan()])
        agg = _minimal_agg(certifier_scan_reader=reader)
        hs = agg.compute("epoch-s06")
        assert "certifier_rejection_rate_score" in hs.signal_breakdown

    def test_t33_s_07_signal_weights_has_certifier_key(self):
        assert "certifier_rejection_rate_score" in SIGNAL_WEIGHTS

    def test_t33_s_08_signal_weights_sum_to_1(self):
        total = sum(SIGNAL_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weight sum {total} ≠ 1.00"

    def test_t33_s_09_all_weights_in_valid_range(self):
        for key, w in SIGNAL_WEIGHTS.items():
            assert 0.0 < w < 1.0, f"Weight for '{key}' out of range: {w}"

    def test_t33_s_10_certifier_report_populated(self, tmp_path):
        reader = _make_reader_with_scans(tmp_path, [_certified_scan(), _rejected_scan()])
        agg = _minimal_agg(certifier_scan_reader=reader)
        hs = agg.compute("epoch-s10")
        assert hs.certifier_report is not None
        assert hs.certifier_report["available"] is True

    def test_t33_s_11_certifier_report_none_when_no_reader(self):
        agg = _minimal_agg()
        hs = agg.compute("epoch-s11")
        assert hs.certifier_report is None

    def test_t33_s_12_certifier_report_required_fields(self, tmp_path):
        reader = _make_reader_with_scans(tmp_path, [_certified_scan()])
        agg = _minimal_agg(certifier_scan_reader=reader)
        hs = agg.compute("epoch-s12")
        required = {"rejection_rate", "certification_rate", "mutation_blocked_count", "available"}
        assert required.issubset(hs.certifier_report.keys())

    def test_t33_s_13_determinism(self, tmp_path):
        def make():
            reader = _make_reader_with_scans(
                tmp_path / "det", [_certified_scan(), _rejected_scan()]
            )
            return _minimal_agg(certifier_scan_reader=reader)

        # Clear between runs
        (tmp_path / "det").mkdir(exist_ok=True)
        (tmp_path / "det" / "certifier.jsonl").unlink(missing_ok=True)
        score_a = make()._collect_certifier_health("test-epoch")
        (tmp_path / "det" / "certifier.jsonl").unlink(missing_ok=True)
        score_b = make()._collect_certifier_health("test-epoch")
        assert score_a == score_b

    def test_t33_s_14_full_rejection_reduces_h(self, tmp_path):
        # Baseline: no reader → certifier signal = 1.0
        hs_baseline = _minimal_agg().compute("b")

        # Full rejection
        reader = _make_reader_with_scans(tmp_path, [_rejected_scan(), _rejected_scan()])
        hs_rejected = _minimal_agg(certifier_scan_reader=reader).compute("r")

        assert hs_rejected.health_score < hs_baseline.health_score

    def test_t33_s_15_init_accepts_certifier_reader_kwarg(self, tmp_path):
        reader = CertifierScanReader(tmp_path / "x.jsonl")
        agg = GovernanceHealthAggregator(
            journal_emit=lambda *_: None,
            certifier_scan_reader=reader,
        )
        assert agg._certifier_reader is reader

    def test_t33_s_16_backward_compat_no_reader(self):
        agg = GovernanceHealthAggregator(journal_emit=lambda *_: None)
        hs = agg.compute("epoch-bc")
        assert hs.certifier_report is None
        assert isinstance(hs.health_score, float)
        assert 0.0 <= hs.health_score <= 1.0

    def test_t33_s_17_reviewer_reputation_weight(self):
        assert SIGNAL_WEIGHTS["avg_reviewer_reputation"] == pytest.approx(0.18)

    def test_t33_s_18_debt_health_weight(self):
        assert SIGNAL_WEIGHTS["governance_debt_health_score"] == pytest.approx(0.08)
