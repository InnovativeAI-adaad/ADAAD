# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase169_mse.py — INNOV-75 · Mutation Selection Engine
Grade-A 30-test suite · Phase 169 · v9.102.0
Markers: T169-MSE-01 … T169-MSE-30
"""

import pytest
from dorkllm.mutation_selection_engine import (
    CANONICAL_AXES,
    DEFAULT_WEIGHTS,
    MAX_BLAST_RADIUS,
    MSE_WINDOW_SIZE,
    SCORE_FLOOR,
    MSEAtomicError,
    MSEAxisError,
    MSEBlastReject,
    MSEFloorReject,
    MSEHuman0Flag,
    MSETamperError,
    MutationCandidate,
    MutationSelectionEngine,
    CandidateTier,
    SelectionVerdict,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _perfect_candidate(cid: str = "CAND-PERFECT", tier: CandidateTier = CandidateTier.TIER2) -> MutationCandidate:
    return MutationCandidate(
        candidate_id=cid,
        label="Perfect candidate",
        tier=tier,
        blast_radius=0.1,
        axis_scores={ax: 1.0 for ax in CANONICAL_AXES},
    )

def _floor_candidate(cid: str = "CAND-FLOOR") -> MutationCandidate:
    return MutationCandidate(
        candidate_id=cid,
        label="Below floor",
        tier=CandidateTier.TIER2,
        blast_radius=0.1,
        axis_scores={ax: 0.0 for ax in CANONICAL_AXES},
    )

@pytest.fixture
def mse():
    return MutationSelectionEngine()


# ── T169-MSE-01 — Engine initialises without error ───────────────────────────
@pytest.mark.phase169
def test_engine_init(mse):
    assert mse is not None


# ── T169-MSE-02 — Default weights cover all canonical axes ───────────────────
@pytest.mark.phase169
def test_default_weights_cover_all_axes():
    assert set(DEFAULT_WEIGHTS.keys()) == CANONICAL_AXES


# ── T169-MSE-03 — Default weights sum to 1.0 ────────────────────────────────
@pytest.mark.phase169
def test_default_weights_sum_to_one():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


# ── T169-MSE-04 — MSE-SCOPE-0: unknown axis in candidate raises ──────────────
@pytest.mark.phase169
def test_unknown_axis_in_candidate_raises():
    with pytest.raises(MSEAxisError):
        MutationCandidate(
            candidate_id="BAD",
            label="bad",
            tier=CandidateTier.TIER2,
            blast_radius=0.1,
            axis_scores={"unknown_axis": 0.5},
        )


# ── T169-MSE-05 — MSE-SCOPE-0: unknown axis in engine weights raises ──────────
@pytest.mark.phase169
def test_unknown_axis_in_weights_raises():
    with pytest.raises(MSEAxisError):
        MutationSelectionEngine(weights={"alien_axis": 0.5})


# ── T169-MSE-06 — score() returns FitnessScore with correct candidate_id ─────
@pytest.mark.phase169
def test_score_candidate_id(mse):
    c = _perfect_candidate()
    fs = mse.score(c)
    assert fs.candidate_id == c.candidate_id


# ── T169-MSE-07 — MSE-RANK-0: perfect scores yield max weighted_score ─────────
@pytest.mark.phase169
def test_score_perfect(mse):
    fs = mse.score(_perfect_candidate())
    assert abs(fs.weighted_score - 1.0) < 1e-6


# ── T169-MSE-08 — MSE-RANK-0: zero scores yield 0.0 weighted_score ───────────
@pytest.mark.phase169
def test_score_zero(mse):
    fs = mse.score(_floor_candidate())
    assert fs.weighted_score == pytest.approx(0.0, abs=1e-6)


# ── T169-MSE-09 — MSE-RANK-0: scoring is deterministic ──────────────────────
@pytest.mark.phase169
def test_score_deterministic(mse):
    c = _perfect_candidate()
    s1 = mse.score(c).weighted_score
    mse2 = MutationSelectionEngine()
    s2 = mse2.score(c).weighted_score
    assert s1 == pytest.approx(s2)


# ── T169-MSE-10 — score_hash changes when score changes ──────────────────────
@pytest.mark.phase169
def test_score_hash_differs(mse):
    c1 = _perfect_candidate("C1")
    c2 = _floor_candidate("C2")
    h1 = mse.score(c1).score_hash
    h2 = mse.score(c2).score_hash
    assert h1 != h2


# ── T169-MSE-11 — MSE-BLAST-0: blast_radius > MAX raises MSEBlastReject ──────
@pytest.mark.phase169
def test_blast_radius_exceeded_raises(mse):
    c = MutationCandidate(
        candidate_id="HIGH-BLAST",
        label="Risky",
        tier=CandidateTier.TIER2,
        blast_radius=MAX_BLAST_RADIUS + 0.01,
        axis_scores={ax: 0.8 for ax in CANONICAL_AXES},
    )
    with pytest.raises(MSEBlastReject):
        mse.select(c)


# ── T169-MSE-12 — MSE-BLAST-0: blast_radius == MAX is accepted ───────────────
@pytest.mark.phase169
def test_blast_radius_at_cap_accepted(mse):
    c = MutationCandidate(
        candidate_id="EDGE-BLAST",
        label="Edge",
        tier=CandidateTier.TIER2,
        blast_radius=MAX_BLAST_RADIUS,
        axis_scores={ax: 1.0 for ax in CANONICAL_AXES},
    )
    rec = mse.select(c)
    assert rec.verdict == SelectionVerdict.SELECTED


# ── T169-MSE-13 — MSE-HUMAN0-0: Tier-0 without ratification raises ───────────
@pytest.mark.phase169
def test_tier0_unratified_raises(mse):
    c = _perfect_candidate("T0-UNRAT", tier=CandidateTier.TIER0)
    c.ratified = False
    with pytest.raises(MSEHuman0Flag):
        mse.select(c)


# ── T169-MSE-14 — MSE-HUMAN0-0: Tier-0 with ratification is selectable ───────
@pytest.mark.phase169
def test_tier0_ratified_selected(mse):
    c = _perfect_candidate("T0-RAT", tier=CandidateTier.TIER0)
    c.ratified = True
    rec = mse.select(c)
    assert rec.verdict == SelectionVerdict.SELECTED


# ── T169-MSE-15 — MSE-FLOOR-0: below-floor candidate is rejected ─────────────
@pytest.mark.phase169
def test_below_floor_rejected(mse):
    rec = mse.select(_floor_candidate())
    assert rec.verdict == SelectionVerdict.REJECTED


# ── T169-MSE-16 — Rejected record still appended to ledger ───────────────────
@pytest.mark.phase169
def test_rejected_in_ledger(mse):
    mse.select(_floor_candidate())
    assert len(mse.ledger()) == 1
    assert mse.ledger()[0]["verdict"] == "REJECTED"


# ── T169-MSE-17 — MSE-WINDOW-0: window fills to MSE_WINDOW_SIZE ──────────────
@pytest.mark.phase169
def test_window_fills(mse):
    for i in range(MSE_WINDOW_SIZE):
        mse.select(_perfect_candidate(f"C{i}"))
    assert len(mse.window_status()["active"]) == MSE_WINDOW_SIZE


# ── T169-MSE-18 — MSE-WINDOW-0: candidate after full window is deferred ──────
@pytest.mark.phase169
def test_window_full_defers(mse):
    for i in range(MSE_WINDOW_SIZE):
        mse.select(_perfect_candidate(f"C{i}"))
    rec = mse.select(_perfect_candidate("OVERFLOW"))
    assert rec.verdict == SelectionVerdict.DEFERRED


# ── T169-MSE-19 — release() frees window slot ────────────────────────────────
@pytest.mark.phase169
def test_release_frees_slot(mse):
    mse.select(_perfect_candidate("C0"))
    before = mse.window_status()["available_slots"]
    mse.release("C0")
    after = mse.window_status()["available_slots"]
    assert after == before + 1


# ── T169-MSE-20 — release() returns False for unknown candidate ───────────────
@pytest.mark.phase169
def test_release_unknown_returns_false(mse):
    assert mse.release("NONEXISTENT") is False


# ── T169-MSE-21 — MSE-CHAIN-0: verify_chain passes on clean ledger ───────────
@pytest.mark.phase169
def test_verify_chain_clean(mse):
    mse.select(_perfect_candidate("C1"))
    mse.select(_floor_candidate("C2"))
    assert mse.verify_chain() is True


# ── T169-MSE-22 — MSE-CHAIN-0: tampered record_hash raises MSETamperError ────
@pytest.mark.phase169
def test_verify_chain_tamper_detected(mse):
    mse.select(_perfect_candidate("C1"))
    mse._ledger[0].record_hash = "deadbeef" * 8
    with pytest.raises(MSETamperError):
        mse.verify_chain()


# ── T169-MSE-23 — MSE-PERSIST-0: ledger grows monotonically ──────────────────
@pytest.mark.phase169
def test_ledger_grows(mse):
    assert len(mse.ledger()) == 0
    mse.select(_perfect_candidate("C1"))
    assert len(mse.ledger()) == 1
    mse.select(_floor_candidate("C2"))
    assert len(mse.ledger()) == 2


# ── T169-MSE-24 — MSE-AUDIT-0: history records scoring events ────────────────
@pytest.mark.phase169
def test_history_records_events(mse):
    mse.select(_perfect_candidate("C1"))
    h = mse.history()
    event_types = [e["event"] for e in h]
    assert "score" in event_types
    assert "select" in event_types


# ── T169-MSE-25 — rank() sorts candidates by score descending ────────────────
@pytest.mark.phase169
def test_rank_descending(mse):
    c_high = _perfect_candidate("HIGH")
    c_low  = _floor_candidate("LOW")
    ranked = mse.rank([c_low, c_high])
    assert ranked[0][0].candidate_id == "HIGH"


# ── T169-MSE-26 — rank() does not append to ledger ───────────────────────────
@pytest.mark.phase169
def test_rank_no_ledger_entry(mse):
    mse.rank([_perfect_candidate("R1"), _perfect_candidate("R2")])
    # ledger should still be empty (rank() doesn't call select())
    assert len(mse.ledger()) == 0


# ── T169-MSE-27 — stats() selected count matches actual ──────────────────────
@pytest.mark.phase169
def test_stats_selected_count(mse):
    mse.select(_perfect_candidate("C1"))
    mse.select(_perfect_candidate("C2"))
    mse.select(_floor_candidate("C3"))
    s = mse.stats()
    assert s["selected"] == 2
    assert s["rejected"] == 1


# ── T169-MSE-28 — SCORE_FLOOR and MSE_WINDOW_SIZE constants correct ──────────
@pytest.mark.phase169
def test_constants_correct():
    assert SCORE_FLOOR == 0.25
    assert MSE_WINDOW_SIZE == 5


# ── T169-MSE-29 — Axis scores are clamped to [0.0, 1.0] ──────────────────────
@pytest.mark.phase169
def test_axis_score_clamping():
    c = MutationCandidate(
        candidate_id="CLAMP",
        label="clamp test",
        tier=CandidateTier.TIER2,
        blast_radius=0.1,
        axis_scores={ax: 999.0 for ax in CANONICAL_AXES},
    )
    assert all(v <= 1.0 for v in c.axis_scores.values())


# ── T169-MSE-30 — Full constitutional workflow ────────────────────────────────
@pytest.mark.phase169
def test_full_workflow(mse):
    # Rank a mixed pool
    candidates = [_perfect_candidate(f"C{i}") for i in range(3)] + [_floor_candidate("LOW")]
    ranked = mse.rank(candidates)
    assert ranked[0][1] > ranked[-1][1]

    # Select top candidates
    for c, _ in ranked[:3]:
        mse.select(c)

    # Verify chain integrity
    assert mse.verify_chain() is True

    # Release one to free window
    mse.release(ranked[0][0].candidate_id)
    assert mse.window_status()["available_slots"] >= 1

    # Stats
    s = mse.stats()
    assert s["total_evaluated"] >= 3
    assert s["selected"] >= 2
