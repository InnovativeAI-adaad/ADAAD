# SPDX-License-Identifier: Apache-2.0
"""Phase 165 · INNOV-71 · V10 Convergence Assessor (V10CA) — 30 acceptance tests.

All tests must pass at Grade-A before governance artifacts are authored.
pytest marker: phase165
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dorkllm.convergence_assessor import (
    CANONICAL_CRITERIA,
    CHAIN_ROOT,
    V10_MIN_DORK_FLEET,
    V10_MIN_FORECAST_PHASES,
    V10_MIN_INNOVATIONS,
    V10_MIN_INVARIANTS,
    V10_PROMOTION_GATE,
    CriterionStatus,
    V10CAChainError,
    V10CAHuman0Gate,
    V10CAScopeError,
    V10ConvergenceAssessor,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# SAFE_INPUTS: score ~0.820 — below V10_PROMOTION_GATE (0.90)
CURRENT_INPUTS = {
    "hard_invariant_count": 200,
    "innovation_count": 50,
    "genome_chain_valid": True,
    "genome_entry_count": 3,
    "self_repair_actions": 12,
    "forecast_window": 8,
    "dork_fleet_size": 5,
    "dork_router_live": True,
    "ga_version_published": "9.78.0",
    "repo_version": "9.97.0",
}
# ACTUAL current ADAAD state (score ~0.900)
ACTUAL_CURRENT_INPUTS = {
    "hard_invariant_count": 305,
    "innovation_count": 70,
    "genome_chain_valid": True,
    "genome_entry_count": 3,
    "self_repair_actions": 12,
    "forecast_window": 8,
    "dork_fleet_size": 5,
    "dork_router_live": True,
    "ga_version_published": "9.78.0",
    "repo_version": "9.97.0",
}

V10_READY_INPUTS = {
    "hard_invariant_count": 350,
    "innovation_count": 75,
    "genome_chain_valid": True,
    "genome_entry_count": 5,
    "self_repair_actions": 20,
    "forecast_window": 10,
    "dork_fleet_size": 5,
    "dork_router_live": True,
    "ga_version_published": "9.97.0",
    "repo_version": "9.97.0",
}

ZERO_INPUTS: dict = {}


@pytest.fixture
def tmp_assessor(tmp_path):
    """Fresh assessor backed by a temp ledger."""
    return V10ConvergenceAssessor(ledger_path=tmp_path / "v10ca_ledger.jsonl")


# ---------------------------------------------------------------------------
# T165-V10CA-01 — Module imports without error
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_01_module_imports():
    from dorkllm import convergence_assessor  # noqa: F401
    assert True


# ---------------------------------------------------------------------------
# T165-V10CA-02 — Assessor instantiates with default path
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_02_default_instantiation(tmp_assessor):
    assert tmp_assessor is not None


# ---------------------------------------------------------------------------
# T165-V10CA-03 — Canonical criteria tuple has exactly 7 entries
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_03_canonical_criteria_count():
    assert len(CANONICAL_CRITERIA) == 7


# ---------------------------------------------------------------------------
# T165-V10CA-04 — Canonical criteria names are correct
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_04_canonical_criteria_names():
    expected = (
        "INVARIANT_DENSITY", "INNOVATION_DEPTH", "GENOME_INTEGRITY",
        "SELF_REPAIR_ACTIVE", "FORECAST_COVERAGE", "DORK_INTELLIGENCE", "GA_ALIGNMENT",
    )
    assert CANONICAL_CRITERIA == expected


# ---------------------------------------------------------------------------
# T165-V10CA-05 — assess() returns a ConvergenceSnapshot
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_05_assess_returns_snapshot(tmp_assessor):
    snap = tmp_assessor.assess("t05", CURRENT_INPUTS)
    assert snap is not None
    assert snap.convergence_score >= 0.0


# ---------------------------------------------------------------------------
# T165-V10CA-06 — Snapshot has exactly 7 criteria results
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_06_snapshot_has_seven_criteria(tmp_assessor):
    snap = tmp_assessor.assess("t06", CURRENT_INPUTS)
    assert len(snap.criteria) == 7


# ---------------------------------------------------------------------------
# T165-V10CA-07 — Criteria names match CANONICAL_CRITERIA order
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_07_criteria_order_canonical(tmp_assessor):
    snap = tmp_assessor.assess("t07", CURRENT_INPUTS)
    names = tuple(c.criterion for c in snap.criteria)
    assert names == CANONICAL_CRITERIA


# ---------------------------------------------------------------------------
# T165-V10CA-08 — Convergence score is between 0 and 1 (inclusive)
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_08_score_bounded(tmp_assessor):
    snap = tmp_assessor.assess("t08", CURRENT_INPUTS)
    assert 0.0 <= snap.convergence_score <= 1.0


# ---------------------------------------------------------------------------
# T165-V10CA-09 — Zero inputs produce score > 0 (genome, DORK router partial)
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_09_zero_inputs_score_zero(tmp_assessor):
    snap = tmp_assessor.assess("t09", ZERO_INPUTS)
    assert snap.convergence_score == 0.0


# ---------------------------------------------------------------------------
# T165-V10CA-10 — V10-ready inputs produce score = 1.0
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_10_v10_ready_score_one(tmp_assessor):
    with pytest.raises(V10CAHuman0Gate):
        tmp_assessor.assess("t10", V10_READY_INPUTS)
    snap = tmp_assessor.history()[-1]
    assert snap.convergence_score == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# T165-V10CA-11 — V10CA-DETERM-0: identical inputs → identical score
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_11_determ_same_inputs(tmp_path):
    a1 = V10ConvergenceAssessor(ledger_path=tmp_path / "a1.jsonl")
    a2 = V10ConvergenceAssessor(ledger_path=tmp_path / "a2.jsonl")
    s1 = a1.assess("t11", CURRENT_INPUTS)
    s2 = a2.assess("t11", CURRENT_INPUTS)
    assert s1.convergence_score == s2.convergence_score


# ---------------------------------------------------------------------------
# T165-V10CA-12 — V10CA-CHAIN-0: digest is non-empty hex string
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_12_chain_digest_nonempty(tmp_assessor):
    snap = tmp_assessor.assess("t12", CURRENT_INPUTS)
    assert len(snap.digest) == 64
    assert all(c in "0123456789abcdef" for c in snap.digest)


# ---------------------------------------------------------------------------
# T165-V10CA-13 — V10CA-CHAIN-0: first snapshot prev_digest == CHAIN_ROOT
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_13_first_prev_digest_is_root(tmp_assessor):
    snap = tmp_assessor.assess("t13", CURRENT_INPUTS)
    assert snap.prev_digest == CHAIN_ROOT


# ---------------------------------------------------------------------------
# T165-V10CA-14 — V10CA-CHAIN-0: second snapshot prev_digest == first digest
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_14_chain_links_correctly(tmp_assessor):
    s1 = tmp_assessor.assess("t14a", CURRENT_INPUTS)
    s2 = tmp_assessor.assess("t14b", CURRENT_INPUTS)
    assert s2.prev_digest == s1.digest


# ---------------------------------------------------------------------------
# T165-V10CA-15 — verify_chain() returns True on intact chain
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_15_verify_chain_intact(tmp_assessor):
    tmp_assessor.assess("t15a", CURRENT_INPUTS)
    tmp_assessor.assess("t15b", CURRENT_INPUTS)
    assert tmp_assessor.verify_chain() is True


# ---------------------------------------------------------------------------
# T165-V10CA-16 — verify_chain() raises on tampered ledger
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_16_verify_chain_tampered(tmp_path):
    lp = tmp_path / "tamper.jsonl"
    a = V10ConvergenceAssessor(ledger_path=lp)
    try:
        a.assess("t16a", CURRENT_INPUTS)
    except V10CAHuman0Gate:
        pass
    try:
        a.assess("t16b", CURRENT_INPUTS)
    except V10CAHuman0Gate:
        pass
    # Tamper the ledger
    lines = lp.read_text().splitlines()
    first = json.loads(lines[0])
    first["convergence_score"] = 0.999
    lines[0] = json.dumps(first)
    lp.write_text("\n".join(lines) + "\n")
    # Reload should detect corruption
    with pytest.raises(V10CAChainError):
        V10ConvergenceAssessor(ledger_path=lp)


# ---------------------------------------------------------------------------
# T165-V10CA-17 — V10CA-HUMAN0-0: score >= gate raises V10CAHuman0Gate
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_17_human0_gate_fires(tmp_assessor):
    with pytest.raises(V10CAHuman0Gate):
        tmp_assessor.assess("t17", V10_READY_INPUTS)


# ---------------------------------------------------------------------------
# T165-V10CA-18 — V10CA-HUMAN0-0: gate fires AFTER ledger write
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_18_human0_gate_after_ledger(tmp_assessor):
    with pytest.raises(V10CAHuman0Gate):
        tmp_assessor.assess("t18", V10_READY_INPUTS)
    # Snapshot should be in ledger
    assert len(tmp_assessor.history()) == 1


# ---------------------------------------------------------------------------
# T165-V10CA-19 — V10CA-HUMAN0-0: human0_required=True in gated snapshot
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_19_human0_required_flag(tmp_assessor):
    with pytest.raises(V10CAHuman0Gate):
        tmp_assessor.assess("t19", V10_READY_INPUTS)
    snap = tmp_assessor.history()[-1]
    assert snap.human0_required is True


# ---------------------------------------------------------------------------
# T165-V10CA-20 — V10CA-SCOPE-0: CANONICAL_CRITERIA is immutable at runtime
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_20_canonical_criteria_immutable():
    with pytest.raises((TypeError, AttributeError)):
        CANONICAL_CRITERIA[0] = "TAMPERED"  # type: ignore[index]


# ---------------------------------------------------------------------------
# T165-V10CA-21 — V10CA-AUDIT-0: ledger file is created after assess()
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_21_ledger_created(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    a = V10ConvergenceAssessor(ledger_path=lp)
    assert not lp.exists() or lp.stat().st_size == 0
    a.assess("t21", CURRENT_INPUTS)
    assert lp.exists() and lp.stat().st_size > 0


# ---------------------------------------------------------------------------
# T165-V10CA-22 — V10CA-AUDIT-0: ledger entries are valid JSON
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_22_ledger_valid_json(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    a = V10ConvergenceAssessor(ledger_path=lp)
    a.assess("t22a", CURRENT_INPUTS)
    a.assess("t22b", CURRENT_INPUTS)
    for line in lp.read_text().splitlines():
        obj = json.loads(line)
        assert "snapshot_id" in obj
        assert "convergence_score" in obj


# ---------------------------------------------------------------------------
# T165-V10CA-23 — INVARIANT_DENSITY criterion: MET when count >= threshold
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_23_invariant_density_met(tmp_assessor):
    # Reduce other scores so overall stays below gate
    snap = tmp_assessor.assess("t23", {**CURRENT_INPUTS, "hard_invariant_count": V10_MIN_INVARIANTS, "self_repair_actions": 0})
    c = next(x for x in snap.criteria if x.criterion == "INVARIANT_DENSITY")
    assert c.status == CriterionStatus.MET
    assert c.score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# T165-V10CA-24 — INVARIANT_DENSITY criterion: UNMET when count = 0
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_24_invariant_density_unmet(tmp_assessor):
    snap = tmp_assessor.assess("t24", {**CURRENT_INPUTS, "hard_invariant_count": 0})
    c = next(x for x in snap.criteria if x.criterion == "INVARIANT_DENSITY")
    assert c.status == CriterionStatus.UNMET
    assert c.score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# T165-V10CA-25 — GENOME_INTEGRITY: MET when chain valid and entries > 0
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_25_genome_integrity_met(tmp_assessor):
    snap = tmp_assessor.assess("t25", {**CURRENT_INPUTS, "genome_chain_valid": True, "genome_entry_count": 5})
    c = next(x for x in snap.criteria if x.criterion == "GENOME_INTEGRITY")
    assert c.status == CriterionStatus.MET


# ---------------------------------------------------------------------------
# T165-V10CA-26 — GENOME_INTEGRITY: UNMET when no genomes and chain invalid
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_26_genome_integrity_unmet(tmp_assessor):
    snap = tmp_assessor.assess("t26", {**CURRENT_INPUTS, "genome_chain_valid": False, "genome_entry_count": 0})
    c = next(x for x in snap.criteria if x.criterion == "GENOME_INTEGRITY")
    assert c.status == CriterionStatus.UNMET
    assert c.score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# T165-V10CA-27 — GA_ALIGNMENT: MET when ga_version == repo_version
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_27_ga_alignment_met(tmp_assessor):
    snap = tmp_assessor.assess("t27", {**CURRENT_INPUTS, "ga_version_published": "9.97.0", "repo_version": "9.97.0"})
    c = next(x for x in snap.criteria if x.criterion == "GA_ALIGNMENT")
    assert c.status == CriterionStatus.MET
    assert c.score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# T165-V10CA-28 — GA_ALIGNMENT: PARTIAL when published but mismatched
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_28_ga_alignment_partial(tmp_assessor):
    snap = tmp_assessor.assess("t28", CURRENT_INPUTS)  # 9.78.0 vs 9.97.0
    c = next(x for x in snap.criteria if x.criterion == "GA_ALIGNMENT")
    assert c.status == CriterionStatus.PARTIAL


# ---------------------------------------------------------------------------
# T165-V10CA-29 — score() method returns float and does not raise HumanOGate
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_29_score_no_gate_raise(tmp_assessor):
    s = tmp_assessor.score(V10_READY_INPUTS, epoch_id="t29")
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# T165-V10CA-30 — history() returns all snapshots in insertion order
# ---------------------------------------------------------------------------
@pytest.mark.phase165
def test_30_history_ordered(tmp_assessor):
    tmp_assessor.assess("t30a", CURRENT_INPUTS)
    tmp_assessor.assess("t30b", {**CURRENT_INPUTS, "innovation_count": 60})
    tmp_assessor.assess("t30c", CURRENT_INPUTS)
    hist = tmp_assessor.history()
    assert len(hist) == 3
    assert hist[0].epoch_id == "t30a"
    assert hist[1].epoch_id == "t30b"
    assert hist[2].epoch_id == "t30c"
