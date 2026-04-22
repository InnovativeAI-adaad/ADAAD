# SPDX-License-Identifier: Apache-2.0
"""Phase 32 — Governance Debt Health Signal Integration.

Test suite for the ``governance_debt_health_score`` signal wired into
``GovernanceHealthAggregator``.

Tests
-----
T32-01  No debt ledger wired → signal defaults to 1.0 (fail-safe)
T32-02  Debt ledger wired, no snapshot → signal defaults to 1.0
T32-03  compound_debt_score == 0.0 → debt_health_score == 1.0 (pristine)
T32-04  compound_debt_score == breach_threshold → debt_health_score == 0.0
T32-05  compound_debt_score == 0.5 * breach_threshold → debt_health_score == 0.5
T32-06  compound_debt_score > breach_threshold → clamped to 0.0 (over-breach)
T32-07  breach_threshold <= 0 → debt_health_score == 1.0 (misconfiguration guard)
T32-08  Collector exception → swallowed, returns 1.0, no raise
T32-09  governance_debt_health_score present in signal_breakdown dict
T32-10  SIGNAL_WEIGHTS contains governance_debt_health_score key
T32-11  SIGNAL_WEIGHTS sum == 1.0 (weight invariant preserved after Ph.32 rebalance)
T32-12  All Phase 32 weights individually in (0.0, 1.0)
T32-13  HealthSnapshot.debt_report populated when ledger is wired with snapshot
T32-14  HealthSnapshot.debt_report is None when ledger is not wired
T32-15  HealthSnapshot.debt_report contains required fields
T32-16  Determinism: identical debt state → identical governance_debt_health_score
T32-17  Debt breach (score == 0) reduces composite h below no-debt baseline
T32-18  GovernanceHealthAggregator __init__ accepts debt_ledger kwarg
T32-19  debt_report.threshold_breached matches GovernanceDebtSnapshot.threshold_breached
T32-20  Old callers (no debt_ledger) remain backward-compatible (no TypeError)
T32-21  Weight rebalance: avg_reviewer_reputation is 0.20 (was 0.22)
T32-22  Weight rebalance: amendment_gate_pass_rate is 0.18 (was 0.20)
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock

import pytest
pytestmark = pytest.mark.governance_gate

from runtime.governance.health_aggregator import (
    SIGNAL_WEIGHTS,
    GovernanceHealthAggregator,
    HealthSnapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_debt_snapshot(
    compound: float = 0.0,
    breach_threshold: float = 3.0,
    threshold_breached: bool = False,
    warning_count: int = 0,
    snapshot_hash: str = "sha256:abc123",
) -> MagicMock:
    snap = MagicMock()
    snap.compound_debt_score  = compound
    snap.breach_threshold     = breach_threshold
    snap.threshold_breached   = threshold_breached
    snap.warning_count        = warning_count
    snap.snapshot_hash        = snapshot_hash
    return snap


def _make_debt_ledger(snapshot=None) -> MagicMock:
    ledger = MagicMock()
    ledger.last_snapshot = snapshot
    return ledger


def _minimal_aggregator(**extra) -> GovernanceHealthAggregator:
    """Aggregator with all dependency signals defaulting to 1.0 fail-safe."""
    return GovernanceHealthAggregator(
        journal_emit=lambda *_: None,
        **extra,
    )


def _collect_debt(aggregator: GovernanceHealthAggregator) -> float:
    """Call the private collector directly for unit-level testing."""
    return aggregator._collect_debt_health("test-epoch")


# ---------------------------------------------------------------------------
# T32-01 — No debt ledger wired → fail-safe 1.0
# ---------------------------------------------------------------------------

def test_t32_01_no_ledger_defaults_to_1():
    agg = _minimal_aggregator()
    assert _collect_debt(agg) == 1.0


# ---------------------------------------------------------------------------
# T32-02 — Ledger wired but no snapshot yet → fail-safe 1.0
# ---------------------------------------------------------------------------

def test_t32_02_ledger_no_snapshot_defaults_to_1():
    ledger = _make_debt_ledger(snapshot=None)
    agg = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == 1.0


# ---------------------------------------------------------------------------
# T32-03 — compound == 0.0 → pristine 1.0
# ---------------------------------------------------------------------------

def test_t32_03_zero_debt_score_is_1():
    snap   = _make_debt_snapshot(compound=0.0, breach_threshold=3.0)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# T32-04 — compound == breach_threshold → fully breached 0.0
# ---------------------------------------------------------------------------

def test_t32_04_full_breach_score_is_0():
    snap   = _make_debt_snapshot(compound=3.0, breach_threshold=3.0, threshold_breached=True)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# T32-05 — compound == 0.5 * breach_threshold → 0.5
# ---------------------------------------------------------------------------

def test_t32_05_half_debt_score_is_half():
    snap   = _make_debt_snapshot(compound=1.5, breach_threshold=3.0)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# T32-06 — compound > breach_threshold → clamped to 0.0
# ---------------------------------------------------------------------------

def test_t32_06_over_breach_clamped_to_0():
    snap   = _make_debt_snapshot(compound=5.0, breach_threshold=3.0, threshold_breached=True)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# T32-07 — breach_threshold <= 0 → misconfiguration guard: 1.0
# ---------------------------------------------------------------------------

def test_t32_07_zero_breach_threshold_guard():
    snap   = _make_debt_snapshot(compound=2.0, breach_threshold=0.0)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == 1.0


def test_t32_07b_negative_breach_threshold_guard():
    snap   = _make_debt_snapshot(compound=2.0, breach_threshold=-1.0)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    assert _collect_debt(agg) == 1.0


# ---------------------------------------------------------------------------
# T32-08 — Collector exception is swallowed, returns 1.0
# ---------------------------------------------------------------------------

def test_t32_08_exception_in_ledger_is_swallowed():
    ledger = MagicMock()
    ledger.last_snapshot = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    # Use a simpler approach: raise on attribute access
    broken = MagicMock()
    type(broken).last_snapshot = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

    class BrokenLedger:
        @property
        def last_snapshot(self):
            raise RuntimeError("simulated I/O error")

    agg = _minimal_aggregator(debt_ledger=BrokenLedger())
    # Must not raise; must return fail-safe 1.0
    result = _collect_debt(agg)
    assert result == 1.0


# ---------------------------------------------------------------------------
# T32-09 — governance_debt_health_score in signal_breakdown
# ---------------------------------------------------------------------------

def test_t32_09_signal_in_breakdown():
    snap   = _make_debt_snapshot(compound=1.0, breach_threshold=3.0)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    snapshot = agg.compute("epoch-t32-09")
    assert "governance_debt_health_score" in snapshot.signal_breakdown


# ---------------------------------------------------------------------------
# T32-10 — SIGNAL_WEIGHTS has governance_debt_health_score key
# ---------------------------------------------------------------------------

def test_t32_10_signal_weights_has_debt_key():
    assert "governance_debt_health_score" in SIGNAL_WEIGHTS


# ---------------------------------------------------------------------------
# T32-11 — SIGNAL_WEIGHTS sum == 1.0
# ---------------------------------------------------------------------------

def test_t32_11_signal_weights_sum_to_1():
    total = sum(SIGNAL_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"Weight sum is {total}, expected 1.0"


# ---------------------------------------------------------------------------
# T32-12 — All weights in (0.0, 1.0)
# ---------------------------------------------------------------------------

def test_t32_12_all_weights_in_valid_range():
    for key, weight in SIGNAL_WEIGHTS.items():
        assert 0.0 < weight < 1.0, f"Weight for '{key}' out of range: {weight}"


# ---------------------------------------------------------------------------
# T32-13 — HealthSnapshot.debt_report populated when ledger is wired
# ---------------------------------------------------------------------------

def test_t32_13_debt_report_populated():
    snap   = _make_debt_snapshot(
        compound=1.2, breach_threshold=3.0, threshold_breached=False,
        warning_count=3, snapshot_hash="sha256:deadbeef"
    )
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    hs     = agg.compute("epoch-t32-13")
    assert hs.debt_report is not None
    assert hs.debt_report["available"] is True


# ---------------------------------------------------------------------------
# T32-14 — HealthSnapshot.debt_report is None when no ledger wired
# ---------------------------------------------------------------------------

def test_t32_14_debt_report_none_when_no_ledger():
    agg = _minimal_aggregator()
    hs  = agg.compute("epoch-t32-14")
    assert hs.debt_report is None


# ---------------------------------------------------------------------------
# T32-15 — debt_report contains all required fields
# ---------------------------------------------------------------------------

def test_t32_15_debt_report_required_fields():
    snap   = _make_debt_snapshot(compound=0.5, breach_threshold=3.0,
                                  threshold_breached=False, warning_count=1,
                                  snapshot_hash="sha256:t3215")
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    hs     = agg.compute("epoch-t32-15")
    report = hs.debt_report
    required = {"compound_debt_score", "breach_threshold", "threshold_breached",
                "warning_count", "snapshot_hash", "available"}
    assert required.issubset(report.keys())


# ---------------------------------------------------------------------------
# T32-16 — Determinism: identical inputs → identical score
# ---------------------------------------------------------------------------

def test_t32_16_determinism():
    def make():
        snap   = _make_debt_snapshot(compound=1.5, breach_threshold=3.0)
        ledger = _make_debt_ledger(snap)
        return _minimal_aggregator(debt_ledger=ledger)

    score_a = _collect_debt(make())
    score_b = _collect_debt(make())
    assert score_a == score_b


# ---------------------------------------------------------------------------
# T32-17 — Debt breach reduces composite h
# ---------------------------------------------------------------------------

def test_t32_17_breach_reduces_composite_h():
    # Baseline: no ledger → debt signal = 1.0
    agg_baseline = _minimal_aggregator()
    hs_baseline  = agg_baseline.compute("epoch-t32-17a")

    # Breached: compound == breach_threshold → debt signal = 0.0
    snap   = _make_debt_snapshot(compound=3.0, breach_threshold=3.0, threshold_breached=True)
    ledger = _make_debt_ledger(snap)
    agg_breached = _minimal_aggregator(debt_ledger=ledger)
    hs_breached  = agg_breached.compute("epoch-t32-17b")

    assert hs_breached.health_score < hs_baseline.health_score


# ---------------------------------------------------------------------------
# T32-18 — __init__ accepts debt_ledger kwarg without error
# ---------------------------------------------------------------------------

def test_t32_18_init_accepts_debt_ledger_kwarg():
    ledger = _make_debt_ledger()
    agg    = GovernanceHealthAggregator(
        journal_emit=lambda *_: None,
        debt_ledger=ledger,
    )
    assert agg._debt_ledger is ledger


# ---------------------------------------------------------------------------
# T32-19 — debt_report.threshold_breached mirrors snapshot
# ---------------------------------------------------------------------------

def test_t32_19_debt_report_threshold_breached_matches_snapshot():
    snap   = _make_debt_snapshot(compound=3.5, breach_threshold=3.0, threshold_breached=True)
    ledger = _make_debt_ledger(snap)
    agg    = _minimal_aggregator(debt_ledger=ledger)
    hs     = agg.compute("epoch-t32-19")
    assert hs.debt_report["threshold_breached"] is True


# ---------------------------------------------------------------------------
# T32-20 — Old callers without debt_ledger remain backward-compatible
# ---------------------------------------------------------------------------

def test_t32_20_backward_compat_no_debt_ledger():
    # Old-style construction — no debt_ledger parameter
    agg = GovernanceHealthAggregator(journal_emit=lambda *_: None)
    hs  = agg.compute("epoch-t32-20")
    # Must not raise; snapshot fields that are new should be None or valid
    assert hs.debt_report is None
    assert isinstance(hs.health_score, float)
    assert 0.0 <= hs.health_score <= 1.0


# ---------------------------------------------------------------------------
# T32-21 — avg_reviewer_reputation weight is 0.20 after rebalance
# ---------------------------------------------------------------------------

def test_t32_21_reviewer_reputation_weight_rebalanced():
    # Phase 35 further rebalanced rep from 0.19 → 0.18
    assert SIGNAL_WEIGHTS["avg_reviewer_reputation"] == pytest.approx(0.18)


# ---------------------------------------------------------------------------
# T32-22 — amendment_gate_pass_rate weight is 0.18 after rebalance
# ---------------------------------------------------------------------------

def test_t32_22_amendment_gate_weight_rebalanced():
    # Phase 35 further rebalanced amendment from 0.17 → 0.16
    assert SIGNAL_WEIGHTS["amendment_gate_pass_rate"] == pytest.approx(0.16)
