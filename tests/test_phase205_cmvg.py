# SPDX-License-Identifier: Apache-2.0
"""Phase 205 · INNOV-110 · CMVG — Constitutional Mutation Velocity Governor
Acceptance Test Suite — 30 tests (T205-CMVG-01 … T205-CMVG-30)

Tests verify all 10 hard-class invariants:
  CMVG-CHAIN-0, CMVG-IMMUT-0, CMVG-HUMAN0-0, CMVG-CGDR-0,
  CMVG-DETERM-0, CMVG-AUDIT-0, CMVG-FLOOR-0, CMVG-CEIL-0,
  CMVG-FAILCLOSED-0, CMVG-SEAL-0
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dorkllm.constitutional_mutation_velocity_governor import (
    CMVG_CEIL,
    CMVG_FLOOR,
    CMVGAuthError,
    CMVGChainError,
    CMVGError,
    CMVGImmutError,
    ConstitutionalMutationVelocityGovernor,
    DecisionOutcome,
    VelocityDecision,
    VelocityLedger,
    VelocityMode,
    VelocitySignals,
)

pytestmark = pytest.mark.phase205


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gov(tmp_path: Path) -> ConstitutionalMutationVelocityGovernor:
    ledger = VelocityLedger(path=tmp_path / "test_cmvg.jsonl")
    return ConstitutionalMutationVelocityGovernor(ledger=ledger)


def _passing_signals(**kwargs) -> VelocitySignals:
    defaults = dict(
        cgdr_status="PASSING",
        invariant_density=0.8,
        cel_gate_pass_rate=0.9,
        innovation_backlog=2,
        last_phase_duration_s=1800.0,
    )
    defaults.update(kwargs)
    return VelocitySignals(**defaults)


# ---------------------------------------------------------------------------
# T205-CMVG-01 … T205-CMVG-03  Basic decision lifecycle
# ---------------------------------------------------------------------------


def test_T205_CMVG_01_decide_returns_decision(tmp_path):
    """T205-CMVG-01: decide() returns a VelocityDecision."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals())
    assert isinstance(decision, VelocityDecision)


def test_T205_CMVG_02_outcome_decided(tmp_path):
    """T205-CMVG-02: normal signals produce DECIDED outcome."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals())
    assert decision.outcome == DecisionOutcome.DECIDED.value


def test_T205_CMVG_03_mode_set(tmp_path):
    """T205-CMVG-03: velocity_mode is set to a valid VelocityMode."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals())
    assert decision.velocity_mode in [m.value for m in VelocityMode]


# ---------------------------------------------------------------------------
# T205-CMVG-04 … T205-CMVG-07  CMVG-CGDR-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_04_cgdr_drifted_halts(tmp_path):
    """T205-CMVG-04: CMVG-CGDR-0 — DRIFTED status → rate 0.0."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(cgdr_status="DRIFTED"))
    assert decision.admission_rate == 0.0


def test_T205_CMVG_05_cgdr_drifted_mode_halt(tmp_path):
    """T205-CMVG-05: CMVG-CGDR-0 — DRIFTED status → HALT mode."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(cgdr_status="DRIFTED"))
    assert decision.velocity_mode == VelocityMode.HALT.value


def test_T205_CMVG_06_cgdr_drifted_outcome(tmp_path):
    """T205-CMVG-06: CMVG-CGDR-0 — DRIFTED → HALT_CGDR outcome."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(cgdr_status="DRIFTED"))
    assert decision.outcome == DecisionOutcome.HALT_CGDR.value


def test_T205_CMVG_07_cgdr_passing_not_halted(tmp_path):
    """T205-CMVG-07: CMVG-CGDR-0 — PASSING → rate > 0.0."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(cgdr_status="PASSING"))
    assert decision.admission_rate > 0.0


# ---------------------------------------------------------------------------
# T205-CMVG-08 … T205-CMVG-10  CMVG-FLOOR-0 / CMVG-CEIL-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_08_floor_respected(tmp_path):
    """T205-CMVG-08: CMVG-FLOOR-0 — rate never below CMVG_FLOOR."""
    gov = _gov(tmp_path)
    # Very low signals
    decision = gov.decide(_passing_signals(
        cel_gate_pass_rate=0.0,
        invariant_density=0.0,
        innovation_backlog=20,
    ))
    assert decision.admission_rate >= CMVG_FLOOR


def test_T205_CMVG_09_ceil_respected(tmp_path):
    """T205-CMVG-09: CMVG-CEIL-0 — rate never above CMVG_CEIL."""
    gov = _gov(tmp_path)
    # Very high signals
    decision = gov.decide(_passing_signals(
        cel_gate_pass_rate=1.0,
        invariant_density=1.0,
        innovation_backlog=0,
    ))
    assert decision.admission_rate <= CMVG_CEIL


def test_T205_CMVG_10_rate_range(tmp_path):
    """T205-CMVG-10: rate in [FLOOR, CEIL] for any normal signals."""
    gov = _gov(tmp_path)
    for density in [0.1, 0.5, 0.9]:
        for cel in [0.2, 0.7, 1.0]:
            d = gov.decide(_passing_signals(
                invariant_density=density,
                cel_gate_pass_rate=cel,
            ))
            assert CMVG_FLOOR <= d.admission_rate <= CMVG_CEIL


# ---------------------------------------------------------------------------
# T205-CMVG-11 … T205-CMVG-13  CMVG-DETERM-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_11_deterministic_id(tmp_path):
    """T205-CMVG-11: CMVG-DETERM-0 — same signals → same decision_id."""
    gov1 = _gov(tmp_path / "a")
    gov2 = _gov(tmp_path / "b")
    sigs = _passing_signals()
    d1 = gov1.decide(sigs)
    d2 = gov2.decide(sigs)
    assert d1.decision_id == d2.decision_id


def test_T205_CMVG_12_deterministic_rate(tmp_path):
    """T205-CMVG-12: CMVG-DETERM-0 — same signals → same rate."""
    gov1 = _gov(tmp_path / "c")
    gov2 = _gov(tmp_path / "d")
    sigs = _passing_signals()
    assert gov1.decide(sigs).admission_rate == gov2.decide(sigs).admission_rate


def test_T205_CMVG_13_different_signals_different_id(tmp_path):
    """T205-CMVG-13: CMVG-DETERM-0 — different signals → different id."""
    gov = _gov(tmp_path)
    d1 = gov.decide(_passing_signals(cel_gate_pass_rate=0.3))
    d2 = gov.decide(_passing_signals(cel_gate_pass_rate=0.9))
    assert d1.decision_id != d2.decision_id


# ---------------------------------------------------------------------------
# T205-CMVG-14 … T205-CMVG-16  CMVG-AUDIT-0 / CMVG-CHAIN-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_14_decision_ledgered(tmp_path):
    """T205-CMVG-14: CMVG-AUDIT-0 — decide() appends to ledger."""
    gov = _gov(tmp_path)
    gov.decide(_passing_signals())
    records = gov.all_decisions()
    assert len(records) == 1


def test_T205_CMVG_15_multiple_decisions_ledgered(tmp_path):
    """T205-CMVG-15: CMVG-AUDIT-0 — each decide() appends one record."""
    gov = _gov(tmp_path)
    for _ in range(5):
        gov.decide(_passing_signals())
    assert len(gov.all_decisions()) == 5


def test_T205_CMVG_16_chain_valid(tmp_path):
    """T205-CMVG-16: CMVG-CHAIN-0 — chain passes verification after N decisions."""
    gov = _gov(tmp_path)
    for _ in range(4):
        gov.decide(_passing_signals())
    result = gov.verify_chain()
    assert result["valid"] is True
    assert result["entries"] == 4


# ---------------------------------------------------------------------------
# T205-CMVG-17 … T205-CMVG-18  CMVG-SEAL-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_17_seal_present(tmp_path):
    """T205-CMVG-17: CMVG-SEAL-0 — content_seal is non-empty hex string."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals())
    assert len(decision.content_seal) == 64
    assert all(c in "0123456789abcdef" for c in decision.content_seal)


def test_T205_CMVG_18_seal_in_ledger(tmp_path):
    """T205-CMVG-18: CMVG-SEAL-0 — ledger record carries content_seal."""
    gov = _gov(tmp_path)
    gov.decide(_passing_signals())
    record = gov.all_decisions()[0]
    assert record["content_seal"] and len(record["content_seal"]) == 64


# ---------------------------------------------------------------------------
# T205-CMVG-19  CMVG-IMMUT-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_19_immut_double_seal(tmp_path):
    """T205-CMVG-19: CMVG-IMMUT-0 — sealing an already-sealed record raises."""
    decision = VelocityDecision(
        decision_id="TEST-01",
        admission_rate=0.7,
        velocity_mode=VelocityMode.CRUISE.value,
        outcome=DecisionOutcome.DECIDED.value,
        signals_snapshot={},
        rationale="test",
    )
    decision.seal("canonical")
    with pytest.raises(CMVGImmutError):
        decision.seal("canonical2")


# ---------------------------------------------------------------------------
# T205-CMVG-20 … T205-CMVG-24  CMVG-HUMAN0-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_20_emergency_stop_requires_human_id(tmp_path):
    """T205-CMVG-20: CMVG-HUMAN0-0 — empty human_id raises CMVGAuthError."""
    gov = _gov(tmp_path)
    with pytest.raises(CMVGAuthError):
        gov.emergency_stop("")


def test_T205_CMVG_21_emergency_stop_halts(tmp_path):
    """T205-CMVG-21: CMVG-HUMAN0-0 — emergency_stop → rate 0.0."""
    gov = _gov(tmp_path)
    gov.emergency_stop("DUSTIN L REID")
    decision = gov.decide(_passing_signals())
    assert decision.admission_rate == 0.0
    assert decision.outcome == DecisionOutcome.HALT_EMERGENCY.value


def test_T205_CMVG_22_clear_emergency_stop(tmp_path):
    """T205-CMVG-22: CMVG-HUMAN0-0 — clear_emergency_stop restores normal."""
    gov = _gov(tmp_path)
    gov.emergency_stop("DUSTIN L REID")
    gov.clear_emergency_stop("DUSTIN L REID")
    decision = gov.decide(_passing_signals())
    assert decision.outcome == DecisionOutcome.DECIDED.value


def test_T205_CMVG_23_set_policy_rate(tmp_path):
    """T205-CMVG-23: CMVG-HUMAN0-0 — set_policy_rate returns override."""
    gov = _gov(tmp_path)
    gov.set_policy_rate(0.42, "DUSTIN L REID")
    decision = gov.decide(_passing_signals())
    assert decision.outcome == DecisionOutcome.POLICY_OVERRIDE.value
    assert decision.admission_rate == pytest.approx(0.42)


def test_T205_CMVG_24_policy_rate_auth_required(tmp_path):
    """T205-CMVG-24: CMVG-HUMAN0-0 — set_policy_rate without human_id raises."""
    gov = _gov(tmp_path)
    with pytest.raises(CMVGAuthError):
        gov.set_policy_rate(0.5, "")


# ---------------------------------------------------------------------------
# T205-CMVG-25  CMVG-FAILCLOSED-0
# ---------------------------------------------------------------------------


def test_T205_CMVG_25_failclosed_on_ledger_error(tmp_path, monkeypatch):
    """T205-CMVG-25: CMVG-FAILCLOSED-0 — ledger failure → CMVGError raised."""
    gov = _gov(tmp_path)

    def _bad_append(_dec):
        raise RuntimeError("simulated ledger failure")

    monkeypatch.setattr(gov._ledger, "append", _bad_append)
    with pytest.raises(CMVGError):
        gov.decide(_passing_signals())


# ---------------------------------------------------------------------------
# T205-CMVG-26 … T205-CMVG-28  Mode thresholds
# ---------------------------------------------------------------------------


def test_T205_CMVG_26_throttle_mode(tmp_path):
    """T205-CMVG-26: low signals → THROTTLE mode."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(
        cel_gate_pass_rate=0.2,
        invariant_density=0.2,
        innovation_backlog=8,
    ))
    assert decision.velocity_mode == VelocityMode.THROTTLE.value


def test_T205_CMVG_27_cruise_mode(tmp_path):
    """T205-CMVG-27: moderate signals → CRUISE mode."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(
        cel_gate_pass_rate=0.75,
        invariant_density=0.65,
        innovation_backlog=3,
    ))
    assert decision.velocity_mode == VelocityMode.CRUISE.value


def test_T205_CMVG_28_accelerate_mode(tmp_path):
    """T205-CMVG-28: high signals → ACCELERATE mode."""
    gov = _gov(tmp_path)
    decision = gov.decide(_passing_signals(
        cel_gate_pass_rate=1.0,
        invariant_density=1.0,
        innovation_backlog=0,
    ))
    assert decision.velocity_mode == VelocityMode.ACCELERATE.value


# ---------------------------------------------------------------------------
# T205-CMVG-29 … T205-CMVG-30  Status & chain integrity
# ---------------------------------------------------------------------------


def test_T205_CMVG_29_status_shape(tmp_path):
    """T205-CMVG-29: status() returns expected keys."""
    gov = _gov(tmp_path)
    s = gov.status()
    assert "innov_id" in s
    assert "emergency_stop" in s
    assert "policy_rate" in s


def test_T205_CMVG_30_chain_invalid_on_tamper(tmp_path):
    """T205-CMVG-30: CMVG-CHAIN-0 — tampered ledger raises CMVGChainError."""
    gov = _gov(tmp_path)
    gov.decide(_passing_signals())
    gov.decide(_passing_signals())
    # Tamper with ledger
    ledger_path = gov._ledger._path
    lines = ledger_path.read_text().splitlines()
    record = json.loads(lines[0])
    record["admission_rate"] = 9.99  # tamper
    lines[0] = json.dumps(record)
    ledger_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(CMVGChainError):
        gov.verify_chain()
