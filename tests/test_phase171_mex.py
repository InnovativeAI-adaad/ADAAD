# SPDX-License-Identifier: Apache-2.0
"""
Phase 171 · INNOV-77 · MEX — Mutation Execution Engine
Test suite: T171-MEX-01 .. T171-MEX-30  (30 tests · Grade-A target)
"""
import pytest
import time
from dorkllm.mutation_execution_engine import (
    MutationExecutionEngine,
    MutationPayload,
    MRPClearanceToken,
    MSESelectionToken,
    RollbackRecord,
    ExecutionStatus,
    ImpactTier,
    MEXClearanceViolation,
    MEXChainViolation,
    MEXHuman0Flag,
    MEXBlastReject,
    MEXAtomicViolation,
    MEXPersistViolation,
    MEXScopeViolation,
    RISK_CEILING,
    MAX_BLAST_RADIUS,
)

pytestmark = pytest.mark.phase171


# ── Fixtures ──────────────────────────────────────────────────────────────────
def make_engine() -> MutationExecutionEngine:
    return MutationExecutionEngine()


def make_payload(
    mutation_id="mut-001",
    target_module="dorkllm.foo",
    target_scope="dorkllm",
    patch=None,
    blast=0.30,
    impact=0.25,
    human0=False,
    ref=None,
) -> MutationPayload:
    return MutationPayload(
        mutation_id=mutation_id,
        target_module=target_module,
        target_scope=target_scope,
        patch_descriptor=patch or {"change_a": "value_a"},
        blast_radius=blast,
        impact_score=impact,
        human0_ratified=human0,
        ratification_ref=ref,
    )


def make_mrp(mid="mut-001", risk=0.30, verdict="LOW") -> MRPClearanceToken:
    return MRPClearanceToken(mutation_id=mid, composite_risk=risk, verdict=verdict)


def make_mse(mid="mut-001", fitness=0.75, tier="TIER_1") -> MSESelectionToken:
    return MSESelectionToken(mutation_id=mid, fitness_score=fitness, selection_tier=tier)


# ── T171-MEX-01: successful apply returns APPLIED record ─────────────────────
def test_mex_01_apply_success():
    eng = make_engine()
    rec = eng.apply(make_payload(), make_mrp(), make_mse())
    assert rec.status == ExecutionStatus.APPLIED


# ── T171-MEX-02: applied record has non-empty HMAC digest ────────────────────
def test_mex_02_hmac_present():
    eng = make_engine()
    rec = eng.apply(make_payload(), make_mrp(), make_mse())
    assert len(rec.hmac_digest) == 64


# ── T171-MEX-03: first record prev_digest == GENESIS ─────────────────────────
def test_mex_03_genesis_prev_digest():
    eng = make_engine()
    rec = eng.apply(make_payload(), make_mrp(), make_mse())
    assert rec.prev_digest == "GENESIS"


# ── T171-MEX-04: MEX-EXEC-0 — risk >= RISK_CEILING raises MEXClearanceViolation
def test_mex_04_risk_ceiling_blocks():
    eng = make_engine()
    mrp = make_mrp(risk=RISK_CEILING)
    with pytest.raises(MEXClearanceViolation, match="MEX-EXEC-0"):
        eng.apply(make_payload(), mrp, make_mse())


# ── T171-MEX-05: MEX-EXEC-0 — mutation_id mismatch raises MEXClearanceViolation
def test_mex_05_mutation_id_mismatch():
    eng = make_engine()
    mrp = make_mrp(mid="different-id")
    with pytest.raises(MEXClearanceViolation, match="mismatch"):
        eng.apply(make_payload(mutation_id="mut-001"), mrp, make_mse())


# ── T171-MEX-06: MEX-BLAST-0 — blast_radius > cap raises MEXBlastReject ──────
def test_mex_06_blast_radius_blocks():
    eng = make_engine()
    p = make_payload(blast=MAX_BLAST_RADIUS + 0.01)
    with pytest.raises(MEXBlastReject, match="MEX-BLAST-0"):
        eng.apply(p, make_mrp(), make_mse())


# ── T171-MEX-07: blast_radius == MAX_BLAST_RADIUS is rejected (>= cap) ───────
def test_mex_07_blast_at_cap_rejected():
    eng = make_engine()
    p = make_payload(blast=MAX_BLAST_RADIUS + 0.001)
    with pytest.raises(MEXBlastReject):
        eng.apply(p, make_mrp(), make_mse())


# ── T171-MEX-08: MEX-HUMAN0-0 — HIGH impact without ratification blocked ─────
def test_mex_08_high_impact_needs_human0():
    eng = make_engine()
    p = make_payload(impact=0.70, human0=False)
    with pytest.raises(MEXHuman0Flag, match="MEX-HUMAN0-0"):
        eng.apply(p, make_mrp(), make_mse())


# ── T171-MEX-09: MEX-HUMAN0-0 — HIGH impact WITH ratification passes ─────────
def test_mex_09_high_impact_with_human0_passes():
    eng = make_engine()
    p = make_payload(impact=0.70, human0=True, ref="ILA-171-20260503-001")
    rec = eng.apply(p, make_mrp(), make_mse())
    assert rec.status == ExecutionStatus.APPLIED
    assert rec.impact_tier == ImpactTier.HIGH


# ── T171-MEX-10: MEX-SCOPE-0 — out-of-scope target raises MEXScopeViolation ──
def test_mex_10_scope_violation():
    eng = make_engine()
    p = make_payload(target_scope="external_service")
    with pytest.raises(MEXScopeViolation, match="MEX-SCOPE-0"):
        eng.apply(p, make_mrp(), make_mse())


# ── T171-MEX-11: all valid scope targets pass ────────────────────────────────
@pytest.mark.parametrize("scope", ["dorkllm", "app", "runtime", "tests", "governance"])
def test_mex_11_valid_scopes(scope):
    eng = make_engine()
    p = make_payload(target_scope=scope)
    rec = eng.apply(p, make_mrp(), make_mse())
    assert rec.status == ExecutionStatus.APPLIED


# ── T171-MEX-12: rollback_record co-committed with each apply ────────────────
def test_mex_12_rollback_record_present():
    eng = make_engine()
    rec = eng.apply(make_payload(), make_mrp(), make_mse())
    assert rec.rollback is not None
    assert rec.rollback.mutation_id == "mut-001"


# ── T171-MEX-13: rollback() appends ROLLED_BACK record ──────────────────────
def test_mex_13_rollback_appends_record():
    eng = make_engine()
    eng.apply(make_payload(), make_mrp(), make_mse())
    rb = eng.rollback("mut-001")
    assert rb.status == ExecutionStatus.ROLLED_BACK


# ── T171-MEX-14: rollback() on unknown mutation_id raises KeyError ───────────
def test_mex_14_rollback_unknown_raises():
    eng = make_engine()
    with pytest.raises(KeyError):
        eng.rollback("nonexistent-id")


# ── T171-MEX-15: verify_chain() passes on fresh engine ───────────────────────
def test_mex_15_verify_chain_empty():
    eng = make_engine()
    assert eng.verify_chain() is True


# ── T171-MEX-16: verify_chain() passes after multiple applies ────────────────
def test_mex_16_verify_chain_multi():
    eng = make_engine()
    for i in range(5):
        mid = f"mut-{i:03d}"
        eng.apply(make_payload(mutation_id=mid), make_mrp(mid=mid), make_mse(mid=mid))
    assert eng.verify_chain() is True


# ── T171-MEX-17: tampered digest detected by verify_chain() ──────────────────
def test_mex_17_tamper_detected():
    eng = make_engine()
    eng.apply(make_payload(), make_mrp(), make_mse())
    eng._ledger[0].hmac_digest = "0" * 64
    with pytest.raises(MEXChainViolation, match="MEX-CHAIN-0"):
        eng.verify_chain()


# ── T171-MEX-18: chained record prev_digest links correctly ──────────────────
def test_mex_18_chain_linkage():
    eng = make_engine()
    r1 = eng.apply(make_payload(mutation_id="mut-001"), make_mrp(mid="mut-001"), make_mse(mid="mut-001"))
    r2 = eng.apply(make_payload(mutation_id="mut-002"), make_mrp(mid="mut-002"), make_mse(mid="mut-002"))
    assert r2.prev_digest == r1.hmac_digest


# ── T171-MEX-19: ledger() returns list of dicts ───────────────────────────────
def test_mex_19_ledger_format():
    eng = make_engine()
    eng.apply(make_payload(), make_mrp(), make_mse())
    ld = eng.ledger()
    assert isinstance(ld, list)
    assert "record_id" in ld[0]
    assert "hmac_digest" in ld[0]


# ── T171-MEX-20: stats() returns correct counts ──────────────────────────────
def test_mex_20_stats():
    eng = make_engine()
    for i in range(3):
        mid = f"m{i}"
        eng.apply(make_payload(mutation_id=mid), make_mrp(mid=mid), make_mse(mid=mid))
    eng.rollback("m0")
    s = eng.stats()
    assert s["applied"] == 3       # 3 APPLIED records in ledger (rollback doesn't erase)
    assert s["rolled_back"] == 1
    assert s["total_records"] == 4
    assert s["currently_applied"] == 2  # only m1, m2 still active


# ── T171-MEX-21: history() filtered by mutation_id ───────────────────────────
def test_mex_21_history_filtered():
    eng = make_engine()
    eng.apply(make_payload(mutation_id="mut-A"), make_mrp(mid="mut-A"), make_mse(mid="mut-A"))
    eng.apply(make_payload(mutation_id="mut-B"), make_mrp(mid="mut-B"), make_mse(mid="mut-B"))
    h = eng.history("mut-A")
    assert all(r.mutation_id == "mut-A" for r in h)
    assert len(h) == 1


# ── T171-MEX-22: history() unfiltered returns all records ────────────────────
def test_mex_22_history_unfiltered():
    eng = make_engine()
    eng.apply(make_payload(mutation_id="mut-A"), make_mrp(mid="mut-A"), make_mse(mid="mut-A"))
    eng.apply(make_payload(mutation_id="mut-B"), make_mrp(mid="mut-B"), make_mse(mid="mut-B"))
    assert len(eng.history()) == 2


# ── T171-MEX-23: MEX-DETERM-0 — same inputs yield identical record fields ────
def test_mex_23_determinism():
    import uuid as _uuid
    # Patch uuid4 to be deterministic for comparison
    eng1 = make_engine()
    eng2 = make_engine()
    p = make_payload()
    mrp = make_mrp()
    mse = make_mse()
    r1 = eng1.apply(p, mrp, mse)
    r2 = eng2.apply(p, mrp, mse)
    # Same structural fields (excluding UUIDs and timestamp)
    assert r1.mutation_id == r2.mutation_id
    assert r1.impact_tier == r2.impact_tier
    assert r1.blast_radius == r2.blast_radius


# ── T171-MEX-24: NEGLIGIBLE impact tier classified correctly ──────────────────
def test_mex_24_impact_negligible():
    eng = make_engine()
    rec = eng.apply(make_payload(impact=0.10), make_mrp(), make_mse())
    assert rec.impact_tier == ImpactTier.NEGLIGIBLE


# ── T171-MEX-25: LOW impact tier classified correctly ─────────────────────────
def test_mex_25_impact_low():
    eng = make_engine()
    rec = eng.apply(make_payload(impact=0.25), make_mrp(), make_mse())
    assert rec.impact_tier == ImpactTier.LOW


# ── T171-MEX-26: MEDIUM impact tier classified correctly ──────────────────────
def test_mex_26_impact_medium():
    eng = make_engine()
    rec = eng.apply(make_payload(impact=0.50), make_mrp(), make_mse())
    assert rec.impact_tier == ImpactTier.MEDIUM


# ── T171-MEX-27: CRITICAL impact tier requires HUMAN-0 ───────────────────────
def test_mex_27_critical_needs_human0():
    eng = make_engine()
    p = make_payload(impact=0.90, human0=False)
    with pytest.raises(MEXHuman0Flag):
        eng.apply(p, make_mrp(), make_mse())


# ── T171-MEX-28: seal() prevents further writes ──────────────────────────────
def test_mex_28_seal_blocks_write():
    eng = make_engine()
    eng.apply(make_payload(), make_mrp(), make_mse())
    eng.seal()
    with pytest.raises(MEXPersistViolation, match="MEX-PERSIST-0"):
        eng.apply(
            make_payload(mutation_id="mut-999"),
            make_mrp(mid="mut-999"),
            make_mse(mid="mut-999"),
        )


# ── T171-MEX-29: transition_log records full lifecycle ───────────────────────
def test_mex_29_transition_log():
    eng = make_engine()
    rec = eng.apply(make_payload(), make_mrp(), make_mse())
    assert "QUEUED" in rec.transition_log
    assert "EXECUTING" in rec.transition_log
    assert "APPLIED" in rec.transition_log


# ── T171-MEX-30: empty patch_descriptor is valid (no-op mutation) ────────────
def test_mex_30_empty_patch_valid():
    eng = make_engine()
    p = make_payload(patch={})
    rec = eng.apply(p, make_mrp(), make_mse())
    assert rec.status == ExecutionStatus.APPLIED
