# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase232_cacg.py
Phase 232 · INNOV-137 · CACG — Constitutional Autonomous Cycle Governor
30-test acceptance suite — T232-CACG-01 through T232-CACG-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 08 (capstone)
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_cycle_governor import (
    CACGEngine,
    CACGViolation,
    ChainBreakError,
    StageError,
    TimeoutStateError,
    EscalationError,
    HUMAN0ResolveError,
    ImmutabilityViolation,
    CycleStatus,
    EscalationState,
    CycleOrchestrator,
    TimeoutEnforcer,
    EscalationEngine,
    CycleLedger,
    CACGAuditor,
    _CYCLE_STAGES,
)
from app.api.cacg import router

pytestmark = pytest.mark.phase232

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def engine() -> CACGEngine:
    return CACGEngine(timeout_seconds=100)


def _advance_to_end(eng: CACGEngine, cycle_id: str):
    last = None
    for stage in _CYCLE_STAGES[1:]:
        last = eng.advance(cycle_id, stage)
    return last


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-01  Module import and engine instantiation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_01_engine_instantiation():
    """T232-CACG-01: CACGEngine instantiates without error."""
    eng = CACGEngine()
    assert eng is not None


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-02  CACG-STAGE-0: exactly 7 fixed ordered stages
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_02_exactly_seven_stages():
    """T232-CACG-02: CACG-STAGE-0 — exactly 7 stages in the documented order."""
    assert len(_CYCLE_STAGES) == 7
    assert _CYCLE_STAGES == ("CASL", "CADE", "EXECUTE", "CAOE", "CALI", "CACP", "CAMS")


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-03  CACG-STAGE-0: opening a cycle starts at stage 0 (CASL)
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_03_open_cycle_starts_at_casl(engine):
    """T232-CACG-03: open_cycle() always begins at stage_index 0, CASL."""
    record = CycleOrchestrator().open_cycle("mutation-ref-A")
    assert record.stage_index == 0
    assert record.current_stage == "CASL"
    assert record.status == CycleStatus.OPEN


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-04  CACG-STAGE-0: empty cycle_ref rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_04_empty_cycle_ref_rejected():
    """T232-CACG-04: CACG-STAGE-0 — empty cycle_ref raises StageError."""
    with pytest.raises(StageError):
        CycleOrchestrator().open_cycle("")
    with pytest.raises(StageError):
        CycleOrchestrator().open_cycle("   ")


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-05  CACG-STAGE-0: advancement must follow strict order
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_05_out_of_order_advance_rejected():
    """T232-CACG-05: CACG-STAGE-0 — skipping a stage raises StageError."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-B")
    with pytest.raises(StageError):
        orch.advance(record.cycle_id, "EXECUTE")  # skips CADE


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-06  CACG-STAGE-0: unknown stage name rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_06_unknown_stage_rejected():
    """T232-CACG-06: CACG-STAGE-0 — unrecognized stage name raises StageError."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-C")
    with pytest.raises(StageError):
        orch.advance(record.cycle_id, "NOT_A_REAL_STAGE")


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-07  CACG-STAGE-0: correct sequential advance succeeds
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_07_sequential_advance_succeeds():
    """T232-CACG-07: advancing stages in exact order succeeds end-to-end."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-D")
    for stage in _CYCLE_STAGES[1:]:
        record = orch.advance(record.cycle_id, stage)
    assert record.current_stage == "CAMS"
    assert record.stage_index == 6
    assert record.stage_history == list(_CYCLE_STAGES)


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-08  Complete requires final stage reached
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_08_complete_requires_final_stage():
    """T232-CACG-08: complete() before reaching CAMS raises StageError."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-E")
    with pytest.raises(StageError):
        orch.complete(record.cycle_id)


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-09  CACG-SCOPE-0: completed cycle status is COMPLETED
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_09_completed_status(engine):
    """T232-CACG-09: CACG-SCOPE-0 — full traversal yields status COMPLETED."""
    c = engine.open_cycle("mutation-ref-F")
    _advance_to_end(engine, c["cycle_id"])
    done = engine.complete(c["cycle_id"])
    assert done["status"] == "COMPLETED"


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-10  CACG-IMMUT-0: cannot advance a COMPLETED cycle
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_10_cannot_advance_completed_cycle(engine):
    """T232-CACG-10: CACG-IMMUT-0 — advancing a COMPLETED cycle raises."""
    c = engine.open_cycle("mutation-ref-G")
    _advance_to_end(engine, c["cycle_id"])
    engine.complete(c["cycle_id"])
    with pytest.raises(ImmutabilityViolation):
        engine.advance(c["cycle_id"], "CADE")


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-11  CACG-DETERM-0 / CACG-TIMEOUT-0: under-threshold elapsed time
#               does not time out
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_11_under_threshold_no_timeout():
    """T232-CACG-11: CACG-DETERM-0 — elapsed time below threshold stays OPEN."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-H")
    enforcer = TimeoutEnforcer(timeout_seconds=1000)
    timed_out = enforcer.check(record, now=record.stage_started_ts + 10)
    assert timed_out is False
    assert record.status == CycleStatus.OPEN


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-12  CACG-TIMEOUT-0: over-threshold elapsed time times out
#               deterministically
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_12_over_threshold_times_out():
    """T232-CACG-12: CACG-TIMEOUT-0 — elapsed time beyond threshold => TIMED_OUT."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-I")
    enforcer = TimeoutEnforcer(timeout_seconds=100)
    timed_out = enforcer.check(record, now=record.stage_started_ts + 9999)
    assert timed_out is True
    assert record.status == CycleStatus.TIMED_OUT
    assert record.timed_out_ts is not None


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-13  CACG-DETERM-0: timeout check is repeatable / deterministic
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_13_timeout_check_deterministic():
    """T232-CACG-13: CACG-DETERM-0 — identical elapsed time always yields the
    same timeout verdict."""
    results = []
    for _ in range(3):
        orch = CycleOrchestrator()
        record = orch.open_cycle("mutation-ref-J")
        enforcer = TimeoutEnforcer(timeout_seconds=500)
        results.append(enforcer.check(record, now=record.stage_started_ts + 1000))
    assert results == [True, True, True]


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-14  CACG-TIMEOUT-0: checking a non-OPEN cycle raises
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_14_timeout_check_requires_open():
    """T232-CACG-14: CACG-TIMEOUT-0 — checking a COMPLETED cycle raises TimeoutStateError."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-K")
    for stage in _CYCLE_STAGES[1:]:
        orch.advance(record.cycle_id, stage)
    orch.complete(record.cycle_id)
    with pytest.raises(TimeoutStateError):
        TimeoutEnforcer().check(record, now=time.time())


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-15  CACG-ESCALATE-0: TIMED_OUT cycle raises exactly one escalation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_15_timed_out_raises_one_escalation(engine):
    """T232-CACG-15: CACG-ESCALATE-0 — check_timeout() on a stalled cycle
    produces exactly one escalation_id."""
    c = engine.open_cycle("mutation-ref-L")
    result = engine.check_timeout(c["cycle_id"], now=c["stage_started_ts"] + 99999)
    assert result["status"] == "TIMED_OUT"
    assert "escalation_id" in result
    assert len(engine.all_escalations()) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-16  CACG-ESCALATE-0: raising on a non-TIMED_OUT cycle rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_16_escalate_rejects_non_timed_out():
    """T232-CACG-16: CACG-ESCALATE-0 — raise_escalation() on an OPEN cycle raises EscalationError."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-M")
    with pytest.raises(EscalationError):
        EscalationEngine().raise_escalation(record)


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-17  CACG-ESCALATE-0: duplicate escalation for same cycle rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_17_duplicate_escalation_rejected():
    """T232-CACG-17: CACG-ESCALATE-0 — a second escalation for the same TIMED_OUT
    cycle raises ImmutabilityViolation."""
    orch = CycleOrchestrator()
    record = orch.open_cycle("mutation-ref-N")
    TimeoutEnforcer(timeout_seconds=10).check(record, now=record.stage_started_ts + 999)
    eng = EscalationEngine()
    eng.raise_escalation(record)
    with pytest.raises(ImmutabilityViolation):
        eng.raise_escalation(record)


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-18  CACG-HUMAN0-0: resolution requires non-empty identity
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_18_resolve_requires_human0_identity(engine):
    """T232-CACG-18: CACG-HUMAN0-0 — empty resolved_by raises HUMAN0ResolveError."""
    c = engine.open_cycle("mutation-ref-O")
    result = engine.check_timeout(c["cycle_id"], now=c["stage_started_ts"] + 99999)
    with pytest.raises(HUMAN0ResolveError):
        engine.resolve_escalation(result["escalation_id"], "")
    with pytest.raises(HUMAN0ResolveError):
        engine.resolve_escalation(result["escalation_id"], "   ")


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-19  CACG-HUMAN0-0: valid resolution clears escalation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_19_valid_resolution_clears_escalation(engine):
    """T232-CACG-19: CACG-HUMAN0-0 — non-empty identity transitions escalation to RESOLVED."""
    c = engine.open_cycle("mutation-ref-P")
    result = engine.check_timeout(c["cycle_id"], now=c["stage_started_ts"] + 99999)
    escalation = engine.resolve_escalation(result["escalation_id"], "DUSTIN L REID", "reviewed")
    assert escalation.state == EscalationState.RESOLVED
    assert escalation.resolved_by == "DUSTIN L REID"
    assert len(engine.open_escalations()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-20  CACG-IMMUT-0: resolved escalation cannot be re-resolved
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_20_double_resolve_blocked(engine):
    """T232-CACG-20: CACG-IMMUT-0 — re-resolving a RESOLVED escalation raises."""
    c = engine.open_cycle("mutation-ref-Q")
    result = engine.check_timeout(c["cycle_id"], now=c["stage_started_ts"] + 99999)
    engine.resolve_escalation(result["escalation_id"], "DUSTIN L REID")
    with pytest.raises(ImmutabilityViolation):
        engine.resolve_escalation(result["escalation_id"], "DUSTIN L REID")


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-21  CACG-CHAIN-0: empty cycle ledger chain trivially verifies
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_21_empty_ledger_chain_verifies():
    """T232-CACG-21: CACG-CHAIN-0 — an empty ledger trivially verifies."""
    assert CycleLedger().verify_chain() is True


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-22  CACG-CHAIN-0: chain verifies after a full cycle traversal
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_22_chain_verifies_after_traversal(engine):
    """T232-CACG-22: CACG-CHAIN-0 — chain remains intact through open/advance/complete."""
    c = engine.open_cycle("mutation-ref-R")
    _advance_to_end(engine, c["cycle_id"])
    engine.complete(c["cycle_id"])
    assert engine.verify_chain() is True
    assert len(engine._ledger) == 8  # open + 6 advances + complete


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-23  CACG-CHAIN-0: tampered entry hash detected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_23_tampered_hash_detected(engine):
    """T232-CACG-23: CACG-CHAIN-0 — mutating a sealed entry's hash is detected."""
    c = engine.open_cycle("mutation-ref-S")
    engine.advance(c["cycle_id"], "CADE")
    entries = engine._ledger.all_entries()
    entries[0].entry_hash = "0" * 64
    with pytest.raises(ChainBreakError):
        engine.verify_chain()


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-24  CACG-CHAIN-0: tampered prev_hash linkage detected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_24_tampered_link_detected(engine):
    """T232-CACG-24: CACG-CHAIN-0 — mutating prev_hash linkage is detected."""
    c = engine.open_cycle("mutation-ref-T")
    engine.advance(c["cycle_id"], "CADE")
    entries = engine._ledger.all_entries()
    entries[1].prev_hash = "f" * 64
    with pytest.raises(ChainBreakError):
        engine.verify_chain()


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-25  CACG-APPEND-0: ledger length grows monotonically
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_25_ledger_append_only(engine):
    """T232-CACG-25: CACG-APPEND-0 — ledger length strictly increases with each transition."""
    c = engine.open_cycle("mutation-ref-U")
    lengths = [len(engine._ledger)]
    for stage in _CYCLE_STAGES[1:]:
        engine.advance(c["cycle_id"], stage)
        lengths.append(len(engine._ledger))
    assert lengths == sorted(lengths)
    assert lengths[-1] == 7


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-26  CACG-AUDIT-0: every cycle operation is audited
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_26_audit_log_grows_on_open(engine):
    """T232-CACG-26: CACG-AUDIT-0 — audit log records OPEN_CYCLE and LEDGER_APPEND."""
    before = len(engine.audit_log())
    engine.open_cycle("mutation-ref-V")
    after = len(engine.audit_log())
    assert after > before
    ops = {e["operation"] for e in engine.audit_log()}
    assert {"OPEN_CYCLE", "LEDGER_APPEND"}.issubset(ops)


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-27  CACG-AUDIT-0: auditor's own HMAC chain is internally consistent
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_27_audit_chain_consistent():
    """T232-CACG-27: CACG-AUDIT-0 — auditor entries are HMAC-bound and linked."""
    auditor = CACGAuditor()
    auditor.record("OPEN_CYCLE", "CACG-AAA")
    auditor.record("ADVANCE", "CACG-AAA")
    entries = auditor.all_entries()
    assert entries[0].prev_hash == "0" * 64
    assert entries[1].prev_hash == entries[0].entry_hash
    for e in entries:
        assert len(e.entry_hash) == 64


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-28  CACGEngine.status reports expected fields
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_28_status_fields(engine):
    """T232-CACG-28: status() reports module identity, version, stages, and counters."""
    engine.open_cycle("mutation-ref-W")
    status = engine.status()
    assert status["module"] == "CACG"
    assert status["innov"] == "INNOV-137"
    assert status["phase"] == 232
    assert status["total_cycles"] == 1
    assert status["stages"] == list(_CYCLE_STAGES)


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-29  API /cacg/cycle/open + /cacg/cycle/{id}/advance round-trip
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_29_api_open_and_advance_round_trip():
    """T232-CACG-29: POST /cacg/cycle/open then /advance works end-to-end via the API."""
    open_resp = _client.post("/cacg/cycle/open", json={"cycle_ref": "api-mutation-ref-1"})
    assert open_resp.status_code == 200
    cycle_id = open_resp.json()["cycle_id"]
    adv_resp = _client.post(f"/cacg/cycle/{cycle_id}/advance", json={"stage": "CADE"})
    assert adv_resp.status_code == 200
    assert adv_resp.json()["current_stage"] == "CADE"


# ═══════════════════════════════════════════════════════════════════════════════
# T232-CACG-30  API /cacg/verify-chain and /cacg/status respond healthy
# ═══════════════════════════════════════════════════════════════════════════════
def test_T232_CACG_30_api_verify_chain_and_status():
    """T232-CACG-30: GET /cacg/verify-chain and GET /cacg/status both respond 200."""
    chain_resp = _client.get("/cacg/verify-chain")
    status_resp = _client.get("/cacg/status")
    assert chain_resp.status_code == 200
    assert chain_resp.json()["chain_intact"] is True
    assert status_resp.status_code == 200
    assert status_resp.json()["module"] == "CACG"
