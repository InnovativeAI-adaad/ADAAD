"""
Phase 197 — INNOV-102 CMQ — Constitutional Mutation Queue
30-Test Acceptance Suite · T197-CMQ-01…30
v10.8.0 · InnovativeAI LLC · DUSTIN L REID (HUMAN-0)
"""
import json
import uuid
from pathlib import Path

import pytest

from dorkllm.constitutional_mutation_queue import (
    CompletionOutcome,
    ConstitutionalMutationQueue,
    EntryStatus,
    RuntimeDeterminismProvider,
    CMQChainBroken,
    CMQDeterminismViolation,
    CMQHuman0Bypass,
    CMQOverlapConflict,
    CMQQueueStalled,
    CMQScopeUndeclared,
    CMQAuthorInvalid,
    CMQBlastTierInvalid,
    CMQIntentLinkMissing,
    CMQError,
    GOVERNOR,
    HUMAN0_PRIORITY,
    OBJECTIVE_WEIGHTS,
    _compute_entry_hmac,
    _compute_priority,
)

pytestmark = pytest.mark.phase197


def _mid() -> str:
    return str(uuid.uuid4())


def _iid() -> str:
    return str(uuid.uuid4())


def fresh_queue(tmp_path: Path) -> ConstitutionalMutationQueue:
    RuntimeDeterminismProvider.reset()
    return ConstitutionalMutationQueue(ledger_path=tmp_path / "queue_ledger.jsonl")


# ===========================================================================
# T197-CMQ-01..03 — Enqueue happy path
# ===========================================================================

def test_t197_cmq_01_enqueue_valid_entry(tmp_path):
    """T197-CMQ-01: Valid enqueue returns QueueEntry with QUEUED status."""
    q = fresh_queue(tmp_path)
    mid = _mid()
    entry = q.enqueue(
        mutation_id=mid,
        intent_declaration_id=_iid(),
        author="MutationAgent",
        blast_tier=1,
        scope_paths=["dorkllm/feature_x.py"],
        governance_objectives=["CEL_INTEGRITY", "DETERMINISM"],
    )
    assert entry.mutation_id == mid
    assert entry.status == EntryStatus.QUEUED
    assert entry.blast_tier == 1
    assert entry.hmac != ""


def test_t197_cmq_02_enqueue_appends_ledger(tmp_path):
    """T197-CMQ-02: Enqueue appends one event to ledger."""
    q = fresh_queue(tmp_path)
    q.enqueue(
        mutation_id=_mid(), intent_declaration_id=_iid(),
        author="MutationAgent", blast_tier=2,
        scope_paths=["tests/test_foo.py"],
        governance_objectives=["MUTATION_SAFETY"],
    )
    ledger = (tmp_path / "queue_ledger.jsonl").read_text().strip().splitlines()
    assert len(ledger) == 1
    event = json.loads(ledger[0])
    assert event["event_type"] == "ENQUEUE"


def test_t197_cmq_03_enqueue_priority_stored_immutably(tmp_path):
    """T197-CMQ-03: Priority score stored on entry matches computed value."""
    q = fresh_queue(tmp_path)
    objectives = ["CEL_INTEGRITY", "INVARIANT_ENFORCEMENT"]
    entry = q.enqueue(
        mutation_id=_mid(), intent_declaration_id=_iid(),
        author="ArchitectAgent", blast_tier=0,
        scope_paths=["runtime/core.py"],
        governance_objectives=objectives,
    )
    obj_weight = sum(OBJECTIVE_WEIGHTS.get(o, 0) for o in objectives)
    expected = (3 - 0) * 100 + obj_weight
    assert entry.priority_score == expected
    assert entry.governance_objective_weight == obj_weight


# ===========================================================================
# T197-CMQ-04..07 — Overlap detection (CMQ-OVERLAP-0)
# ===========================================================================

def test_t197_cmq_04_overlap_exact_match_blocked(tmp_path):
    """T197-CMQ-04: Exact scope match with in-flight raises CMQOverlapConflict."""
    q = fresh_queue(tmp_path)
    scope = ["dorkllm/engine.py"]
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1, scope_paths=scope,
              governance_objectives=["CEL_INTEGRITY"])
    q.dequeue()  # mark first in-flight

    with pytest.raises(CMQOverlapConflict):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="MutationAgent", blast_tier=1,
                  scope_paths=scope,
                  governance_objectives=["CEL_INTEGRITY"])


def test_t197_cmq_05_overlap_prefix_match_blocked(tmp_path):
    """T197-CMQ-05: Prefix overlap with in-flight raises CMQOverlapConflict."""
    q = fresh_queue(tmp_path)
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/"],
              governance_objectives=["CEL_INTEGRITY"])
    q.dequeue()

    with pytest.raises(CMQOverlapConflict):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="MutationAgent", blast_tier=1,
                  scope_paths=["dorkllm/engine.py"],
                  governance_objectives=["CEL_INTEGRITY"])


def test_t197_cmq_06_no_overlap_allowed(tmp_path):
    """T197-CMQ-06: Non-overlapping scopes enqueue without conflict."""
    q = fresh_queue(tmp_path)
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/engine.py"],
              governance_objectives=["CEL_INTEGRITY"])
    q.dequeue()

    # Different path — no overlap
    entry = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                      author="MutationAgent", blast_tier=1,
                      scope_paths=["tests/test_other.py"],
                      governance_objectives=["CEL_INTEGRITY"])
    assert entry.status == EntryStatus.QUEUED


def test_t197_cmq_07_overlap_reverse_prefix_blocked(tmp_path):
    """T197-CMQ-07: Reverse prefix (in-flight is child of new) also blocked."""
    q = fresh_queue(tmp_path)
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/engine.py"],
              governance_objectives=["CEL_INTEGRITY"])
    q.dequeue()

    # new path is parent of in-flight path
    with pytest.raises(CMQOverlapConflict):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="MutationAgent", blast_tier=1,
                  scope_paths=["dorkllm/"],
                  governance_objectives=["CEL_INTEGRITY"])


# ===========================================================================
# T197-CMQ-08..11 — Priority ordering (CMQ-PRIORITY-0)
# ===========================================================================

def test_t197_cmq_08_blast_tier_dominates_ordering(tmp_path):
    """T197-CMQ-08: Lower blast tier yields higher priority score."""
    q = fresh_queue(tmp_path)
    e0 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                   author="MutationAgent", blast_tier=0,
                   scope_paths=["runtime/a.py"],
                   governance_objectives=[])
    e2 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                   author="MutationAgent", blast_tier=2,
                   scope_paths=["tests/b.py"],
                   governance_objectives=[])
    assert e0.priority_score > e2.priority_score


def test_t197_cmq_09_objective_weight_tiebreak(tmp_path):
    """T197-CMQ-09: Same blast tier — higher governance weight wins."""
    q = fresh_queue(tmp_path)
    e_heavy = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                        author="MutationAgent", blast_tier=1,
                        scope_paths=["dorkllm/a.py"],
                        governance_objectives=["HUMAN0_GATE", "CEL_INTEGRITY"])
    e_light = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                        author="MutationAgent", blast_tier=1,
                        scope_paths=["dorkllm/b.py"],
                        governance_objectives=["INNOVATION_DELIVERY"])
    assert e_heavy.priority_score > e_light.priority_score


def test_t197_cmq_10_fifo_tiebreak(tmp_path):
    """T197-CMQ-10: Equal priority — earlier enqueue_timestamp dequeues first."""
    q = fresh_queue(tmp_path)
    e1 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                   author="MutationAgent", blast_tier=1,
                   scope_paths=["dorkllm/x.py"],
                   governance_objectives=["CEL_INTEGRITY"])
    e2 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                   author="MutationAgent", blast_tier=1,
                   scope_paths=["dorkllm/y.py"],
                   governance_objectives=["CEL_INTEGRITY"])
    first = q.dequeue()
    assert first.mutation_id == e1.mutation_id  # e1 enqueued first


def test_t197_cmq_11_human0_override_highest_priority(tmp_path):
    """T197-CMQ-11: HUMAN-0 override lane yields HUMAN0_PRIORITY=9999."""
    q = fresh_queue(tmp_path)
    # High-weight normal mutation
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="ArchitectAgent", blast_tier=0,
              scope_paths=["runtime/a.py"],
              governance_objectives=list(OBJECTIVE_WEIGHTS.keys()))
    # HUMAN-0 override on different scope
    h0 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                   author=GOVERNOR, blast_tier=0,
                   scope_paths=["runtime/b.py"],
                   governance_objectives=[],
                   human0_override=True)
    assert h0.priority_score == HUMAN0_PRIORITY
    first = q.dequeue()
    assert first.mutation_id == h0.mutation_id


# ===========================================================================
# T197-CMQ-12..15 — HMAC chain (CMQ-CHAIN-0)
# ===========================================================================

def test_t197_cmq_12_valid_chain_verify(tmp_path):
    """T197-CMQ-12: Chain verify returns valid=True after normal operations."""
    q = fresh_queue(tmp_path)
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=["CEL_INTEGRITY"])
    result = q.verify_chain()
    assert result["valid"] is True


def test_t197_cmq_13_state_hmac_changes_on_enqueue(tmp_path):
    """T197-CMQ-13: state_hmac changes after each enqueue."""
    q = fresh_queue(tmp_path)
    hmac0 = q.get_state().state_hmac
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=[])
    hmac1 = q.get_state().state_hmac
    assert hmac0 != hmac1


def test_t197_cmq_14_snapshot_version_increments(tmp_path):
    """T197-CMQ-14: snapshot_version increments after each state-changing operation."""
    q = fresh_queue(tmp_path)
    v0 = q.get_state().snapshot_version
    q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=[])
    v1 = q.get_state().snapshot_version
    assert v1 == v0 + 1


def test_t197_cmq_15_entry_hmac_non_empty(tmp_path):
    """T197-CMQ-15: Every QueueEntry carries a non-empty HMAC."""
    q = fresh_queue(tmp_path)
    entry = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                      author="MutationAgent", blast_tier=1,
                      scope_paths=["dorkllm/a.py"],
                      governance_objectives=["CEL_INTEGRITY"])
    assert len(entry.hmac) == 64  # SHA-256 hex digest


# ===========================================================================
# T197-CMQ-16..19 — Dequeue + complete cycle
# ===========================================================================

def test_t197_cmq_16_dequeue_marks_in_flight(tmp_path):
    """T197-CMQ-16: Dequeue transitions entry to IN_FLIGHT."""
    q = fresh_queue(tmp_path)
    mid = _mid()
    q.enqueue(mutation_id=mid, intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=[])
    entry = q.dequeue()
    assert entry.status == EntryStatus.IN_FLIGHT
    assert mid in q._in_flight


def test_t197_cmq_17_complete_promoted(tmp_path):
    """T197-CMQ-17: complete(promoted) marks COMPLETED and releases scope lock."""
    q = fresh_queue(tmp_path)
    mid = _mid()
    q.enqueue(mutation_id=mid, intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=[])
    q.dequeue()
    entry = q.complete(mid, CompletionOutcome.PROMOTED)
    assert entry.status == EntryStatus.COMPLETED
    assert mid not in q._in_flight


def test_t197_cmq_18_complete_rolled_back(tmp_path):
    """T197-CMQ-18: complete(rolled_back) marks COMPLETED and releases scope lock."""
    q = fresh_queue(tmp_path)
    mid = _mid()
    q.enqueue(mutation_id=mid, intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=[])
    q.dequeue()
    entry = q.complete(mid, CompletionOutcome.ROLLED_BACK)
    assert entry.status == EntryStatus.COMPLETED
    assert mid not in q._in_flight


def test_t197_cmq_19_scope_lock_released_after_complete(tmp_path):
    """T197-CMQ-19: After complete, same scope path can be enqueued again."""
    q = fresh_queue(tmp_path)
    scope = ["dorkllm/engine.py"]
    mid = _mid()
    q.enqueue(mutation_id=mid, intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=scope, governance_objectives=[])
    q.dequeue()
    q.complete(mid, CompletionOutcome.PROMOTED)

    # Should succeed now
    entry2 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                       author="MutationAgent", blast_tier=1,
                       scope_paths=scope, governance_objectives=[])
    assert entry2.status == EntryStatus.QUEUED


# ===========================================================================
# T197-CMQ-20..21 — Stall detection (CMQ-DRAIN-0)
# ===========================================================================

def test_t197_cmq_20_empty_queue_raises_stalled(tmp_path):
    """T197-CMQ-20: Dequeue on empty queue raises CMQQueueStalled."""
    q = fresh_queue(tmp_path)
    with pytest.raises(CMQQueueStalled):
        q.dequeue()


def test_t197_cmq_21_peek_on_empty_returns_none(tmp_path):
    """T197-CMQ-21: Peek on empty queue returns None (no exception)."""
    q = fresh_queue(tmp_path)
    assert q.peek() is None


# ===========================================================================
# T197-CMQ-22..26 — API endpoint contracts
# ===========================================================================

def test_t197_cmq_22_api_enqueue_rejection_scope_empty(tmp_path):
    """T197-CMQ-22: CMQScopeUndeclared raised when scope_paths is empty."""
    q = fresh_queue(tmp_path)
    with pytest.raises(CMQScopeUndeclared):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="MutationAgent", blast_tier=1,
                  scope_paths=[], governance_objectives=[])


def test_t197_cmq_23_api_enqueue_rejection_human0_bypass(tmp_path):
    """T197-CMQ-23: CMQHuman0Bypass raised when non-HUMAN-0 sets override=True."""
    q = fresh_queue(tmp_path)
    with pytest.raises(CMQHuman0Bypass):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="MutationAgent", blast_tier=1,
                  scope_paths=["dorkllm/x.py"],
                  governance_objectives=[],
                  human0_override=True)


def test_t197_cmq_24_api_enqueue_rejection_invalid_author(tmp_path):
    """T197-CMQ-24: CMQAuthorInvalid raised for unknown author."""
    q = fresh_queue(tmp_path)
    with pytest.raises(CMQAuthorInvalid):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="RogueAgent", blast_tier=1,
                  scope_paths=["dorkllm/x.py"],
                  governance_objectives=[])


def test_t197_cmq_25_api_enqueue_rejection_intent_missing(tmp_path):
    """T197-CMQ-25: CMQIntentLinkMissing raised when intent_declaration_id is empty."""
    q = fresh_queue(tmp_path)
    with pytest.raises(CMQIntentLinkMissing):
        q.enqueue(mutation_id=_mid(), intent_declaration_id="",
                  author="MutationAgent", blast_tier=1,
                  scope_paths=["dorkllm/x.py"],
                  governance_objectives=[])


def test_t197_cmq_26_export_ledger_returns_all_events(tmp_path):
    """T197-CMQ-26: Export returns all ledger events."""
    q = fresh_queue(tmp_path)
    mid = _mid()
    q.enqueue(mutation_id=mid, intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"], governance_objectives=[])
    q.dequeue()
    q.complete(mid, CompletionOutcome.PROMOTED)

    events = q.export_ledger()
    event_types = [e["event_type"] for e in events]
    assert "ENQUEUE" in event_types
    assert "DEQUEUE" in event_types
    assert "COMPLETE" in event_types


# ===========================================================================
# T197-CMQ-27..28 — Determinism (CMQ-DETERM-0, CMQ-SERIAL-0)
# ===========================================================================

def test_t197_cmq_27_deterministic_provider_monotonic(tmp_path):
    """T197-CMQ-27: RuntimeDeterminismProvider yields monotonically increasing values."""
    RuntimeDeterminismProvider.reset(seed=1_000_000)
    t1 = RuntimeDeterminismProvider.now_ms()
    t2 = RuntimeDeterminismProvider.now_ms()
    t3 = RuntimeDeterminismProvider.now_ms()
    assert t1 < t2 < t3


def test_t197_cmq_28_identical_inputs_identical_priority(tmp_path):
    """T197-CMQ-28: Same blast_tier + objectives always produce same priority score."""
    q = fresh_queue(tmp_path)
    objectives = ["CEL_INTEGRITY", "MUTATION_SAFETY", "DETERMINISM"]
    blast_tier = 1

    # Compute manually
    obj_weight = sum(OBJECTIVE_WEIGHTS.get(o, 0) for o in objectives)
    expected = (3 - blast_tier) * 100 + obj_weight

    e1 = q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                   author="MutationAgent", blast_tier=blast_tier,
                   scope_paths=["dorkllm/a.py"],
                   governance_objectives=objectives)

    q2 = fresh_queue(Path(tmp_path / "q2"))
    e2 = q2.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                    author="MutationAgent", blast_tier=blast_tier,
                    scope_paths=["dorkllm/b.py"],
                    governance_objectives=objectives)

    assert e1.priority_score == expected
    assert e2.priority_score == expected


# ===========================================================================
# T197-CMQ-29..30 — Invariant enforcement
# ===========================================================================

def test_t197_cmq_29_invalid_blast_tier_rejected(tmp_path):
    """T197-CMQ-29: blast_tier outside {0,1,2} raises CMQBlastTierInvalid."""
    q = fresh_queue(tmp_path)
    with pytest.raises(CMQBlastTierInvalid):
        q.enqueue(mutation_id=_mid(), intent_declaration_id=_iid(),
                  author="MutationAgent", blast_tier=3,
                  scope_paths=["dorkllm/x.py"],
                  governance_objectives=[])


def test_t197_cmq_30_audit_trail_complete(tmp_path):
    """T197-CMQ-30: Every operation produces a ledger entry — full audit trail present."""
    q = fresh_queue(tmp_path)
    mid = _mid()
    q.enqueue(mutation_id=mid, intent_declaration_id=_iid(),
              author="MutationAgent", blast_tier=1,
              scope_paths=["dorkllm/a.py"],
              governance_objectives=["CEL_INTEGRITY"])
    q.dequeue()
    q.complete(mid, CompletionOutcome.PROMOTED)

    events = q.export_ledger()
    assert len(events) == 3
    for event in events:
        assert "event_type" in event
        assert "mutation_id" in event
        assert "timestamp_deterministic" in event
        assert "queue_depth" in event
        assert "hmac" in event
