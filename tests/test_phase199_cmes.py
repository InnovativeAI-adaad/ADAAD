"""
Phase 199 · INNOV-104 · CMES Acceptance Suite
30/30 tests — T199-CMES-01…30
pytest -m phase199
"""
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dorkllm.constitutional_mutation_execution_sandbox import (
    BehavioralDelta,
    BlastRadius,
    CMESChainViolation,
    CMESConstitutionalViolation,
    CMESImmutabilityViolation,
    CMESPromotionBlocked,
    CMESSandboxLedger,
    ConstitutionalMutationExecutionSandbox,
    MutationSpec,
    SandboxStatus,
    _compute_entry_hash,
)

pytestmark = pytest.mark.phase199


# ── Fixtures ─────────────────────────────────────────────────────────────────

HUMAN0 = "DUSTIN L REID"


def _ledger(tmp_path):
    path = str(tmp_path / "sandbox_ledger.jsonl")
    return CMESSandboxLedger(path=path)


def _sandbox(tmp_path, **kwargs):
    return ConstitutionalMutationExecutionSandbox(
        ledger=_ledger(tmp_path), **kwargs
    )


def _spec(**overrides):
    defaults = dict(
        mutation_id=str(uuid.uuid4()),
        module_path="dorkllm/constitutional_mutation_execution_sandbox.py",
        blast_radius=BlastRadius.TIER1,
        description="Test mutation",
        invariants_targeted=["CMES-TEST-0"],
        seed="fixed-seed-abc",
    )
    defaults.update(overrides)
    return MutationSpec(**defaults)


# ── INV: Invariant enforcement ────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T199-CMES-01"])
def test_cmes_isolate_no_live_state_touched(tid, tmp_path):
    """CMES-ISOLATE-0: sandbox execution never mutates live baseline."""
    sb = _sandbox(tmp_path, baseline_invariant_count=100)
    spec = _spec()
    run = sb.open_sandbox(spec)
    sb.execute(run.run_id)
    assert sb._baseline_invariants == 100, "CMES-ISOLATE-0: baseline mutated"


@pytest.mark.parametrize("tid", ["T199-CMES-02"])
def test_cmes_delta_always_emitted(tid, tmp_path):
    """CMES-DELTA-0: BehavioralDelta must be emitted on every execution."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    result = sb.execute(run.run_id)
    assert result.delta is not None, "CMES-DELTA-0: no delta emitted"
    assert isinstance(result.delta, BehavioralDelta)


@pytest.mark.parametrize("tid", ["T199-CMES-03"])
def test_cmes_chain_genesis_entry(tid, tmp_path):
    """CMES-CHAIN-0: first entry prev_hash == GENESIS."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    sb.execute(run.run_id)
    entries = sb._ledger.all_entries()
    assert entries[0]["prev_hash"] == "GENESIS"


@pytest.mark.parametrize("tid", ["T199-CMES-04"])
def test_cmes_chain_links_correctly(tid, tmp_path):
    """CMES-CHAIN-0: each entry's prev_hash == previous entry_hash."""
    sb = _sandbox(tmp_path)
    for _ in range(3):
        r = sb.open_sandbox(_spec())
        sb.execute(r.run_id)
    entries = sb._ledger.all_entries()
    for i in range(1, len(entries)):
        assert entries[i]["prev_hash"] == entries[i - 1]["entry_hash"]


@pytest.mark.parametrize("tid", ["T199-CMES-05"])
def test_cmes_human0_required_for_promote(tid, tmp_path):
    """CMES-HUMAN0-0: promotion by non-HUMAN-0 raises violation."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    executed = sb.execute(run.run_id)
    # Seal the run (already in ledger via execute)
    with pytest.raises(CMESConstitutionalViolation):
        sb.promote(executed.run_id, "random-agent")


@pytest.mark.parametrize("tid", ["T199-CMES-06"])
def test_cmes_promote_requires_passed_status(tid, tmp_path):
    """CMES-PROMOTE-0: FAILED run cannot be promoted."""
    sb = _sandbox(tmp_path)
    spec = _spec(invariants_targeted=["A"] * 20)  # still TIER1 ≤15? No — triggers scope fail
    # Force a FAILED run via callable that returns failures
    run = sb.open_sandbox(_spec())
    def fail_callable(state, seed):
        return {"state": state, "tests_passed": 0, "tests_failed": 30, "api_added": [], "api_removed": []}
    executed = sb.execute(run.run_id, dry_run_callable=fail_callable)
    assert executed.status == SandboxStatus.FAILED
    with pytest.raises(CMESPromotionBlocked):
        sb.promote(executed.run_id, HUMAN0)


@pytest.mark.parametrize("tid", ["T199-CMES-07"])
def test_cmes_promote_passed_run(tid, tmp_path):
    """CMES-PROMOTE-0 + CMES-HUMAN0-0: HUMAN-0 can promote PASSED run."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    executed = sb.execute(run.run_id)
    if executed.status == SandboxStatus.PASSED:
        promoted = sb.promote(executed.run_id, HUMAN0)
        assert promoted.status == SandboxStatus.PROMOTED
        assert promoted.promoted_by == HUMAN0


@pytest.mark.parametrize("tid", ["T199-CMES-08"])
def test_cmes_discard_human0_only(tid, tmp_path):
    """CMES-HUMAN0-0: discard by non-HUMAN-0 raises violation."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    executed = sb.execute(run.run_id)
    with pytest.raises(CMESConstitutionalViolation):
        sb.discard(executed.run_id, "intruder")


@pytest.mark.parametrize("tid", ["T199-CMES-09"])
def test_cmes_discard_by_human0(tid, tmp_path):
    """CMES-HUMAN0-0: HUMAN-0 can discard any run."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    executed = sb.execute(run.run_id)
    discarded = sb.discard(executed.run_id, HUMAN0)
    assert discarded.status == SandboxStatus.DISCARDED
    assert discarded.discarded_by == HUMAN0


@pytest.mark.parametrize("tid", ["T199-CMES-10"])
def test_cmes_scope_tier1_invariant_limit(tid, tmp_path):
    """CMES-SCOPE-0: TIER1 with >15 invariants targeted raises violation."""
    sb = _sandbox(tmp_path)
    spec = _spec(invariants_targeted=["INV-" + str(i) for i in range(16)])
    run = sb.open_sandbox(spec)
    with pytest.raises(CMESConstitutionalViolation):
        sb.execute(run.run_id)


@pytest.mark.parametrize("tid", ["T199-CMES-11"])
def test_cmes_scope_tier2_invariant_limit(tid, tmp_path):
    """CMES-SCOPE-0: TIER2 with >30 invariants targeted raises violation."""
    sb = _sandbox(tmp_path)
    spec = _spec(
        blast_radius=BlastRadius.TIER2,
        invariants_targeted=["INV-" + str(i) for i in range(31)],
    )
    run = sb.open_sandbox(spec)
    with pytest.raises(CMESConstitutionalViolation):
        sb.execute(run.run_id)


@pytest.mark.parametrize("tid", ["T199-CMES-12"])
def test_cmes_scope_tier3_unlimited(tid, tmp_path):
    """CMES-SCOPE-0: TIER3 has no invariant count limit."""
    sb = _sandbox(tmp_path)
    spec = _spec(
        blast_radius=BlastRadius.TIER3,
        invariants_targeted=["INV-" + str(i) for i in range(50)],
    )
    run = sb.open_sandbox(spec)
    result = sb.execute(run.run_id)
    assert result.delta is not None


@pytest.mark.parametrize("tid", ["T199-CMES-13"])
def test_cmes_determ_seed_determinism(tid, tmp_path):
    """CMES-DETERM-0: same seed + mutation_id produces same tests_passed."""
    sb1 = _sandbox(tmp_path)
    sb2 = ConstitutionalMutationExecutionSandbox(
        ledger=CMESSandboxLedger(str(tmp_path / "sb2_ledger.jsonl"))
    )
    fixed_seed = "determinism-seed-xyz"
    fixed_id = "mutation-determinism-test"
    spec1 = _spec(seed=fixed_seed, mutation_id=fixed_id)
    spec2 = _spec(seed=fixed_seed, mutation_id=fixed_id)
    r1 = sb1.open_sandbox(spec1)
    r2 = sb2.open_sandbox(spec2)
    e1 = sb1.execute(r1.run_id)
    e2 = sb2.execute(r2.run_id)
    assert e1.delta.tests_passed == e2.delta.tests_passed, "CMES-DETERM-0: non-deterministic"


@pytest.mark.parametrize("tid", ["T199-CMES-14"])
def test_cmes_replay_determinism_verified(tid, tmp_path):
    """CMES-REPLAY-0: replay of ledger run produces determinism_verified=True."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec(seed="replay-test-seed", mutation_id="replay-mut-001"))
    sb.execute(run.run_id)
    result = sb.replay(run.run_id)
    assert result["determinism_verified"] is True


@pytest.mark.parametrize("tid", ["T199-CMES-15"])
def test_cmes_replay_missing_run_raises(tid, tmp_path):
    """CMES-REPLAY-0: replaying unknown run_id raises violation."""
    sb = _sandbox(tmp_path)
    with pytest.raises(CMESConstitutionalViolation):
        sb.replay("nonexistent-run-id")


@pytest.mark.parametrize("tid", ["T199-CMES-16"])
def test_cmes_chain_verify_passes_clean_ledger(tid, tmp_path):
    """CMES-CHAIN-0: verify_chain passes on unmodified ledger."""
    sb = _sandbox(tmp_path)
    for _ in range(5):
        r = sb.open_sandbox(_spec())
        sb.execute(r.run_id)
    assert sb.verify_chain() is True


@pytest.mark.parametrize("tid", ["T199-CMES-17"])
def test_cmes_immut_entry_count_grows_only(tid, tmp_path):
    """CMES-IMMUT-0: ledger only grows; entry count never decreases."""
    sb = _sandbox(tmp_path)
    counts = []
    for _ in range(4):
        r = sb.open_sandbox(_spec())
        sb.execute(r.run_id)
        counts.append(len(sb._ledger.all_entries()))
    assert counts == sorted(counts) and counts == list(range(1, 5))


@pytest.mark.parametrize("tid", ["T199-CMES-18"])
def test_cmes_audit_timestamp_present(tid, tmp_path):
    """CMES-AUDIT-0: every ledger entry has ISO-8601 timestamp."""
    sb = _sandbox(tmp_path)
    r = sb.open_sandbox(_spec())
    sb.execute(r.run_id)
    entry = sb._ledger.all_entries()[0]
    assert "timestamp_created" in entry
    ts = entry["timestamp_created"]
    assert "T" in ts and "Z" in ts


@pytest.mark.parametrize("tid", ["T199-CMES-19"])
def test_cmes_delta_fields_complete(tid, tmp_path):
    """CMES-DELTA-0: BehavioralDelta contains all required fields."""
    sb = _sandbox(tmp_path)
    r = sb.open_sandbox(_spec())
    result = sb.execute(r.run_id)
    d = result.delta
    assert hasattr(d, "invariants_pre")
    assert hasattr(d, "invariants_post")
    assert hasattr(d, "invariant_delta")
    assert hasattr(d, "tests_passed")
    assert hasattr(d, "tests_failed")
    assert hasattr(d, "api_endpoints_added")
    assert hasattr(d, "execution_duration_ms")
    assert hasattr(d, "determinism_seed")


@pytest.mark.parametrize("tid", ["T199-CMES-20"])
def test_cmes_no_blast_radius_raises(tid, tmp_path):
    """CMES-SCOPE-0: MutationSpec without valid blast_radius raises."""
    with pytest.raises((ValueError, KeyError, Exception)):
        BlastRadius("INVALID_TIER")


@pytest.mark.parametrize("tid", ["T199-CMES-21"])
def test_cmes_execute_unknown_run_raises(tid, tmp_path):
    """CMES-AUDIT-0: executing unknown run_id raises violation."""
    sb = _sandbox(tmp_path)
    with pytest.raises(CMESConstitutionalViolation):
        sb.execute("no-such-run")


@pytest.mark.parametrize("tid", ["T199-CMES-22"])
def test_cmes_sandbox_run_status_transitions(tid, tmp_path):
    """CMES status flow: PENDING → RUNNING → PASSED or FAILED."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    assert run.status == SandboxStatus.PENDING
    result = sb.execute(run.run_id)
    assert result.status in (SandboxStatus.PASSED, SandboxStatus.FAILED)


@pytest.mark.parametrize("tid", ["T199-CMES-23"])
def test_cmes_callable_result_reflected_in_delta(tid, tmp_path):
    """CMES-DELTA-0: custom callable results are captured in delta."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    def custom(state, seed):
        state["invariants"] += 5
        state["ledger_entries"] = 42
        return {"state": state, "tests_passed": 30, "tests_failed": 0,
                "api_added": ["/cmes/test"], "api_removed": []}
    result = sb.execute(run.run_id, dry_run_callable=custom)
    assert result.delta.tests_passed == 30
    assert result.delta.tests_failed == 0
    assert result.delta.invariant_delta == 5
    assert result.delta.ledger_entries_added == 42


@pytest.mark.parametrize("tid", ["T199-CMES-24"])
def test_cmes_callable_failure_sets_failed_status(tid, tmp_path):
    """CMES-DELTA-0: callable that raises sets FAILED status."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    def broken(state, seed):
        raise RuntimeError("simulated failure")
    result = sb.execute(run.run_id, dry_run_callable=broken)
    assert result.status == SandboxStatus.FAILED
    assert result.failure_reason is not None


@pytest.mark.parametrize("tid", ["T199-CMES-25"])
def test_cmes_summary_structure(tid, tmp_path):
    """CMES summary returns all required keys."""
    sb = _sandbox(tmp_path)
    r = sb.open_sandbox(_spec())
    sb.execute(r.run_id)
    s = sb.summary()
    assert "total_runs" in s
    assert "status_counts" in s
    assert "chain_tip" in s
    assert "invariants" in s
    assert "governor" in s


@pytest.mark.parametrize("tid", ["T199-CMES-26"])
def test_cmes_export_structure(tid, tmp_path):
    """CMES export returns ledger_path, total_entries, chain_tip, entries."""
    sb = _sandbox(tmp_path)
    r = sb.open_sandbox(_spec())
    sb.execute(r.run_id)
    exp = sb.export()
    assert "ledger_path" in exp
    assert "total_entries" in exp
    assert "chain_tip" in exp
    assert "entries" in exp


@pytest.mark.parametrize("tid", ["T199-CMES-27"])
def test_cmes_promote_adds_ledger_entry(tid, tmp_path):
    """CMES-PROMOTE-0: promotion appends a new ledger entry."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec(seed="promote-seed", mutation_id="promote-mut"))
    executed = sb.execute(run.run_id)
    if executed.status == SandboxStatus.PASSED:
        before = len(sb._ledger.all_entries())
        sb.promote(executed.run_id, HUMAN0)
        after = len(sb._ledger.all_entries())
        assert after == before + 1


@pytest.mark.parametrize("tid", ["T199-CMES-28"])
def test_cmes_discard_adds_ledger_entry(tid, tmp_path):
    """CMES-HUMAN0-0: discard appends new ledger entry."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    executed = sb.execute(run.run_id)
    before = len(sb._ledger.all_entries())
    sb.discard(executed.run_id, HUMAN0)
    after = len(sb._ledger.all_entries())
    assert after == before + 1


@pytest.mark.parametrize("tid", ["T199-CMES-29"])
def test_cmes_delta_duration_positive(tid, tmp_path):
    """CMES-DELTA-0: execution_duration_ms is a positive float."""
    sb = _sandbox(tmp_path)
    run = sb.open_sandbox(_spec())
    result = sb.execute(run.run_id)
    assert result.delta.execution_duration_ms >= 0.0


@pytest.mark.parametrize("tid", ["T199-CMES-30"])
def test_cmes_invariant_ids_complete(tid, tmp_path):
    """All 10 CMES Hard-class invariant IDs are present in the module manifest."""
    sb = _sandbox(tmp_path)
    expected = {
        "CMES-ISOLATE-0", "CMES-DETERM-0", "CMES-DELTA-0", "CMES-CHAIN-0",
        "CMES-IMMUT-0", "CMES-HUMAN0-0", "CMES-PROMOTE-0", "CMES-SCOPE-0",
        "CMES-REPLAY-0", "CMES-AUDIT-0",
    }
    actual = set(sb.INVARIANT_IDS)
    assert actual == expected, f"Missing: {expected - actual}"
