# SPDX-License-Identifier: Apache-2.0
"""Phase 208 · INNOV-113 · CMOA — Constitutional Mutation Outcome Analyst
30-test acceptance suite (T208-CMOA-01 … T208-CMOA-30).

All 30 tests must pass before Phase 208 is promoted.
Governor: DUSTIN L REID · InnovativeAI LLC
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_records(n: int, outcome: str = "SUCCESS", blast_tier: int = 1, fitness: float = 0.85) -> List[dict]:
    return [
        {
            "window_id": f"WIN-{i:03d}",
            "proposal_id": f"PROP-{i:03d}",
            "blast_tier": blast_tier,
            "constitutional_fitness": fitness,
            "outcome": outcome,
        }
        for i in range(n)
    ]


def _mixed_records() -> List[dict]:
    """5 SUCCESS, 3 FAILED, 1 TIMEOUT, 1 REJECTED = 10 total."""
    recs = _make_records(5, "SUCCESS", blast_tier=1, fitness=0.85)
    recs += _make_records(3, "FAILED", blast_tier=2, fitness=0.45)
    recs += _make_records(1, "TIMEOUT", blast_tier=0, fitness=0.60)
    recs += _make_records(1, "REJECTED", blast_tier=1, fitness=0.70)
    return recs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def healthy_cmoa(tmp_path: Path):
    from dorkllm.constitutional_mutation_outcome_analyst import (
        ConstitutionalMutationOutcomeAnalyst,
    )
    return ConstitutionalMutationOutcomeAnalyst(
        ledger_path=tmp_path / "cmoa_ledger.jsonl",
        cgdr_status_override="HEALTHY",
    )


@pytest.fixture()
def drifted_cmoa(tmp_path: Path):
    from dorkllm.constitutional_mutation_outcome_analyst import (
        ConstitutionalMutationOutcomeAnalyst,
    )
    return ConstitutionalMutationOutcomeAnalyst(
        ledger_path=tmp_path / "cmoa_ledger.jsonl",
        cgdr_status_override="DRIFTED",
    )


@pytest.fixture()
def alert_cmoa(tmp_path: Path):
    from dorkllm.constitutional_mutation_outcome_analyst import (
        ConstitutionalMutationOutcomeAnalyst,
    )
    return ConstitutionalMutationOutcomeAnalyst(
        ledger_path=tmp_path / "cmoa_ledger.jsonl",
        cgdr_status_override="DRIFT_ALERT",
    )


# ===========================================================================
# T208-CMOA-01: analyse returns SIGNALS_EMITTED with ≥3 success records
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_01_signals_emitted_on_healthy(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(5, "SUCCESS"))
    assert result["outcome"] == "SIGNALS_EMITTED"


# ===========================================================================
# T208-CMOA-02: fitness_signal present and bounded (CMOA-BIAS-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_02_fitness_signal_bounded(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(5, "SUCCESS"))
    sig = result.get("fitness_signal", {})
    assert sig.get("type") == "FITNESS_ADJUST"
    delta = sig.get("delta", 999)
    assert -0.20 <= delta <= 0.20, f"CMOA-BIAS-0: delta {delta} out of bounds"


# ===========================================================================
# T208-CMOA-03: velocity_signal present with valid nudge value
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_03_velocity_signal_present(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_mixed_records())
    sig = result.get("velocity_signal", {})
    assert sig.get("type") == "VELOCITY_NUDGE"
    assert sig.get("nudge") in ("ACCELERATE", "CRUISE", "THROTTLE", "HALT")


# ===========================================================================
# T208-CMOA-04: NO_SIGNAL returned when sample < 3 (CMOA-MIN-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_04_no_signal_below_min_sample(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(2, "SUCCESS"))
    assert result["outcome"] == "NO_SIGNAL"


# ===========================================================================
# T208-CMOA-05: exactly 3 records is accepted (boundary)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_05_min_sample_boundary(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(3, "SUCCESS"))
    assert result["outcome"] == "SIGNALS_EMITTED"


# ===========================================================================
# T208-CMOA-06: CGDR DRIFTED blocks signal emission (CMOA-CGDR-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_06_cgdr_drifted_blocks(drifted_cmoa):
    from dorkllm.constitutional_mutation_outcome_analyst import CMOACGDRGateError
    with pytest.raises(CMOACGDRGateError):
        drifted_cmoa.analyse(inject_records=_make_records(5, "SUCCESS"))


# ===========================================================================
# T208-CMOA-07: DRIFT_ALERT still allows analysis
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_07_drift_alert_allowed(alert_cmoa):
    result = alert_cmoa.analyse(inject_records=_make_records(5, "SUCCESS"))
    assert result["outcome"] == "SIGNALS_EMITTED"


# ===========================================================================
# T208-CMOA-08: ledger chain valid after analysis (CMOA-CHAIN-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_08_ledger_chain_valid(healthy_cmoa):
    healthy_cmoa.analyse(inject_records=_make_records(4, "SUCCESS"))
    chain = healthy_cmoa.verify_chain()
    assert chain["valid"] is True


# ===========================================================================
# T208-CMOA-09: every record has content_seal (CMOA-SEAL-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_09_content_seal_present(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(4, "SUCCESS"))
    assert "content_seal" in result
    assert len(result["content_seal"]) == 64


# ===========================================================================
# T208-CMOA-10: NO_SIGNAL record also has content_seal
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_10_no_signal_has_seal(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(1, "SUCCESS"))
    assert result["outcome"] == "NO_SIGNAL"
    assert len(result.get("content_seal", "")) == 64


# ===========================================================================
# T208-CMOA-11: record_id is deterministic-format (CMOA-DETERM-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_11_record_id_format(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(4, "SUCCESS"))
    rid = result.get("record_id", "")
    assert rid.startswith("CMOA-"), "CMOA-DETERM-0: ID must start with CMOA-"
    assert len(rid) == 5 + 14, "CMOA-DETERM-0: suffix must be 14 chars"


# ===========================================================================
# T208-CMOA-12: 100% success → ACCELERATE velocity nudge
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_12_all_success_accelerates(healthy_cmoa):
    result = healthy_cmoa.analyse(inject_records=_make_records(5, "SUCCESS"))
    assert result["velocity_signal"]["nudge"] == "ACCELERATE"


# ===========================================================================
# T208-CMOA-13: majority FAILED → THROTTLE velocity nudge
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_13_majority_failed_throttles(healthy_cmoa):
    recs = _make_records(3, "FAILED") + _make_records(1, "SUCCESS")
    result = healthy_cmoa.analyse(inject_records=recs)
    assert result["velocity_signal"]["nudge"] == "THROTTLE"


# ===========================================================================
# T208-CMOA-14: high timeout rate → HALT velocity nudge
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_14_high_timeout_halts(healthy_cmoa):
    recs = _make_records(4, "TIMEOUT") + _make_records(3, "SUCCESS")
    result = healthy_cmoa.analyse(inject_records=recs)
    assert result["velocity_signal"]["nudge"] == "HALT"


# ===========================================================================
# T208-CMOA-15: mixed outcomes → CRUISE velocity nudge
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_15_mixed_cruises(healthy_cmoa):
    recs = _make_records(4, "SUCCESS") + _make_records(3, "FAILED")
    result = healthy_cmoa.analyse(inject_records=recs)
    # 4/7 ≈ 57% success — not ≥80% → CRUISE
    assert result["velocity_signal"]["nudge"] == "CRUISE"


# ===========================================================================
# T208-CMOA-16: statistics block has correct total
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_16_stats_total_correct(healthy_cmoa):
    recs = _make_records(7, "SUCCESS")
    result = healthy_cmoa.analyse(inject_records=recs)
    assert result["statistics"]["total"] == 7


# ===========================================================================
# T208-CMOA-17: statistics tracks successes, failures, timeouts, rejections
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_17_stats_counts(healthy_cmoa):
    recs = _mixed_records()  # 5S 3F 1T 1R
    result = healthy_cmoa.analyse(inject_records=recs)
    stats = result["statistics"]
    assert stats["successes"] == 5
    assert stats["failures"] == 3
    assert stats["timeouts"] == 1
    assert stats["rejections"] == 1


# ===========================================================================
# T208-CMOA-18: global_success_rate computed correctly
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_18_success_rate(healthy_cmoa):
    recs = _make_records(4, "SUCCESS") + _make_records(1, "FAILED")
    result = healthy_cmoa.analyse(inject_records=recs)
    rate = result["statistics"]["global_success_rate"]
    assert abs(rate - 0.80) < 0.01


# ===========================================================================
# T208-CMOA-19: fitness delta positive for high success rate
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_19_positive_delta_for_high_success(healthy_cmoa):
    recs = _make_records(10, "SUCCESS")
    result = healthy_cmoa.analyse(inject_records=recs)
    delta = result["fitness_signal"]["delta"]
    assert delta > 0.0, "High success rate must yield positive fitness delta"


# ===========================================================================
# T208-CMOA-20: fitness delta negative for low success rate
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_20_negative_delta_for_low_success(healthy_cmoa):
    recs = _make_records(1, "SUCCESS") + _make_records(9, "FAILED")
    result = healthy_cmoa.analyse(inject_records=recs)
    delta = result["fitness_signal"]["delta"]
    assert delta < 0.0, "Low success rate must yield negative fitness delta"


# ===========================================================================
# T208-CMOA-21: neutral success rate (40–80%) gives delta = 0.0
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_21_neutral_delta_mid_range(healthy_cmoa):
    # 5/10 = 50% success → delta should be 0.0
    recs = _make_records(5, "SUCCESS") + _make_records(5, "FAILED")
    result = healthy_cmoa.analyse(inject_records=recs)
    delta = result["fitness_signal"]["delta"]
    assert delta == 0.0


# ===========================================================================
# T208-CMOA-22: recalibrate succeeds for HUMAN-0 (CMOA-HUMAN0-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_22_recalibrate_human0_succeeds(healthy_cmoa):
    rec = healthy_cmoa.recalibrate(
        human_id="HUMAN-0", fitness_delta_override=0.10, rationale="Phase 208 test"
    )
    assert rec["human_id"] == "HUMAN-0"
    assert rec["fitness_delta_override"] == 0.10
    assert rec["event"] == "HUMAN0_RECALIBRATION"


# ===========================================================================
# T208-CMOA-23: recalibrate rejects non-HUMAN-0 (CMOA-HUMAN0-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_23_recalibrate_rejects_non_human0(healthy_cmoa):
    from dorkllm.constitutional_mutation_outcome_analyst import CMOAHuman0Error
    with pytest.raises(CMOAHuman0Error):
        healthy_cmoa.recalibrate(human_id="RANDOM", fitness_delta_override=0.05)


# ===========================================================================
# T208-CMOA-24: recalibrate rejects delta > 0.20 (CMOA-BIAS-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_24_recalibrate_rejects_oob_delta(healthy_cmoa):
    from dorkllm.constitutional_mutation_outcome_analyst import CMOABiasError
    with pytest.raises(CMOABiasError):
        healthy_cmoa.recalibrate(human_id="HUMAN-0", fitness_delta_override=0.99)


# ===========================================================================
# T208-CMOA-25: recalibrate record sealed in ledger (CMOA-CHAIN-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_25_recalibrate_ledgered(healthy_cmoa):
    healthy_cmoa.recalibrate(human_id="HUMAN-0", fitness_delta_override=0.05)
    chain = healthy_cmoa.verify_chain()
    assert chain["valid"] is True
    assert chain["entries"] >= 1


# ===========================================================================
# T208-CMOA-26: get_history returns ledger records
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_26_get_history(healthy_cmoa):
    healthy_cmoa.analyse(inject_records=_make_records(4, "SUCCESS"))
    history = healthy_cmoa.get_history()
    assert len(history) >= 1


# ===========================================================================
# T208-CMOA-27: get_status returns correct engine name and invariant list
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_27_status_structure(healthy_cmoa):
    status = healthy_cmoa.get_status()
    assert status["engine"] == "CMOA"
    assert len(status["invariants"]) == 10
    assert "CMOA-CHAIN-0" in status["invariants"]
    assert "CMOA-BIAS-0" in status["invariants"]


# ===========================================================================
# T208-CMOA-28: signal_gate OPEN when CGDR HEALTHY
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_28_signal_gate_open_healthy(healthy_cmoa):
    assert healthy_cmoa.get_status()["signal_gate"] == "OPEN"


# ===========================================================================
# T208-CMOA-29: signal_gate BLOCKED when CGDR DRIFTED
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_29_signal_gate_blocked_drifted(drifted_cmoa):
    assert drifted_cmoa.get_status()["signal_gate"] == "BLOCKED"


# ===========================================================================
# T208-CMOA-30: NO_SIGNAL also logged in ledger (CMOA-AUDIT-0)
# ===========================================================================
@pytest.mark.phase208
def test_t208_cmoa_30_no_signal_audited(healthy_cmoa):
    # below min sample → NO_SIGNAL must still be ledgered
    healthy_cmoa.analyse(inject_records=_make_records(2, "SUCCESS"))
    chain = healthy_cmoa.verify_chain()
    assert chain["valid"] is True
    assert chain["entries"] >= 1
    history = healthy_cmoa.get_history()
    no_sig = [r for r in history if r.get("outcome") == "NO_SIGNAL"]
    assert len(no_sig) >= 1, "CMOA-AUDIT-0: NO_SIGNAL run must appear in ledger"
