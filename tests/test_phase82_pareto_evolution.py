# SPDX-License-Identifier: Apache-2.0
"""Phase 82 — Pareto Population Evolution Tests.

Tests ID: T82-PARETO-NN

Invariants under test:
  PARETO-0       Scalar fitness is advisory only — never drives dominance.
  PARETO-DET-0   Frontier computation is deterministic.
  PARETO-NONDEG-0 Non-empty input → non-empty frontier.
  PARETO-GOV-0   GovernanceGate evaluates every frontier candidate.
  COMP-LEDGER-0  Ledger written before result returned.
"""

from __future__ import annotations

import pathlib
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import pytest

from runtime.evolution.pareto_frontier import (
    PARETO_OBJECTIVES,
    ParetoFrontier,
    ParetoFrontierResult,
    ParetoObjectiveVector,
    build_objective_vector,
    build_objective_vector_from_fitness_context,
    _dominates,
)
from runtime.evolution.pareto_competition import (
    ParetoCompetitionOrchestrator,
    ParetoCompetitionResult,
    _epoch_digest,
)
from runtime.seed_competition import SeedCandidate
from runtime.evolution.lineage_v2 import LineageLedgerV2

pytestmark = pytest.mark.phase82


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _vec(cid: str, c=0.5, e=0.5, g=0.5, m=0.5, cd=0.5, scalar=0.0) -> ParetoObjectiveVector:
    return build_objective_vector(cid, correctness=c, efficiency=e, governance=g,
                                  maintainability=m, coverage_delta=cd, scalar_score=scalar)


def _candidate(cid: str, correctness=0.5, efficiency=0.5) -> SeedCandidate:
    ctx = {
        "epoch_id": f"ep-{cid}", "mutation_tier": "low",
        "correctness_score": correctness, "efficiency_score": efficiency,
        "policy_compliance_score": 0.8, "goal_alignment_score": 0.7,
        "simulated_market_score": 0.5, "coverage_delta": 0.5,
    }
    return SeedCandidate(candidate_id=cid, fitness_context=ctx, metadata={})


def _always_pass(cid: str, meta: Dict) -> str:
    return "pass"


def _always_fail(cid: str, meta: Dict) -> str:
    return "fail"


def _always_deferred(cid: str, meta: Dict) -> str:
    return "deferred"


def _make_ledger(tmp: pathlib.Path) -> LineageLedgerV2:
    return LineageLedgerV2(ledger_path=tmp / "ledger.jsonl")


def _make_orch(tmp: pathlib.Path, gate_fn=None) -> ParetoCompetitionOrchestrator:
    return ParetoCompetitionOrchestrator(
        ledger=_make_ledger(tmp),
        gate_fn=gate_fn or _always_pass,
        epoch_id_factory=lambda: "epoch-test-01",
    )


# ===========================================================================
# PARETO-DET-0 — Determinism
# ===========================================================================


def test_T82_PARETO_01_dominance_is_deterministic():
    """T82-PARETO-01: PARETO-DET-0 — _dominates is pure/deterministic."""
    a = _vec("a", c=0.9, e=0.9)
    b = _vec("b", c=0.5, e=0.5)
    assert _dominates(a, b, PARETO_OBJECTIVES) is True
    assert _dominates(a, b, PARETO_OBJECTIVES) is True  # repeat = same


def test_T82_PARETO_02_frontier_determinism():
    """T82-PARETO-02: PARETO-DET-0 — identical inputs → identical frontier."""
    vecs = [_vec("a", c=0.9), _vec("b", c=0.5), _vec("c", c=0.7)]
    pf = ParetoFrontier()
    r1 = pf.compute(vecs)
    r2 = pf.compute(vecs)
    assert r1.frontier_ids == r2.frontier_ids
    assert r1.frontier_digest == r2.frontier_digest


def test_T82_PARETO_03_frontier_digest_changes_on_different_input():
    """T82-PARETO-03: PARETO-DET-0 — different populations → different digests."""
    pf = ParetoFrontier()
    r1 = pf.compute([_vec("a", c=0.9), _vec("b", c=0.5)])
    r2 = pf.compute([_vec("a", c=0.5), _vec("b", c=0.9)])
    # Frontier members may differ; digests must differ if inputs differ
    assert r1.frontier_digest != r2.frontier_digest


def test_T82_PARETO_04_vector_digest_is_deterministic():
    """T82-PARETO-04: PARETO-DET-0 — vector_digest identical for same inputs."""
    v1 = _vec("x", c=0.8)
    v2 = _vec("x", c=0.8)
    assert v1.vector_digest == v2.vector_digest


# ===========================================================================
# PARETO-NONDEG-0 — Non-empty frontier
# ===========================================================================


def test_T82_PARETO_05_non_empty_input_non_empty_frontier():
    """T82-PARETO-05: PARETO-NONDEG-0 — non-empty input → non-empty frontier."""
    vecs = [_vec("a", c=0.9, e=0.9), _vec("b", c=0.5, e=0.5)]
    pf = ParetoFrontier()
    r = pf.compute(vecs)
    assert len(r.frontier_ids) >= 1


def test_T82_PARETO_06_all_mutually_non_dominated_all_frontier():
    """T82-PARETO-06: PARETO-NONDEG-0 — mutually non-dominated → all on frontier."""
    # a wins on correctness, b wins on efficiency — neither dominates the other
    vecs = [_vec("a", c=1.0, e=0.0), _vec("b", c=0.0, e=1.0)]
    pf = ParetoFrontier()
    r = pf.compute(vecs)
    assert set(r.frontier_ids) == {"a", "b"}
    assert len(r.dominated_ids) == 0


def test_T82_PARETO_07_empty_input_empty_result():
    """T82-PARETO-07: empty input → empty frontier (boundary case)."""
    pf = ParetoFrontier()
    r = pf.compute([])
    assert r.frontier_ids == ()
    assert r.dominated_ids == ()


def test_T82_PARETO_08_single_candidate_is_own_frontier():
    """T82-PARETO-08: PARETO-NONDEG-0 — single candidate is always on frontier."""
    pf = ParetoFrontier()
    r = pf.compute([_vec("solo")])
    assert r.frontier_ids == ("solo",)
    assert r.dominated_ids == ()


# ===========================================================================
# Dominance logic
# ===========================================================================


def test_T82_PARETO_09_clear_dominance():
    """T82-PARETO-09: strictly better on all objectives → dominates."""
    a = _vec("a", c=0.9, e=0.9, g=0.9, m=0.9, cd=0.9)
    b = _vec("b", c=0.5, e=0.5, g=0.5, m=0.5, cd=0.5)
    assert _dominates(a, b, PARETO_OBJECTIVES) is True
    assert _dominates(b, a, PARETO_OBJECTIVES) is False


def test_T82_PARETO_10_equal_does_not_dominate():
    """T82-PARETO-10: equal on all objectives → neither dominates."""
    a = _vec("a", c=0.7, e=0.7, g=0.7, m=0.7, cd=0.7)
    b = _vec("b", c=0.7, e=0.7, g=0.7, m=0.7, cd=0.7)
    assert _dominates(a, b, PARETO_OBJECTIVES) is False
    assert _dominates(b, a, PARETO_OBJECTIVES) is False


def test_T82_PARETO_11_partial_better_does_not_dominate_when_worse_elsewhere():
    """T82-PARETO-11: better on some, worse on others → no dominance."""
    a = _vec("a", c=1.0, e=0.0)
    b = _vec("b", c=0.0, e=1.0)
    assert _dominates(a, b, PARETO_OBJECTIVES) is False
    assert _dominates(b, a, PARETO_OBJECTIVES) is False


def test_T82_PARETO_12_dominated_candidate_not_on_frontier():
    """T82-PARETO-12: dominated candidate excluded from frontier_ids."""
    a = _vec("a", c=0.9, e=0.9, g=0.9, m=0.9, cd=0.9)
    b = _vec("b", c=0.5, e=0.5, g=0.5, m=0.5, cd=0.5)
    pf = ParetoFrontier()
    r = pf.compute([a, b])
    assert "a" in r.frontier_ids
    assert "b" not in r.frontier_ids
    assert "b" in r.dominated_ids


def test_T82_PARETO_13_dominance_pair_recorded():
    """T82-PARETO-13: dominator-dominated pair recorded in dominance_pairs."""
    a = _vec("a", c=0.9, e=0.9, g=0.9, m=0.9, cd=0.9)
    b = _vec("b", c=0.1, e=0.1, g=0.1, m=0.1, cd=0.1)
    pf = ParetoFrontier()
    r = pf.compute([a, b])
    assert ("a", "b") in r.dominance_pairs


# ===========================================================================
# PARETO-0 — Scalar advisory only
# ===========================================================================


def test_T82_PARETO_14_scalar_does_not_affect_dominance():
    """T82-PARETO-14: PARETO-0 — scalar_score never changes dominance outcome."""
    # a dominates b on objectives regardless of scalar
    a = _vec("a", c=0.9, e=0.9, g=0.9, m=0.9, cd=0.9, scalar=0.1)
    b = _vec("b", c=0.5, e=0.5, g=0.5, m=0.5, cd=0.5, scalar=0.99)
    assert _dominates(a, b, PARETO_OBJECTIVES) is True


def test_T82_PARETO_15_scalar_used_for_frontier_ranking():
    """T82-PARETO-15: PARETO-0 — within frontier, scalar determines advisory rank."""
    a = _vec("a", c=1.0, e=0.0, scalar=0.3)  # non-dominated
    b = _vec("b", c=0.0, e=1.0, scalar=0.8)  # non-dominated
    pf = ParetoFrontier()
    r = pf.compute([a, b])
    ranked = pf.rank_frontier(r, [a, b])
    # b has higher scalar → ranked first
    assert ranked[0][0] == "b"
    assert ranked[1][0] == "a"


# ===========================================================================
# ParetoObjectiveVector round-trip
# ===========================================================================


def test_T82_PARETO_16_vector_roundtrip():
    """T82-PARETO-16: ParetoObjectiveVector to_dict/from_dict round-trip."""
    v = _vec("test", c=0.8, e=0.6, scalar=0.75)
    v2 = ParetoObjectiveVector.from_dict(v.to_dict())
    assert v == v2


def test_T82_PARETO_17_frontier_result_roundtrip():
    """T82-PARETO-17: ParetoFrontierResult to_dict/from_dict round-trip."""
    pf = ParetoFrontier()
    vecs = [_vec("a", c=0.9), _vec("b", c=0.5)]
    r = pf.compute(vecs)
    r2 = ParetoFrontierResult.from_dict(r.to_dict())
    assert r.frontier_ids == r2.frontier_ids
    assert r.frontier_digest == r2.frontier_digest


# ===========================================================================
# build_objective_vector_from_fitness_context
# ===========================================================================


def test_T82_PARETO_18_build_from_context_clamps_values():
    """T82-PARETO-18: build_from_context clamps objectives to [0, 1]."""
    ctx = {
        "correctness_score": 1.5,  # over 1
        "efficiency_score": -0.1,  # under 0
        "policy_compliance_score": 0.8,
        "goal_alignment_score": 0.7,
        "simulated_market_score": 0.5,
        "coverage_delta": 0.6,
    }
    v = build_objective_vector_from_fitness_context("c", ctx)
    for obj, score in v.objectives.items():
        assert 0.0 <= score <= 1.0, f"{obj}={score} out of [0,1]"


# ===========================================================================
# ParetoCompetitionOrchestrator — integration
# ===========================================================================


def test_T82_PARETO_19_basic_epoch_returns_result():
    """T82-PARETO-19: basic 2-candidate epoch returns ParetoCompetitionResult."""
    with tempfile.TemporaryDirectory() as td:
        orch = _make_orch(pathlib.Path(td))
        result = orch.run_epoch([_candidate("a", correctness=0.9), _candidate("b", correctness=0.5)])
        assert isinstance(result, ParetoCompetitionResult)
        assert len(result.frontier_ids) >= 1
        assert result.gate_verdict == "pass"


def test_T82_PARETO_20_empty_candidates_raises():
    """T82-PARETO-20: PARETO-NONDEG-0 — empty input raises ValueError."""
    with tempfile.TemporaryDirectory() as td:
        orch = _make_orch(pathlib.Path(td))
        with pytest.raises(ValueError, match="PARETO-NONDEG-0"):
            orch.run_epoch([])


def test_T82_PARETO_21_ledger_written_before_return():
    """T82-PARETO-21: COMP-LEDGER-0 — ledger entry written before result returned."""
    import json
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        ledger = _make_ledger(tmp)
        orch = ParetoCompetitionOrchestrator(
            ledger=ledger, gate_fn=_always_pass,
            epoch_id_factory=lambda: "ep-ledger",
        )
        orch.run_epoch([_candidate("x")])
        lines = ledger.ledger_path.read_text().strip().splitlines()
        events = [json.loads(l) for l in lines]
        types = [e["type"] for e in events]
        assert "ParetoCompetitionEpochEvent" in types


def test_T82_PARETO_22_all_fail_gate_writes_ledger_then_raises():
    """T82-PARETO-22: PARETO-GOV-0 — all fail gate → ledger written, RuntimeError raised."""
    import json
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        ledger = _make_ledger(tmp)
        orch = ParetoCompetitionOrchestrator(
            ledger=ledger, gate_fn=_always_fail,
            epoch_id_factory=lambda: "ep-all-fail",
        )
        with pytest.raises(RuntimeError, match="PARETO-GOV-0"):
            orch.run_epoch([_candidate("a"), _candidate("b")])
        events = [json.loads(l) for l in ledger.ledger_path.read_text().strip().splitlines()]
        assert any(e["type"] == "ParetoCompetitionEpochEvent" for e in events)
        pareto_events = [e for e in events if e["type"] == "ParetoCompetitionEpochEvent"]
        assert pareto_events[-1]["payload"]["gate_verdict"] == "fail"


def test_T82_PARETO_22A_deferred_gate_verdict_is_rejected():
    """T82-PARETO-22A: deferred verdict is unsupported in Pareto run_epoch flow."""
    with tempfile.TemporaryDirectory() as td:
        orch = ParetoCompetitionOrchestrator(
            ledger=_make_ledger(pathlib.Path(td)), gate_fn=_always_deferred,
            epoch_id_factory=lambda: "ep-deferred",
        )
        with pytest.raises(ValueError, match="unsupported gate verdict"):
            orch.run_epoch([_candidate("a"), _candidate("b")])


def test_T82_PARETO_23_gate_called_for_all_frontier_candidates():
    """T82-PARETO-23: PARETO-GOV-0 — gate called for every frontier candidate."""
    evaluated: List[str] = []

    def _tracking(cid: str, meta: Dict) -> str:
        evaluated.append(cid)
        return "pass"

    with tempfile.TemporaryDirectory() as td:
        orch = ParetoCompetitionOrchestrator(
            ledger=_make_ledger(pathlib.Path(td)), gate_fn=_tracking,
            epoch_id_factory=lambda: "ep-gate-track",
        )
        # All three are non-dominated (each wins on different objectives)
        orch.run_epoch([
            _candidate("a", correctness=1.0, efficiency=0.0),
            _candidate("b", correctness=0.0, efficiency=1.0),
        ])
        # Both are on frontier → both evaluated
        assert set(evaluated) == {"a", "b"}


def test_T82_PARETO_24_multiple_promoted_candidates():
    """T82-PARETO-24: Multiple non-dominated candidates all eligible for promotion."""
    with tempfile.TemporaryDirectory() as td:
        orch = _make_orch(pathlib.Path(td))
        result = orch.run_epoch([
            _candidate("a", correctness=1.0, efficiency=0.0),
            _candidate("b", correctness=0.0, efficiency=1.0),
            _candidate("c", correctness=0.5, efficiency=0.5),
        ])
        # a and b are non-dominated; c is dominated by one of them
        assert len(result.passed_gate_ids) >= 1


def test_T82_PARETO_25_dominated_candidates_not_gated():
    """T82-PARETO-25: Dominated candidates are excluded from gate evaluation."""
    gated: List[str] = []

    def _tracking(cid: str, meta: Dict) -> str:
        gated.append(cid)
        return "pass"

    with tempfile.TemporaryDirectory() as td:
        orch = ParetoCompetitionOrchestrator(
            ledger=_make_ledger(pathlib.Path(td)), gate_fn=_tracking,
            epoch_id_factory=lambda: "ep-dom-skip",
        )
        # a clearly dominates b (better on all objectives)
        result = orch.run_epoch([
            _candidate("a", correctness=0.9, efficiency=0.9),
            _candidate("b", correctness=0.1, efficiency=0.1),
        ])
        # Only frontier candidates (a) should be gated
        assert "b" not in gated


def test_T82_PARETO_26_winner_id_is_top_scalar_ranked_passer():
    """T82-PARETO-26: PARETO-0 — winner_id is highest scalar-ranked gate passer."""
    with tempfile.TemporaryDirectory() as td:
        orch = _make_orch(pathlib.Path(td))
        result = orch.run_epoch([_candidate("solo")])
        assert result.winner_id == "solo"


def test_T82_PARETO_27_epoch_digest_deterministic():
    """T82-PARETO-27: PARETO-DET-0 — epoch_digest deterministic for same input."""
    with tempfile.TemporaryDirectory() as td:
        orch1 = _make_orch(pathlib.Path(td))
        orch2 = ParetoCompetitionOrchestrator(
            ledger=_make_ledger(pathlib.Path(td) / "l2"),
            gate_fn=_always_pass,
            epoch_id_factory=lambda: "epoch-test-01",
        )
        cs = [_candidate("a"), _candidate("b")]
        r1 = orch1.run_epoch(cs)
        r2 = orch2.run_epoch(cs)
        assert r1.epoch_digest == r2.epoch_digest


def test_T82_PARETO_28_single_candidate_epoch_succeeds():
    """T82-PARETO-28: PARETO-NONDEG-0 — single candidate forms own frontier."""
    with tempfile.TemporaryDirectory() as td:
        orch = _make_orch(pathlib.Path(td))
        result = orch.run_epoch([_candidate("only")])
        assert "only" in result.frontier_ids
        assert result.winner_id == "only"


def test_T82_PARETO_29_ledger_payload_has_frontier_info():
    """T82-PARETO-29: COMP-LEDGER-0 — ledger entry contains frontier_ids and phase."""
    import json
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        ledger = _make_ledger(tmp)
        orch = ParetoCompetitionOrchestrator(
            ledger=ledger, gate_fn=_always_pass,
            epoch_id_factory=lambda: "ep-payload",
        )
        orch.run_epoch([_candidate("x", correctness=0.8)])
        events = [json.loads(l) for l in ledger.ledger_path.read_text().strip().splitlines()]
        pareto_events = [e for e in events if e["type"] == "ParetoCompetitionEpochEvent"]
        assert pareto_events
        payload = pareto_events[-1]["payload"]
        assert "frontier_ids" in payload
        assert payload["phase"] == 82


def test_T82_PARETO_30_five_candidate_pareto():
    """T82-PARETO-30: 5-candidate epoch with mixed dominance relationships."""
    pf = ParetoFrontier()
    vecs = [
        _vec("a", c=1.0, e=0.0, g=0.5, m=0.5, cd=0.5),  # frontier
        _vec("b", c=0.0, e=1.0, g=0.5, m=0.5, cd=0.5),  # frontier
        _vec("c", c=0.5, e=0.5, g=1.0, m=0.5, cd=0.5),  # frontier
        _vec("d", c=0.4, e=0.4, g=0.4, m=0.4, cd=0.4),  # dominated
        _vec("e", c=0.3, e=0.3, g=0.3, m=0.3, cd=0.3),  # dominated
    ]
    r = pf.compute(vecs)
    assert set(r.frontier_ids) == {"a", "b", "c"}
    assert set(r.dominated_ids) == {"d", "e"}


def test_T82_PARETO_31_objectives_tuple_returned():
    """T82-PARETO-31: ParetoFrontier.objectives() returns configured objectives."""
    pf = ParetoFrontier()
    assert pf.objectives() == PARETO_OBJECTIVES


def test_T82_PARETO_32_frontier_ids_sorted():
    """T82-PARETO-32: PARETO-DET-0 — frontier_ids always returned in sorted order."""
    pf = ParetoFrontier()
    # All mutually non-dominated
    vecs = [_vec("z"), _vec("a"), _vec("m")]
    r = pf.compute(vecs)
    assert list(r.frontier_ids) == sorted(r.frontier_ids)
