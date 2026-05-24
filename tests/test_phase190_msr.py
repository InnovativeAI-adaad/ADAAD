"""
Phase 190 · INNOV-95 · MSR test suite — 30 tests
Covers: routing correctness, chain integrity, HUMAN-0 gate,
        scope enforcement, atomic failure, factory/helper API.
"""

import hmac as _hmac
import hashlib
import time
import uuid
import pytest

from runtime.innovations30.mutation_strategy_router import (
    BlastRadius,
    DispatchOutcome,
    MutationStrategyRouter,
    SignalVector,
    StrategyDescriptor,
    StrategyTier,
    INVARIANTS,
    HARD_CLASS,
    make_router,
    make_signal,
)

pytestmark = pytest.mark.phase190


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def router():
    return MutationStrategyRouter(secret=b"test-secret")


@pytest.fixture
def low_signal():
    return SignalVector("mut-001", 0.2, BlastRadius.LOCAL)


@pytest.fixture
def mid_signal():
    return SignalVector("mut-002", 0.6, BlastRadius.MODULE)


@pytest.fixture
def critical_signal():
    return SignalVector("mut-003", 0.9, BlastRadius.GLOBAL, requires_human0=True)


# ── T190-MSR-01 to 05: Invariant registry ────────────────────────────────────

def test_T190_MSR_01_invariants_present():
    assert "MSR-ROUTE-0" in INVARIANTS

def test_T190_MSR_02_invariant_chain():
    assert "MSR-CHAIN-0" in INVARIANTS

def test_T190_MSR_03_invariant_human0():
    assert "MSR-HUMAN0-0" in INVARIANTS

def test_T190_MSR_04_invariant_scope():
    assert "MSR-SCOPE-0" in INVARIANTS

def test_T190_MSR_05_invariant_atomic():
    assert "MSR-ATOMIC-0" in INVARIANTS and HARD_CLASS == "Hard"


# ── T190-MSR-06 to 10: Strategy selection ────────────────────────────────────

def test_T190_MSR_06_low_entropy_routes_incremental(router, low_signal):
    s = router.select_strategy(low_signal)
    assert s.name == "incremental"

def test_T190_MSR_07_mid_entropy_routes_staged(router, mid_signal):
    s = router.select_strategy(mid_signal)
    assert s.name == "staged_rollout"

def test_T190_MSR_08_critical_entropy_routes_review(router):
    sig = SignalVector("mut-x", 0.85, BlastRadius.LOCAL)
    s = router.select_strategy(sig)
    assert s.name == "constitutional_review"

def test_T190_MSR_09_human0_flag_routes_review(router, critical_signal):
    s = router.select_strategy(critical_signal)
    assert s.name == "constitutional_review"

def test_T190_MSR_10_global_scope_routes_staged(router):
    sig = SignalVector("mut-g", 0.3, BlastRadius.GLOBAL)
    s = router.select_strategy(sig)
    assert s.name == "staged_rollout"


# ── T190-MSR-11 to 15: Dispatch outcomes ─────────────────────────────────────

def test_T190_MSR_11_incremental_dispatch_succeeds(router, low_signal):
    rec = router.dispatch(low_signal)
    assert rec.outcome == DispatchOutcome.DISPATCHED

def test_T190_MSR_12_staged_dispatch_succeeds(router):
    sig = SignalVector("mut-s", 0.55, BlastRadius.SUBSYSTEM)
    rec = router.dispatch(sig)
    assert rec.outcome == DispatchOutcome.DISPATCHED

def test_T190_MSR_13_critical_blocked_without_approval(router, critical_signal):
    rec = router.dispatch(critical_signal)
    assert rec.outcome == DispatchOutcome.BLOCKED

def test_T190_MSR_14_critical_dispatched_after_approval(router, critical_signal):
    router.approve_human0(critical_signal.mutation_id)
    rec = router.dispatch(critical_signal)
    assert rec.outcome == DispatchOutcome.DISPATCHED

def test_T190_MSR_15_record_seeded_in_ledger(router, low_signal):
    router.dispatch(low_signal)
    assert router.ledger_depth == 1


# ── T190-MSR-16 to 20: HMAC chain integrity ──────────────────────────────────

def test_T190_MSR_16_chain_valid_after_single_dispatch(router, low_signal):
    router.dispatch(low_signal)
    assert router.verify_chain()

def test_T190_MSR_17_chain_valid_after_multiple_dispatches(router):
    for i in range(5):
        sig = SignalVector(f"mut-{i}", 0.1 * i, BlastRadius.LOCAL)
        router.dispatch(sig)
    assert router.verify_chain()

def test_T190_MSR_18_chain_links_prev_hmac(router):
    sig1 = SignalVector("m1", 0.1, BlastRadius.LOCAL)
    sig2 = SignalVector("m2", 0.2, BlastRadius.LOCAL)
    r1 = router.dispatch(sig1)
    r2 = router.dispatch(sig2)
    assert r2.prev_hmac == r1.hmac

def test_T190_MSR_19_genesis_prev_hmac_on_first_record(router, low_signal):
    rec = router.dispatch(low_signal)
    assert rec.prev_hmac == "genesis"

def test_T190_MSR_20_tampered_chain_fails_verification(router, low_signal):
    router.dispatch(low_signal)
    router._ledger[0].hmac = "deadbeef" * 8
    assert not router.verify_chain()


# ── T190-MSR-21 to 24: MSR-SCOPE-0 enforcement ───────────────────────────────

def test_T190_MSR_21_scope_blocked_when_exceeds_strategy(router):
    # incremental strategy max_scope=MODULE; SUBSYSTEM should be blocked
    # Force incremental selection by low entropy, but set scope to SUBSYSTEM
    # Actually select_strategy will route to staged_rollout for SUBSYSTEM,
    # so use a custom low-scope strategy and override
    router.register_strategy(StrategyDescriptor(
        name="narrow",
        tier=StrategyTier.ROUTINE,
        max_scope=BlastRadius.LOCAL,
        handler=lambda s: DispatchOutcome.DISPATCHED,
    ))
    # Directly test scope guard by patching select_strategy
    original = router.select_strategy
    router.select_strategy = lambda _: router._strategies["narrow"]
    sig = SignalVector("mut-scope", 0.1, BlastRadius.MODULE)
    rec = router.dispatch(sig)
    router.select_strategy = original
    assert rec.outcome == DispatchOutcome.BLOCKED

def test_T190_MSR_22_scope_allowed_within_max(router, low_signal):
    rec = router.dispatch(low_signal)
    assert rec.outcome != DispatchOutcome.BLOCKED or rec.outcome == DispatchOutcome.DISPATCHED

def test_T190_MSR_23_scope_rank_ordering():
    rank = MutationStrategyRouter._SCOPE_RANK
    assert rank[BlastRadius.LOCAL] < rank[BlastRadius.MODULE] < rank[BlastRadius.SUBSYSTEM] < rank[BlastRadius.GLOBAL]

def test_T190_MSR_24_global_scope_critical_blocked_without_h0(router):
    sig = SignalVector("mut-gc", 0.95, BlastRadius.GLOBAL, requires_human0=True)
    rec = router.dispatch(sig)
    assert rec.outcome == DispatchOutcome.BLOCKED


# ── T190-MSR-25 to 27: MSR-ATOMIC-0 ─────────────────────────────────────────

def test_T190_MSR_25_atomic_rollback_on_handler_exception(router):
    def exploding(sig):
        raise RuntimeError("handler exploded")
    router.register_strategy(StrategyDescriptor(
        name="bomb",
        tier=StrategyTier.ROUTINE,
        max_scope=BlastRadius.GLOBAL,
        handler=exploding,
    ))
    router.select_strategy = lambda _: router._strategies["bomb"]
    depth_before = router.ledger_depth
    sig = SignalVector("mut-boom", 0.1, BlastRadius.LOCAL)
    rec = router.dispatch(sig)
    # The rolled-back record is still appended (it's the failure record)
    assert rec.outcome == DispatchOutcome.ROLLED_BACK

def test_T190_MSR_26_chain_still_valid_after_rollback(router):
    def exploding(sig):
        raise RuntimeError("boom")
    router.register_strategy(StrategyDescriptor(
        name="bomb2", tier=StrategyTier.ROUTINE, max_scope=BlastRadius.GLOBAL, handler=exploding
    ))
    router.select_strategy = lambda _: router._strategies["bomb2"]
    router.dispatch(SignalVector("mut-b2", 0.1, BlastRadius.LOCAL))
    assert router.verify_chain()

def test_T190_MSR_27_ledger_immutable_after_copy(router, low_signal):
    router.dispatch(low_signal)
    snap = router.ledger
    router.dispatch(SignalVector("mut-x", 0.1, BlastRadius.LOCAL))
    assert len(snap) == 1  # original snapshot unchanged


# ── T190-MSR-28 to 30: Factory / helper API ──────────────────────────────────

def test_T190_MSR_28_make_router_returns_instance():
    r = make_router(secret=b"s")
    assert isinstance(r, MutationStrategyRouter)

def test_T190_MSR_29_make_signal_constructs_correctly():
    sig = make_signal("m", 0.5, BlastRadius.MODULE, requires_human0=False, tag="v1")
    assert sig.mutation_id == "m" and sig.metadata["tag"] == "v1"

def test_T190_MSR_30_signal_entropy_bounds_enforced():
    with pytest.raises(ValueError):
        SignalVector("bad", 1.5, BlastRadius.LOCAL)
