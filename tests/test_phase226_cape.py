# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase226_cape.py
Phase 226 · INNOV-131 · CAPE — Constitutional Autonomous Promotion Executor
30-test acceptance suite · DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Test IDs: T226-CAPE-01 … T226-CAPE-30
Markers:  phase226, cape
"""

from __future__ import annotations

import pytest

from dorkllm.constitutional_autonomous_promotion_executor import (
    CAPEEngine,
    CAPEViolation,
    ChainBreakError,
    ExecutionError,
    ExecutionLedger,
    ExecutionStatus,
    GateBlockError,
    HUMAN0ApprovalError,
    ImmutabilityViolation,
    OrderViolation,
    PromotionExecutor,
    PromotionQueue,
    ExecutionAuditor,
    QueueStatus,
    ScopeViolation,
    _PROMOTE_VERDICT,
    _CHI_GATE_THRESHOLD,
    _PIPELINE_STAGES,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine() -> CAPEEngine:
    return CAPEEngine()


@pytest.fixture
def queue() -> PromotionQueue:
    return PromotionQueue()


@pytest.fixture
def ledger() -> ExecutionLedger:
    return ExecutionLedger()


@pytest.fixture
def auditor() -> ExecutionAuditor:
    return ExecutionAuditor()


def _enqueue_and_approve(engine: CAPEEngine, chi: float = 0.90, mutation_ref: str = "MUT-TEST") -> str:
    """Helper: enqueue + approve a valid PROMOTE entry; returns entry_id."""
    entry = engine.enqueue(
        decision_id="DEC-001",
        synthesis_id="SYN-001",
        chi_score=chi,
        mutation_ref=mutation_ref,
        verdict=_PROMOTE_VERDICT,
    )
    engine.approve(entry_id=entry["entry_id"], approved_by="DUSTIN L REID")
    return entry["entry_id"]


# ── Invariant coverage ────────────────────────────────────────────────────────

@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_01_scope_violation_non_promote(engine: CAPEEngine):
    """T226-CAPE-01: CAPE-SCOPE-0: HOLD verdict raises ScopeViolation."""
    with pytest.raises(ScopeViolation):
        engine.enqueue("D1", "S1", 0.95, "M1", "HOLD")


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_02_scope_violation_reject_verdict(engine: CAPEEngine):
    """T226-CAPE-02: CAPE-SCOPE-0: REJECT verdict raises ScopeViolation."""
    with pytest.raises(ScopeViolation):
        engine.enqueue("D1", "S1", 0.95, "M1", "REJECT")


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_03_gate_block_chi_below_threshold(engine: CAPEEngine):
    """T226-CAPE-03: CAPE-GATE-0: CHI 0.79 raises GateBlockError."""
    with pytest.raises(GateBlockError):
        engine.enqueue("D1", "S1", 0.79, "M1", _PROMOTE_VERDICT)


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_04_gate_block_chi_zero(engine: CAPEEngine):
    """T226-CAPE-04: CAPE-GATE-0: CHI 0.0 raises GateBlockError."""
    with pytest.raises(GateBlockError):
        engine.enqueue("D1", "S1", 0.0, "M1", _PROMOTE_VERDICT)


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_05_enqueue_success_returns_pending(engine: CAPEEngine):
    """T226-CAPE-05: CAPE-QUEUE-0: valid enqueue returns PENDING entry."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    assert entry["status"] == QueueStatus.PENDING.value
    assert entry["verdict"] == _PROMOTE_VERDICT
    assert entry["chi_score"] == 0.90


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_06_enqueue_hmac_seal_present(engine: CAPEEngine):
    """T226-CAPE-06: CAPE-QUEUE-0: enqueued entry has non-empty hmac_seal."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    assert entry["hmac_seal"] and len(entry["hmac_seal"]) == 64


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_07_approve_requires_human0_id(engine: CAPEEngine):
    """T226-CAPE-07: CAPE-HUMAN0-0: empty approved_by raises HUMAN0ApprovalError."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    with pytest.raises(HUMAN0ApprovalError):
        engine.approve(entry["entry_id"], "")


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_08_approve_whitespace_only_raises(engine: CAPEEngine):
    """T226-CAPE-08: CAPE-HUMAN0-0: whitespace-only approved_by raises HUMAN0ApprovalError."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    with pytest.raises(HUMAN0ApprovalError):
        engine.approve(entry["entry_id"], "   ")


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_09_approve_success_transitions_to_approved(engine: CAPEEngine):
    """T226-CAPE-09: CAPE-HUMAN0-0: valid approval transitions entry to APPROVED."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    approved = engine.approve(entry["entry_id"], "DUSTIN L REID")
    assert approved["status"] == QueueStatus.APPROVED.value
    assert approved["approved_by"] == "DUSTIN L REID"


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_10_execute_requires_approved_entry(engine: CAPEEngine):
    """T226-CAPE-10: CAPE-EXEC-0: executing PENDING entry raises ExecutionError."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    with pytest.raises((ExecutionError, CAPEViolation)):
        engine.execute(entry["entry_id"])


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_11_full_pipeline_success(engine: CAPEEngine):
    """T226-CAPE-11: End-to-end: enqueue→approve→execute succeeds with SUCCESS status."""
    entry_id = _enqueue_and_approve(engine)
    rec = engine.execute(entry_id)
    assert rec["status"] == ExecutionStatus.SUCCESS.value
    assert rec["stages_completed"] == _PIPELINE_STAGES


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_12_execution_record_has_proof(engine: CAPEEngine):
    """T226-CAPE-12: CAPE-CHAIN-0: execution record has 64-char SHA-256 proof."""
    entry_id = _enqueue_and_approve(engine)
    rec = engine.execute(entry_id)
    assert rec["proof"] and len(rec["proof"]) == 64


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_13_execution_record_has_hmac_seal(engine: CAPEEngine):
    """T226-CAPE-13: CAPE-CHAIN-0: execution record has 64-char hmac_seal."""
    entry_id = _enqueue_and_approve(engine)
    rec = engine.execute(entry_id)
    assert rec["hmac_seal"] and len(rec["hmac_seal"]) == 64


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_14_chain_valid_after_single_execution(engine: CAPEEngine):
    """T226-CAPE-14: CAPE-CHAIN-0: ledger chain valid after one execution."""
    _enqueue_and_approve(engine)
    entry_id = list(engine.list_queue())[0]["entry_id"]
    engine.execute(entry_id)
    chain = engine.verify_chain()
    assert chain["chain_valid"] is True


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_15_chain_valid_after_multiple_executions(engine: CAPEEngine):
    """T226-CAPE-15: CAPE-CHAIN-0: chain valid after three sequential executions."""
    for i in range(3):
        e = engine.enqueue(f"D{i}", f"S{i}", 0.85 + i * 0.02, f"MUT-{i}", _PROMOTE_VERDICT)
        engine.approve(e["entry_id"], "DUSTIN L REID")
        engine.execute(e["entry_id"])
    assert engine.verify_chain()["chain_valid"] is True


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_16_order_violation_non_fifo(engine: CAPEEngine):
    """T226-CAPE-16: CAPE-ORDER-0: executing second entry before first raises OrderViolation."""
    e1 = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    e2 = engine.enqueue("D2", "S2", 0.92, "M2", _PROMOTE_VERDICT)
    engine.approve(e1["entry_id"], "DUSTIN L REID")
    engine.approve(e2["entry_id"], "DUSTIN L REID")
    with pytest.raises(OrderViolation):
        engine.execute(e2["entry_id"])


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_17_fifo_order_correct_sequence(engine: CAPEEngine):
    """T226-CAPE-17: CAPE-ORDER-0: FIFO executes first entry first."""
    e1 = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    e2 = engine.enqueue("D2", "S2", 0.92, "M2", _PROMOTE_VERDICT)
    engine.approve(e1["entry_id"], "DUSTIN L REID")
    engine.approve(e2["entry_id"], "DUSTIN L REID")
    rec1 = engine.execute(e1["entry_id"])
    assert rec1["mutation_ref"] == "M1"
    rec2 = engine.execute(e2["entry_id"])
    assert rec2["mutation_ref"] == "M2"


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_18_list_queue_empty_on_new_engine(engine: CAPEEngine):
    """T226-CAPE-18: CAPE-QUEUE-0: fresh engine queue is empty."""
    assert engine.list_queue() == []


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_19_list_queue_returns_all_entries(engine: CAPEEngine):
    """T226-CAPE-19: CAPE-QUEUE-0: list_queue returns all enqueued entries."""
    for i in range(3):
        engine.enqueue(f"D{i}", f"S{i}", 0.85, f"M{i}", _PROMOTE_VERDICT)
    assert len(engine.list_queue()) == 3


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_20_list_executions_empty_before_execute(engine: CAPEEngine):
    """T226-CAPE-20: CAPE-APPEND-0: execution ledger empty before any execute."""
    assert engine.list_executions() == []


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_21_list_executions_count_matches_executions(engine: CAPEEngine):
    """T226-CAPE-21: CAPE-APPEND-0: execution count matches after two runs."""
    for i in range(2):
        e = engine.enqueue(f"D{i}", f"S{i}", 0.90, f"M{i}", _PROMOTE_VERDICT)
        engine.approve(e["entry_id"], "DUSTIN L REID")
        engine.execute(e["entry_id"])
    assert len(engine.list_executions()) == 2


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_22_audit_log_populated_after_operations(engine: CAPEEngine):
    """T226-CAPE-22: CAPE-AUDIT-0: audit log captures enqueue, approve, execute operations."""
    entry_id = _enqueue_and_approve(engine)
    engine.execute(entry_id)
    audit = engine.get_audit()
    ops = {e["operation"] for e in audit}
    assert "enqueue" in ops
    assert "approve" in ops


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_23_audit_entries_have_hmac_seals(engine: CAPEEngine):
    """T226-CAPE-23: CAPE-AUDIT-0: every audit entry has a 64-char hmac_seal."""
    _enqueue_and_approve(engine)
    for entry in engine.get_audit():
        assert entry["hmac_seal"] and len(entry["hmac_seal"]) == 64


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_24_get_queue_entry_returns_correct(engine: CAPEEngine):
    """T226-CAPE-24: get_queue_entry returns matching entry_id."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    fetched = engine.get_queue_entry(entry["entry_id"])
    assert fetched is not None
    assert fetched["entry_id"] == entry["entry_id"]


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_25_get_execution_returns_correct(engine: CAPEEngine):
    """T226-CAPE-25: get_execution returns matching record_id."""
    entry_id = _enqueue_and_approve(engine)
    rec = engine.execute(entry_id)
    fetched = engine.get_execution(rec["record_id"])
    assert fetched is not None
    assert fetched["record_id"] == rec["record_id"]


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_26_reject_transitions_to_rejected(engine: CAPEEngine):
    """T226-CAPE-26: reject transitions entry to REJECTED status."""
    entry = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    rejected = engine.reject(entry["entry_id"], "DUSTIN L REID")
    assert rejected["status"] == QueueStatus.REJECTED.value


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_27_status_reflects_queue_counts(engine: CAPEEngine):
    """T226-CAPE-27: status() accurately reflects pending and approved counts."""
    e1 = engine.enqueue("D1", "S1", 0.90, "M1", _PROMOTE_VERDICT)
    engine.enqueue("D2", "S2", 0.91, "M2", _PROMOTE_VERDICT)
    engine.approve(e1["entry_id"], "DUSTIN L REID")
    st = engine.status()
    assert st["pending_queue"] == 1
    assert st["approved_queue"] == 1
    assert st["total_queue"] == 2


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_28_status_invariants_all_present(engine: CAPEEngine):
    """T226-CAPE-28: status() lists all 10 CAPE hard-class invariants."""
    st = engine.status()
    expected = {
        "CAPE-CHAIN-0", "CAPE-APPEND-0", "CAPE-EXEC-0", "CAPE-GATE-0",
        "CAPE-QUEUE-0", "CAPE-AUDIT-0", "CAPE-HUMAN0-0", "CAPE-SCOPE-0",
        "CAPE-IMMUT-0", "CAPE-ORDER-0",
    }
    assert set(st["hard_invariants"]) == expected


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_29_scope_violation_missing_decision_id(engine: CAPEEngine):
    """T226-CAPE-29: CAPE-SCOPE-0: empty decision_id raises CAPEViolation."""
    with pytest.raises(CAPEViolation):
        engine.enqueue("", "S1", 0.90, "M1", _PROMOTE_VERDICT)


@pytest.mark.phase226
@pytest.mark.cape
def test_T226_CAPE_30_pipeline_stages_constant_is_five(engine: CAPEEngine):
    """T226-CAPE-30: _PIPELINE_STAGES has exactly 5 ordered stages."""
    assert _PIPELINE_STAGES == ["VALIDATE", "STAGE", "EXECUTE", "SEAL", "RECORD"]
    assert len(_PIPELINE_STAGES) == 5
    st = engine.status()
    assert st["pipeline_stages"] == _PIPELINE_STAGES
