# SPDX-License-Identifier: Apache-2.0
"""Phase 35 — Gate Decision Ledger & Approval Rate Health Signal.

Tests
-----
Ledger tests (T35-L-*)
  T35-L-01  Inactive ledger (path=None) — emit() is a no-op, no file created
  T35-L-02  emit() creates file and appends JSONL record
  T35-L-03  Approved decision persists approved=True
  T35-L-04  Denied decision persists approved=False
  T35-L-05  Chain verifies after multiple emits
  T35-L-06  Chain resumes correctly on reopen
  T35-L-07  record_hash differs between approved and denied records
  T35-L-08  chain_verify_on_open raises GateDecisionChainError on tampered record
  T35-L-09  emit() I/O failure is swallowed — never raises
  T35-L-10  sequence increments monotonically
  T35-L-11  Timestamp excluded from record_hash (deterministic field hash)
  T35-L-12  Parent directory auto-created
  T35-L-13  human_override=True persisted correctly

Reader tests (T35-R-*)
  T35-R-01  approval_rate() == 1.0 on empty history
  T35-R-02  approval_rate() == 1.0 when all decisions approved
  T35-R-03  approval_rate() == 0.0 when all decisions denied
  T35-R-04  approval_rate() == 0.5 for 50/50
  T35-R-05  rejection_rate() == 1.0 - approval_rate()
  T35-R-06  history(denied_only=True) returns only denied records
  T35-R-07  decision_breakdown() counts labels correctly
  T35-R-08  failed_rules_frequency() tallies per rule
  T35-R-09  human_override_count() correct
  T35-R-10  trust_mode_breakdown() correct
  T35-R-11  verify_chain() returns True on intact chain

Signal integration tests (T35-S-*)
  T35-S-01  No reader wired → signal defaults to 1.0 (fail-safe)
  T35-S-02  Empty decision history → approval_rate == 1.0 → signal == 1.0
  T35-S-03  100% approved → signal == 1.0
  T35-S-04  100% denied → signal == 0.0
  T35-S-05  50% approved → signal == 0.5
  T35-S-06  Exception in reader is swallowed, returns 1.0
  T35-S-07  gate_approval_rate_score in signal_breakdown
  T35-S-08  SIGNAL_WEIGHTS contains gate_approval_rate_score key
  T35-S-09  SIGNAL_WEIGHTS sum == 1.0 (weight invariant preserved after Ph.35 rebalance)
  T35-S-10  All Phase 35 weights individually in (0.0, 1.0)
  T35-S-11  HealthSnapshot.gate_decision_report populated when reader is wired
  T35-S-12  HealthSnapshot.gate_decision_report is None when no reader wired
  T35-S-13  gate_decision_report contains required fields
  T35-S-14  Full denial reduces composite h below no-reader baseline
  T35-S-15  GovernanceHealthAggregator accepts gate_decision_reader kwarg
  T35-S-16  Backward compat: old callers without gate_decision_reader unchanged
  T35-S-17  Weight rebalance: avg_reviewer_reputation is 0.18 (was 0.19)
  T35-S-18  Weight rebalance: certifier_rejection_rate_score is 0.06 (was 0.07)
  T35-S-19  Determinism: identical history → identical gate_approval_rate_score
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
pytestmark = pytest.mark.governance_gate

from runtime.governance.gate_decision_ledger import (
    GATE_DECISION_LEDGER_GENESIS_PREV_HASH,
    GateDecisionChainError,
    GateDecisionLedger,
    GateDecisionReader,
)
from runtime.governance.health_aggregator import (
    SIGNAL_WEIGHTS,
    GovernanceHealthAggregator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approved_payload(
    mutation_id: str = "mut-001",
    trust_mode: str = "standard",
    gate_mode: str = "serial",
) -> dict[str, Any]:
    return {
        "approved": True,
        "decision": "pass",
        "mutation_id": mutation_id,
        "trust_mode": trust_mode,
        "reason_codes": ["all_axes_pass"],
        "failed_rules": [],
        "human_override": False,
        "gate_mode": gate_mode,
        "decision_id": f"sha256:{'a' * 64}",
    }


def _denied_payload(
    mutation_id: str = "mut-002",
    failed_rules: list[str] | None = None,
    trust_mode: str = "standard",
) -> dict[str, Any]:
    return {
        "approved": False,
        "decision": "deny",
        "mutation_id": mutation_id,
        "trust_mode": trust_mode,
        "reason_codes": ["rule_violation"],
        "failed_rules": failed_rules or ["IV.gate_forbidden_code_block"],
        "human_override": False,
        "gate_mode": "serial",
        "decision_id": f"sha256:{'b' * 64}",
    }


def _override_payload(mutation_id: str = "mut-003") -> dict[str, Any]:
    return {
        "approved": True,
        "decision": "override_pass",
        "mutation_id": mutation_id,
        "trust_mode": "elevated",
        "reason_codes": ["human_override"],
        "failed_rules": ["IV.gate_forbidden_code_block"],
        "human_override": True,
        "gate_mode": "serial",
        "decision_id": f"sha256:{'c' * 64}",
    }


def _make_reader_with_decisions(
    tmp_path: Path, payloads: list[dict]
) -> GateDecisionReader:
    path = tmp_path / "gate_decisions.jsonl"
    ledger = GateDecisionLedger(path)
    for p in payloads:
        ledger.emit(p)
    return GateDecisionReader(path)


def _minimal_agg(**extra) -> GovernanceHealthAggregator:
    return GovernanceHealthAggregator(journal_emit=lambda *_: None, **extra)


# ===========================================================================
# LEDGER TESTS
# ===========================================================================

class TestGateDecisionLedger:

    def test_t35_l_01_inactive_no_file(self, tmp_path):
        ledger = GateDecisionLedger(path=None)
        ledger.emit(_approved_payload())
        assert not (tmp_path / "gate_decisions.jsonl").exists()

    def test_t35_l_02_emit_creates_file(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        GateDecisionLedger(path).emit(_approved_payload())
        assert path.exists()
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(records) == 1

    def test_t35_l_03_approved_persisted(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        GateDecisionLedger(path).emit(_approved_payload())
        rec = json.loads(path.read_text().strip())
        assert rec["approved"] is True
        assert rec["decision"] == "pass"

    def test_t35_l_04_denied_persisted(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        GateDecisionLedger(path).emit(_denied_payload())
        rec = json.loads(path.read_text().strip())
        assert rec["approved"] is False
        assert rec["decision"] == "deny"

    def test_t35_l_05_chain_verifies_after_multiple(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        ledger = GateDecisionLedger(path)
        for p in [_approved_payload(), _denied_payload(), _approved_payload("mut-004")]:
            ledger.emit(p)
        assert ledger.verify_chain() is True

    def test_t35_l_06_chain_resumes_on_reopen(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        GateDecisionLedger(path).emit(_approved_payload())
        ledger2 = GateDecisionLedger(path)
        ledger2.emit(_denied_payload())
        assert ledger2.verify_chain() is True
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(records) == 2
        assert records[1]["sequence"] == 1

    def test_t35_l_07_record_hash_differs_approved_vs_denied(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        ledger = GateDecisionLedger(path)
        ledger.emit(_approved_payload("m1"))
        ledger.emit(_denied_payload("m2"))
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert records[0]["record_hash"] != records[1]["record_hash"]

    def test_t35_l_08_tamper_raises_chain_error(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        ledger = GateDecisionLedger(path)
        ledger.emit(_approved_payload())
        ledger.emit(_denied_payload())
        lines = path.read_text().splitlines()
        first = json.loads(lines[0])
        first["record_hash"] = "sha256:" + "f" * 64
        lines[0] = json.dumps(first)
        path.write_text("\n".join(lines) + "\n")
        with pytest.raises(GateDecisionChainError):
            GateDecisionLedger(path, chain_verify_on_open=True)

    def test_t35_l_09_emit_io_failure_swallowed(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        ledger = GateDecisionLedger(path)
        path.mkdir(exist_ok=True)
        ledger.emit(_approved_payload())  # must not raise

    def test_t35_l_10_sequence_increments(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        ledger = GateDecisionLedger(path)
        for p in [_approved_payload("a"), _denied_payload("b"), _approved_payload("c")]:
            ledger.emit(p)
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert [r["sequence"] for r in records] == [0, 1, 2]

    def test_t35_l_11_timestamp_excluded_from_record_hash(self, tmp_path):
        pa = tmp_path / "a.jsonl"
        pb = tmp_path / "b.jsonl"
        p = _approved_payload("x")
        GateDecisionLedger(pa).emit(p)
        GateDecisionLedger(pb).emit(p)
        rec_a = json.loads(pa.read_text().strip())
        rec_b = json.loads(pb.read_text().strip())
        assert rec_a["record_hash"] == rec_b["record_hash"]

    def test_t35_l_12_parent_dir_auto_created(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "gate.jsonl"
        GateDecisionLedger(path).emit(_approved_payload())
        assert path.exists()

    def test_t35_l_13_human_override_persisted(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        GateDecisionLedger(path).emit(_override_payload())
        rec = json.loads(path.read_text().strip())
        assert rec["human_override"] is True
        assert rec["decision"] == "override_pass"


# ===========================================================================
# READER TESTS
# ===========================================================================

class TestGateDecisionReader:

    def test_t35_r_01_approval_rate_empty(self, tmp_path):
        reader = GateDecisionReader(tmp_path / "none.jsonl")
        assert reader.approval_rate() == pytest.approx(1.0)

    def test_t35_r_02_approval_rate_all_approved(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload("a"), _approved_payload("b")]
        )
        assert reader.approval_rate() == pytest.approx(1.0)

    def test_t35_r_03_approval_rate_all_denied(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_denied_payload("a"), _denied_payload("b")]
        )
        assert reader.approval_rate() == pytest.approx(0.0)

    def test_t35_r_04_approval_rate_half(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload(), _denied_payload()]
        )
        assert reader.approval_rate() == pytest.approx(0.5)

    def test_t35_r_05_rejection_rate_complement(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload(), _approved_payload("x"), _denied_payload()]
        )
        assert reader.rejection_rate() == pytest.approx(1.0 - reader.approval_rate())

    def test_t35_r_06_history_denied_only(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload(), _denied_payload(), _approved_payload("y")]
        )
        denied = reader.history(denied_only=True)
        assert len(denied) == 1
        assert denied[0]["approved"] is False

    def test_t35_r_07_decision_breakdown(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload(), _denied_payload(), _override_payload()]
        )
        bd = reader.decision_breakdown()
        assert bd.get("pass") == 1
        assert bd.get("deny") == 1
        assert bd.get("override_pass") == 1

    def test_t35_r_08_failed_rules_frequency(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [
                _denied_payload(failed_rules=["R1", "R2"]),
                _denied_payload(failed_rules=["R1"]),
            ]
        )
        freq = reader.failed_rules_frequency()
        assert freq.get("R1") == 2
        assert freq.get("R2") == 1

    def test_t35_r_09_human_override_count(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload(), _override_payload(), _approved_payload("z")]
        )
        assert reader.human_override_count() == 1

    def test_t35_r_10_trust_mode_breakdown(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [
                _approved_payload(trust_mode="standard"),
                _approved_payload(trust_mode="elevated"),
                _denied_payload(trust_mode="standard"),
            ]
        )
        bd = reader.trust_mode_breakdown()
        assert bd.get("standard") == 2
        assert bd.get("elevated") == 1

    def test_t35_r_11_verify_chain_intact(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path, [_approved_payload(), _denied_payload()]
        )
        assert reader.verify_chain() is True

    def test_t35_r_12_cache_invalidates_on_file_update(self, tmp_path):
        path = tmp_path / "gate_decisions.jsonl"
        ledger = GateDecisionLedger(path)
        ledger.emit(_approved_payload("a"))
        reader = GateDecisionReader(path)
        assert reader.approval_rate() == pytest.approx(1.0)
        ledger.emit(_denied_payload("b"))
        assert reader.approval_rate() == pytest.approx(0.5)
        assert reader.rejection_rate() == pytest.approx(0.5)

    def test_t35_r_13_cached_and_uncached_consistency(self, tmp_path):
        reader = _make_reader_with_decisions(
            tmp_path,
            [
                _approved_payload("a", trust_mode="standard"),
                _denied_payload("b", failed_rules=["R1", "R2"], trust_mode="elevated"),
                _override_payload("c"),
            ],
        )
        cached = reader.common_aggregates()
        reader._cache_key = None
        reader._cached_records = None
        reader._cached_aggregates = None
        uncached = {
            "approval_rate": reader.approval_rate(),
            "rejection_rate": reader.rejection_rate(),
            "human_override_count": reader.human_override_count(),
            "decision_breakdown": reader.decision_breakdown(),
            "failed_rules_frequency": reader.failed_rules_frequency(),
            "trust_mode_breakdown": reader.trust_mode_breakdown(),
        }
        assert uncached == cached


# ===========================================================================
# SIGNAL INTEGRATION TESTS
# ===========================================================================

class TestGateApprovalRateSignal:

    def test_t35_s_01_no_reader_defaults_to_1(self):
        assert _minimal_agg()._collect_gate_approval_health() == 1.0

    def test_t35_s_02_empty_history_defaults_to_1(self, tmp_path):
        reader = GateDecisionReader(tmp_path / "empty.jsonl")
        assert _minimal_agg(gate_decision_reader=reader)._collect_gate_approval_health() == pytest.approx(1.0)

    def test_t35_s_03_all_approved_gives_1(self, tmp_path):
        reader = _make_reader_with_decisions(tmp_path, [_approved_payload(), _approved_payload("y")])
        assert _minimal_agg(gate_decision_reader=reader)._collect_gate_approval_health() == pytest.approx(1.0)

    def test_t35_s_04_all_denied_gives_0(self, tmp_path):
        reader = _make_reader_with_decisions(tmp_path, [_denied_payload(), _denied_payload("b")])
        assert _minimal_agg(gate_decision_reader=reader)._collect_gate_approval_health() == pytest.approx(0.0)

    def test_t35_s_05_half_approved_gives_half(self, tmp_path):
        reader = _make_reader_with_decisions(tmp_path, [_approved_payload(), _denied_payload()])
        assert _minimal_agg(gate_decision_reader=reader)._collect_gate_approval_health() == pytest.approx(0.5)

    def test_t35_s_06_exception_swallowed_returns_1(self):
        class BrokenReader:
            def approval_rate(self):
                raise RuntimeError("boom")

        assert _minimal_agg(gate_decision_reader=BrokenReader())._collect_gate_approval_health() == 1.0

    def test_t35_s_07_signal_in_breakdown(self, tmp_path):
        reader = _make_reader_with_decisions(tmp_path, [_approved_payload()])
        hs = _minimal_agg(gate_decision_reader=reader).compute("e-s07")
        assert "gate_approval_rate_score" in hs.signal_breakdown

    def test_t35_s_08_signal_weights_has_gate_key(self):
        assert "gate_approval_rate_score" in SIGNAL_WEIGHTS

    def test_t35_s_09_signal_weights_sum_to_1(self):
        total = sum(SIGNAL_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weight sum {total} ≠ 1.00"

    def test_t35_s_10_all_weights_in_valid_range(self):
        for key, w in SIGNAL_WEIGHTS.items():
            assert 0.0 < w < 1.0, f"Weight '{key}' out of range: {w}"

    def test_t35_s_11_gate_decision_report_populated(self, tmp_path):
        reader = _make_reader_with_decisions(tmp_path, [_approved_payload(), _denied_payload()])
        hs = _minimal_agg(gate_decision_reader=reader).compute("e-s11")
        assert hs.gate_decision_report is not None
        assert hs.gate_decision_report["available"] is True

    def test_t35_s_12_gate_decision_report_none_without_reader(self):
        hs = _minimal_agg().compute("e-s12")
        assert hs.gate_decision_report is None

    def test_t35_s_13_gate_decision_report_required_fields(self, tmp_path):
        reader = _make_reader_with_decisions(tmp_path, [_approved_payload()])
        hs = _minimal_agg(gate_decision_reader=reader).compute("e-s13")
        required = {"approval_rate", "rejection_rate", "human_override_count", "available"}
        assert required.issubset(hs.gate_decision_report.keys())

    def test_t35_s_14_full_denial_reduces_h(self, tmp_path):
        baseline = _minimal_agg().compute("b")
        reader = _make_reader_with_decisions(tmp_path, [_denied_payload(), _denied_payload("z")])
        hs = _minimal_agg(gate_decision_reader=reader).compute("d")
        assert hs.health_score < baseline.health_score

    def test_t35_s_15_init_accepts_gate_decision_reader_kwarg(self, tmp_path):
        reader = GateDecisionReader(tmp_path / "x.jsonl")
        agg = GovernanceHealthAggregator(journal_emit=lambda *_: None, gate_decision_reader=reader)
        assert agg._gate_decision_reader is reader

    def test_t35_s_16_backward_compat_no_reader(self):
        agg = GovernanceHealthAggregator(journal_emit=lambda *_: None)
        hs = agg.compute("e-bc")
        assert hs.gate_decision_report is None
        assert isinstance(hs.health_score, float)
        assert 0.0 <= hs.health_score <= 1.0

    def test_t35_s_17_reviewer_reputation_weight(self):
        assert SIGNAL_WEIGHTS["avg_reviewer_reputation"] == pytest.approx(0.18)

    def test_t35_s_18_certifier_weight_rebalanced(self):
        assert SIGNAL_WEIGHTS["certifier_rejection_rate_score"] == pytest.approx(0.06)

    def test_t35_s_19_determinism(self, tmp_path):
        def make_score():
            (tmp_path / "det.jsonl").unlink(missing_ok=True)
            reader = _make_reader_with_decisions(
                tmp_path, [_approved_payload(), _denied_payload()]
            )
            return _minimal_agg(gate_decision_reader=reader)._collect_gate_approval_health()

        assert make_score() == make_score()
