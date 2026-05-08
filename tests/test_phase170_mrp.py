# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase170_mrp.py
Phase 170 · INNOV-76 · MRP — Mutation Risk Profiler
30 Grade-A constitutional tests · T170-MRP-01..30

Governor: DUSTIN L REID
"""

import hmac
import hashlib
import pytest

from dorkllm.mutation_risk_profiler import (
    CANONICAL_DIMENSIONS,
    DEFAULT_WEIGHTS,
    MAX_SCORE,
    MIN_SCORE,
    RISK_CEILING,
    MutationProposal,
    MutationRiskProfiler,
    ProfileRecord,
    ProfileStatus,
    RiskProfile,
    RiskVerdict,
    MRPAtomicError,
    MRPCeilingBlock,
    MRPDimensionError,
    MRPHuman0Required,
    MRPNegativeRiskError,
    MRPTamperError,
    HMAC_SECRET,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _low_risk_proposal(pid: str = "P-001") -> MutationProposal:
    """A proposal with all dimension scores at 0.1 → low composite risk."""
    return MutationProposal(
        proposal_id=pid,
        label="low-risk-test",
        dimension_scores={d: 0.1 for d in CANONICAL_DIMENSIONS},
    )


def _medium_risk_proposal(pid: str = "P-002") -> MutationProposal:
    """A proposal with dimension scores around 0.5 → medium composite risk."""
    return MutationProposal(
        proposal_id=pid,
        label="medium-risk-test",
        dimension_scores={d: 0.5 for d in CANONICAL_DIMENSIONS},
    )


def _critical_proposal(pid: str = "P-CRIT") -> MutationProposal:
    """A proposal with all dimension scores at 0.85 → CRITICAL verdict."""
    return MutationProposal(
        proposal_id=pid,
        label="critical-risk-test",
        dimension_scores={d: 0.85 for d in CANONICAL_DIMENSIONS},
    )


def _blocked_proposal(pid: str = "P-BLOCK") -> MutationProposal:
    """A proposal with all dimension scores at 0.95 → exceeds RISK_CEILING."""
    return MutationProposal(
        proposal_id=pid,
        label="blocked-risk-test",
        dimension_scores={d: 0.95 for d in CANONICAL_DIMENSIONS},
    )


# ── T170-MRP-01: MutationProposal accepts valid dimensions ────────────────────

def test_T170_MRP_01_proposal_valid_dimensions():
    proposal = _low_risk_proposal()
    assert set(proposal.dimension_scores.keys()) <= CANONICAL_DIMENSIONS


# ── T170-MRP-02: MutationProposal rejects unknown dimensions ─────────────────

def test_T170_MRP_02_proposal_rejects_unknown_dimension():
    with pytest.raises(MRPDimensionError):
        MutationProposal(
            proposal_id="P-BAD",
            label="bad",
            dimension_scores={"unknown_dim": 0.5},
        )


# ── T170-MRP-03: MutationProposal clamps scores to [0.0, 1.0] ────────────────

def test_T170_MRP_03_proposal_clamps_scores():
    proposal = MutationProposal(
        proposal_id="P-CLAMP",
        label="clamp",
        dimension_scores={d: 1.5 for d in CANONICAL_DIMENSIONS},
    )
    assert all(v <= MAX_SCORE for v in proposal.dimension_scores.values())
    proposal2 = MutationProposal(
        proposal_id="P-CLAMP2",
        label="clamp-neg",
        dimension_scores={d: -0.5 for d in CANONICAL_DIMENSIONS},
    )
    assert all(v >= MIN_SCORE for v in proposal2.dimension_scores.values())


# ── T170-MRP-04: compute_profile is deterministic (MRP-SCORE-0) ──────────────

def test_T170_MRP_04_profile_deterministic():
    mrp = MutationRiskProfiler()
    proposal = _medium_risk_proposal()
    p1 = mrp.compute_profile(proposal)
    p2 = mrp.compute_profile(proposal)
    assert p1.composite_risk == p2.composite_risk
    assert p1.verdict == p2.verdict


# ── T170-MRP-05: composite_risk is within [0.0, 1.0] ─────────────────────────

def test_T170_MRP_05_composite_risk_bounded():
    mrp = MutationRiskProfiler()
    for scores in ([0.0] * 5, [0.5] * 5, [1.0] * 5):
        proposal = MutationProposal(
            proposal_id=f"P-BOUND-{scores[0]}",
            label="bound",
            dimension_scores={d: s for d, s in zip(sorted(CANONICAL_DIMENSIONS), scores)},
        )
        rp = mrp.compute_profile(proposal)
        assert MIN_SCORE <= rp.composite_risk <= MAX_SCORE


# ── T170-MRP-06: low dimension scores → NEGLIGIBLE or LOW verdict ─────────────

def test_T170_MRP_06_low_scores_yield_low_verdict():
    mrp = MutationRiskProfiler()
    rp = mrp.compute_profile(_low_risk_proposal())
    assert rp.verdict in (RiskVerdict.NEGLIGIBLE, RiskVerdict.LOW)


# ── T170-MRP-07: medium dimension scores → MEDIUM verdict ────────────────────

def test_T170_MRP_07_medium_scores_yield_medium_verdict():
    mrp = MutationRiskProfiler()
    rp = mrp.compute_profile(_medium_risk_proposal())
    assert rp.verdict == RiskVerdict.MEDIUM


# ── T170-MRP-08: high dimension scores → HIGH or CRITICAL verdict ─────────────

def test_T170_MRP_08_high_scores_yield_high_or_critical():
    mrp = MutationRiskProfiler()
    proposal = MutationProposal(
        proposal_id="P-HIGH",
        label="high",
        dimension_scores={d: 0.72 for d in CANONICAL_DIMENSIONS},
    )
    rp = mrp.compute_profile(proposal)
    assert rp.verdict in (RiskVerdict.HIGH, RiskVerdict.CRITICAL)


# ── T170-MRP-09: RISK_CEILING auto-blocks proposal (MRP-CEIL-0) ───────────────

def test_T170_MRP_09_ceiling_blocks_proposal():
    mrp = MutationRiskProfiler()
    with pytest.raises(MRPCeilingBlock):
        mrp.profile(_blocked_proposal())


# ── T170-MRP-10: CRITICAL without HUMAN-0 → DEFERRED (MRP-HUMAN0-0) ──────────

def test_T170_MRP_10_critical_without_human0_deferred():
    mrp = MutationRiskProfiler(risk_ceiling=0.99)  # allow critical through ceiling
    proposal = _critical_proposal()
    rp, record = mrp.profile(proposal)
    assert rp.verdict == RiskVerdict.CRITICAL
    assert record.status == ProfileStatus.DEFERRED


# ── T170-MRP-11: CRITICAL with HUMAN-0 ack → CLEAR (MRP-HUMAN0-0) ────────────

def test_T170_MRP_11_critical_with_human0_ack_clear():
    mrp = MutationRiskProfiler(risk_ceiling=0.99)
    proposal = _critical_proposal()
    proposal.human0_acknowledged = True
    rp, record = mrp.profile(proposal)
    assert rp.verdict == RiskVerdict.CRITICAL
    assert record.status == ProfileStatus.CLEAR


# ── T170-MRP-12: low-risk proposal → CLEAR status ────────────────────────────

def test_T170_MRP_12_low_risk_yields_clear_status():
    mrp = MutationRiskProfiler()
    _, record = mrp.profile(_low_risk_proposal())
    assert record.status == ProfileStatus.CLEAR


# ── T170-MRP-13: RiskProfile hash is stable (MRP-SCORE-0) ────────────────────

def test_T170_MRP_13_profile_hash_stable():
    mrp = MutationRiskProfiler()
    proposal = _medium_risk_proposal()
    rp1 = mrp.compute_profile(proposal)
    rp2 = mrp.compute_profile(proposal)
    assert rp1.profile_hash == rp2.profile_hash


# ── T170-MRP-14: HMAC chain starts with zero sentinel ────────────────────────

def test_T170_MRP_14_chain_starts_with_zero_sentinel():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal("P-FIRST"))
    first_record = mrp._registry[0]
    assert first_record.prev_record_hash == "0" * 64


# ── T170-MRP-15: HMAC chain links correctly across multiple records (MRP-CHAIN-0)

def test_T170_MRP_15_hmac_chain_links_correctly():
    mrp = MutationRiskProfiler()
    for i in range(3):
        mrp.profile(_low_risk_proposal(f"P-CHAIN-{i}"))
    for i in range(1, len(mrp._registry)):
        prev = mrp._registry[i - 1]
        curr = mrp._registry[i]
        assert hmac.compare_digest(curr.prev_record_hash[:24], prev.record_hash[:24])


# ── T170-MRP-16: verify_chain passes on clean registry ───────────────────────

def test_T170_MRP_16_verify_chain_passes_clean():
    mrp = MutationRiskProfiler()
    for i in range(5):
        mrp.profile(_low_risk_proposal(f"P-VC-{i}"))
    assert mrp.verify_chain() is True


# ── T170-MRP-17: verify_chain detects tampered record (MRP-CHAIN-0) ──────────

def test_T170_MRP_17_verify_chain_detects_tamper():
    mrp = MutationRiskProfiler()
    for i in range(3):
        mrp.profile(_low_risk_proposal(f"P-TAMP-{i}"))
    # Manually corrupt the second record's hash
    mrp._registry[1] = ProfileRecord(
        record_id=mrp._registry[1].record_id,
        proposal_id=mrp._registry[1].proposal_id,
        verdict=mrp._registry[1].verdict,
        status=mrp._registry[1].status,
        composite_risk=mrp._registry[1].composite_risk,
        prev_record_hash="deadbeef" + "0" * 56,
        reason=mrp._registry[1].reason,
    )
    with pytest.raises(MRPTamperError):
        mrp.verify_chain()


# ── T170-MRP-18: registry is append-only — length monotonically increases ─────

def test_T170_MRP_18_registry_append_only():
    mrp = MutationRiskProfiler()
    lengths = []
    for i in range(4):
        mrp.profile(_low_risk_proposal(f"P-AO-{i}"))
        lengths.append(len(mrp._registry))
    assert lengths == [1, 2, 3, 4]


# ── T170-MRP-19: audit_trail records every profiling event (MRP-AUDIT-0) ─────

def test_T170_MRP_19_audit_trail_populated():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal())
    trail = mrp.audit_trail()
    assert any(e["event"] == "profile_decision" for e in trail)
    assert any(e["event"] == "compute_profile" for e in trail)


# ── T170-MRP-20: audit_trail grows with each call ─────────────────────────────

def test_T170_MRP_20_audit_trail_grows():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal("P-AT-1"))
    count1 = len(mrp.audit_trail())
    mrp.profile(_low_risk_proposal("P-AT-2"))
    count2 = len(mrp.audit_trail())
    assert count2 > count1


# ── T170-MRP-21: RiskProfile.summary() contains required keys ────────────────

def test_T170_MRP_21_profile_summary_keys():
    mrp = MutationRiskProfiler()
    rp = mrp.compute_profile(_low_risk_proposal())
    summary = rp.summary()
    assert "proposal_id" in summary
    assert "composite_risk" in summary
    assert "verdict" in summary
    assert "dimension_breakdown" in summary


# ── T170-MRP-22: dimension_breakdown keys match CANONICAL_DIMENSIONS ──────────

def test_T170_MRP_22_breakdown_has_canonical_dimensions():
    mrp = MutationRiskProfiler()
    rp = mrp.compute_profile(_medium_risk_proposal())
    assert set(rp.dimension_breakdown.keys()) == CANONICAL_DIMENSIONS


# ── T170-MRP-23: all dimension contributions are non-negative (MRP-BLAST-0) ──

def test_T170_MRP_23_no_negative_contributions():
    mrp = MutationRiskProfiler()
    for pid, score in [("P-ZERO", 0.0), ("P-MID", 0.5), ("P-ONE", 1.0)]:
        proposal = MutationProposal(
            proposal_id=pid,
            label="non-neg",
            dimension_scores={d: score for d in CANONICAL_DIMENSIONS},
        )
        rp = mrp.compute_profile(proposal)
        for v in rp.dimension_breakdown.values():
            assert v >= 0.0


# ── T170-MRP-24: custom weights are applied correctly ─────────────────────────

def test_T170_MRP_24_custom_weights_applied():
    # Give blast_exposure all weight; other weights zero
    custom_w = {d: 0.0 for d in CANONICAL_DIMENSIONS}
    custom_w["blast_exposure"] = 1.0
    mrp = MutationRiskProfiler(weights=custom_w)
    proposal = MutationProposal(
        proposal_id="P-CW",
        label="custom-weight",
        dimension_scores={d: (1.0 if d == "blast_exposure" else 0.0) for d in CANONICAL_DIMENSIONS},
    )
    rp = mrp.compute_profile(proposal)
    # Only blast_exposure matters; score should be ~1.0
    assert rp.composite_risk > 0.9


# ── T170-MRP-25: custom weights with unknown dimension rejected (MRP-DIM-0) ──

def test_T170_MRP_25_custom_weights_unknown_dim_rejected():
    with pytest.raises(MRPDimensionError):
        MutationRiskProfiler(weights={"ghost_dim": 0.5})


# ── T170-MRP-26: registry() returns serialisable list ────────────────────────

def test_T170_MRP_26_registry_returns_serialisable():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal("P-SER"))
    reg = mrp.registry()
    assert isinstance(reg, list)
    assert len(reg) == 1
    rec = reg[0]
    assert "proposal_id" in rec
    assert "verdict" in rec
    assert "composite_risk" in rec
    assert "record_hash" in rec


# ── T170-MRP-27: stats() returns expected keys ────────────────────────────────

def test_T170_MRP_27_stats_keys():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal())
    stats = mrp.stats()
    assert "total_profiled" in stats
    assert "by_verdict" in stats
    assert "clear" in stats
    assert "risk_ceiling" in stats
    assert stats["total_profiled"] == 1


# ── T170-MRP-28: highest_risk_record returns None on empty registry ───────────

def test_T170_MRP_28_highest_risk_record_empty():
    mrp = MutationRiskProfiler()
    assert mrp.highest_risk_record() is None


# ── T170-MRP-29: highest_risk_record identifies peak record ───────────────────

def test_T170_MRP_29_highest_risk_record_correct():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal("P-PEAK-LOW"))
    # Medium risk
    med = MutationProposal(
        proposal_id="P-PEAK-MED",
        label="med",
        dimension_scores={d: 0.55 for d in CANONICAL_DIMENSIONS},
    )
    mrp.profile(med)
    peak = mrp.highest_risk_record()
    assert peak is not None
    assert peak["proposal_id"] == "P-PEAK-MED"


# ── T170-MRP-30: ProfileRecord HMAC uses HMAC_SECRET (MRP-CHAIN-0) ────────────

def test_T170_MRP_30_record_hmac_uses_secret():
    mrp = MutationRiskProfiler()
    mrp.profile(_low_risk_proposal("P-HMAC"))
    record = mrp._registry[0]
    # Reconstruct expected hash using HMAC_SECRET
    payload = (
        f"{record.record_id}|{record.proposal_id}|{record.verdict.value}|"
        f"{record.status.value}|{record.composite_risk:.6f}|"
        f"{record.prev_record_hash}"
    ).encode()
    expected = hmac.new(HMAC_SECRET, payload, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(record.record_hash[:24], expected[:24])
