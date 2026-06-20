# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase232_cacg.py
Phase 232 · INNOV-137 · CACG — Constitutional Autonomous Cycle Governor
30-test acceptance suite — T232-CACG-01 through T232-CACG-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 08
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_cycle_governor import (
    ACI_STAGES,
    CACGEngine,
    CACGViolation,
    ChainBreakError,
    ConfigError,
    HUMAN0EscalationError,
    ImmutabilityViolation,
    StageError,
    TimeoutViolation,
    CycleState,
    StageOutcome,
    TimeoutEnforcer,
    CycleGovernanceLedger,
    EscalationEngine,
    CACGAuditor,
    DEFAULT_STAGE_TIMEOUTS,
    _STAGE_COUNT,
    _STAGE_SET,
)
from app.api.cacg import router

pytestmark = pytest.mark.phase232

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _engine() -> CACGEngine:
    return CACGEngine()


def _now() -> float:
    return time.time()


def _complete_all_stages(eng: CACGEngine, cycle_id: str, delay: float = 0.001) -> None:
    """Register all 8 ACI stages with sub-timeout elapsed times."""
    t = _now()
    for stage in ACI_STAGES:
        eng.register_stage_completion(
            cycle_id=cycle_id,
            stage=stage,
            started_at=t,
            completed_at=t + delay,
            payload={"stage": stage},
        )
        t += delay


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL INVARIANTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_01_stage_count_exactly_8():
    """T232-CACG-01 · CACG-STAGES-0: exactly 8 ACI stages registered."""
    assert _STAGE_COUNT == 8


def test_T232_CACG_02_canonical_stage_set():
    """T232-CACG-02 · CACG-STAGES-0: canonical stages match expected names."""
    expected = {"CASL", "CADE", "CAPE", "CAVE", "CAOE", "CALI", "CACP", "CAMS"}
    assert _STAGE_SET == expected


def test_T232_CACG_03_default_timeouts_all_positive():
    """T232-CACG-03 · CACG-TIMEOUT-0: all default stage timeouts are positive."""
    for stage, t in DEFAULT_STAGE_TIMEOUTS.items():
        assert t > 0, f"Stage {stage} timeout must be positive"


def test_T232_CACG_04_config_error_on_zero_timeout():
    """T232-CACG-04 · CACG-TIMEOUT-0: zero timeout raises ConfigError."""
    bad = dict(DEFAULT_STAGE_TIMEOUTS)
    bad["CASL"] = 0.0
    with pytest.raises(ConfigError):
        TimeoutEnforcer(bad)


def test_T232_CACG_05_config_error_on_negative_timeout():
    """T232-CACG-05 · CACG-TIMEOUT-0: negative timeout raises ConfigError."""
    bad = dict(DEFAULT_STAGE_TIMEOUTS)
    bad["CADE"] = -1.0
    with pytest.raises(ConfigError):
        TimeoutEnforcer(bad)


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE REGISTRATION & TIMEOUT
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_06_unknown_stage_raises_stage_error():
    """T232-CACG-06 · CACG-STAGES-0: registering unknown stage raises StageError."""
    eng = _engine()
    cid = eng.start_cycle()
    t = _now()
    with pytest.raises(StageError):
        eng.register_stage_completion(cid, "UNKNOWN", t, t + 1)


def test_T232_CACG_07_stage_within_timeout_returns_receipt():
    """T232-CACG-07 · CACG-TIMEOUT-0: on-time stage returns COMPLETED receipt."""
    eng = _engine()
    cid = eng.start_cycle()
    t = _now()
    receipt = eng.register_stage_completion(cid, "CASL", t, t + 0.5)
    assert receipt.outcome == StageOutcome.COMPLETED
    assert not receipt.timed_out


def test_T232_CACG_08_stage_exceeding_timeout_raises_timeout_violation():
    """T232-CACG-08 · CACG-TIMEOUT-0: timed-out stage raises TimeoutViolation."""
    # Use tiny timeouts so we can force a timeout with real elapsed time
    tiny = dict(DEFAULT_STAGE_TIMEOUTS)
    tiny["CASL"] = 0.001  # 1 ms
    eng = CACGEngine(timeouts=tiny)
    cid = eng.start_cycle()
    t = _now()
    with pytest.raises(TimeoutViolation):
        eng.register_stage_completion(cid, "CASL", t, t + 10.0)  # 10 s >> 1 ms


def test_T232_CACG_09_timed_out_stage_marks_cycle_violated():
    """T232-CACG-09 · CACG-TIMEOUT-0: cycle state becomes VIOLATED after timeout."""
    tiny = dict(DEFAULT_STAGE_TIMEOUTS)
    tiny["CADE"] = 0.001
    eng = CACGEngine(timeouts=tiny)
    cid = eng.start_cycle()
    t = _now()
    try:
        eng.register_stage_completion(cid, "CADE", t, t + 999.0)
    except TimeoutViolation:
        pass
    # Close with HUMAN-0 identity since cycle is VIOLATED
    record = eng.close_cycle(cid, human0_identity="DUSTIN L REID")
    assert record.violated is True
    assert record.state == CycleState.ESCALATED


# ═══════════════════════════════════════════════════════════════════════════════
# CYCLE LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_10_start_cycle_returns_uuid():
    """T232-CACG-10: start_cycle returns a non-empty cycle_id."""
    eng = _engine()
    cid = eng.start_cycle()
    assert cid and len(cid) == 36  # UUID4


def test_T232_CACG_11_complete_cycle_state_is_completed():
    """T232-CACG-11 · CACG-DETERM-0: all-stages-done cycle → COMPLETED."""
    eng = _engine()
    cid = eng.start_cycle()
    _complete_all_stages(eng, cid)
    record = eng.close_cycle(cid)
    assert record.state == CycleState.COMPLETED
    assert not record.stalled
    assert not record.violated


def test_T232_CACG_12_partial_cycle_state_is_stalled():
    """T232-CACG-12 · CACG-STALL-0: missing stages → STALLED → ESCALATED."""
    eng = _engine()
    cid = eng.start_cycle()
    t = _now()
    # Only register CASL — other 7 missing
    eng.register_stage_completion(cid, "CASL", t, t + 0.001)
    record = eng.close_cycle(cid, human0_identity="DUSTIN L REID")
    assert record.stalled is True
    assert record.state == CycleState.ESCALATED


def test_T232_CACG_13_stall_requires_human0_identity():
    """T232-CACG-13 · CACG-HUMAN0-0: closing stalled cycle without identity raises."""
    eng = _engine()
    cid = eng.start_cycle()
    # Don't register any stages → stall
    with pytest.raises(HUMAN0EscalationError):
        eng.close_cycle(cid, human0_identity=None)


def test_T232_CACG_14_stall_empty_identity_raises():
    """T232-CACG-14 · CACG-HUMAN0-0: empty identity string raises."""
    eng = _engine()
    cid = eng.start_cycle()
    with pytest.raises(HUMAN0EscalationError):
        eng.close_cycle(cid, human0_identity="   ")


def test_T232_CACG_15_close_nonexistent_cycle_raises():
    """T232-CACG-15: closing unknown cycle_id raises KeyError."""
    eng = _engine()
    with pytest.raises(KeyError):
        eng.close_cycle("nonexistent-id")


def test_T232_CACG_16_cycle_not_in_active_after_close():
    """T232-CACG-16: completed cycle is removed from active cycles."""
    eng = _engine()
    cid = eng.start_cycle()
    _complete_all_stages(eng, cid)
    eng.close_cycle(cid)
    assert cid not in eng.get_active_cycles()


# ═══════════════════════════════════════════════════════════════════════════════
# LEDGER CHAIN & PROOF
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_17_sealed_record_has_proof_hmac():
    """T232-CACG-17 · CACG-PROOF-0: closed cycle record carries non-empty proof_hmac."""
    eng = _engine()
    cid = eng.start_cycle()
    _complete_all_stages(eng, cid)
    record = eng.close_cycle(cid)
    assert record.proof_hmac and len(record.proof_hmac) == 64


def test_T232_CACG_18_verify_chain_passes_after_close():
    """T232-CACG-18 · CACG-CHAIN-0: chain verifies after sealing cycles."""
    eng = _engine()
    for _ in range(3):
        cid = eng.start_cycle()
        _complete_all_stages(eng, cid)
        eng.close_cycle(cid)
    assert eng.verify_chain() is True


def test_T232_CACG_19_sealed_record_immutable():
    """T232-CACG-19 · CACG-IMMUT-0: writing to sealed record raises ImmutabilityViolation."""
    eng = _engine()
    cid = eng.start_cycle()
    _complete_all_stages(eng, cid)
    record = eng.close_cycle(cid)
    with pytest.raises(ImmutabilityViolation):
        record.state = CycleState.ACTIVE


def test_T232_CACG_20_ledger_grows_per_cycle():
    """T232-CACG-20 · CACG-APPEND-0: ledger count increments per sealed cycle."""
    eng = _engine()
    for i in range(5):
        cid = eng.start_cycle()
        _complete_all_stages(eng, cid)
        eng.close_cycle(cid)
    assert len(eng.get_ledger()) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_21_escalation_issued_on_stall():
    """T232-CACG-21 · CACG-HUMAN0-0: STALLED cycle produces escalation record."""
    eng = _engine()
    cid = eng.start_cycle()
    record = eng.close_cycle(cid, human0_identity="DUSTIN L REID")
    assert record.escalation_id is not None
    esc = eng.get_escalation(record.escalation_id)
    assert esc is not None
    assert not esc.acknowledged


def test_T232_CACG_22_acknowledge_escalation_clears_it():
    """T232-CACG-22 · CACG-HUMAN0-0: escalation acknowledgement accepted."""
    eng = _engine()
    cid = eng.start_cycle()
    record = eng.close_cycle(cid, human0_identity="DUSTIN L REID")
    esc = eng.acknowledge_escalation(record.escalation_id, "DUSTIN L REID")
    assert esc.acknowledged is True
    assert esc.acknowledged_by == "DUSTIN L REID"


def test_T232_CACG_23_double_acknowledge_raises_immutability():
    """T232-CACG-23 · CACG-IMMUT-0: double-acknowledgement raises ImmutabilityViolation."""
    eng = _engine()
    cid = eng.start_cycle()
    record = eng.close_cycle(cid, human0_identity="DUSTIN L REID")
    eng.acknowledge_escalation(record.escalation_id, "DUSTIN L REID")
    with pytest.raises(ImmutabilityViolation):
        eng.acknowledge_escalation(record.escalation_id, "DUSTIN L REID")


def test_T232_CACG_24_empty_acknowledged_by_raises():
    """T232-CACG-24 · CACG-HUMAN0-0: empty acknowledged_by raises."""
    eng = _engine()
    cid = eng.start_cycle()
    record = eng.close_cycle(cid, human0_identity="DUSTIN L REID")
    with pytest.raises(HUMAN0EscalationError):
        eng.acknowledge_escalation(record.escalation_id, "")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_25_audit_log_records_operations():
    """T232-CACG-25 · CACG-AUDIT-0: audit log grows with operations."""
    eng = _engine()
    cid = eng.start_cycle()
    _complete_all_stages(eng, cid)
    eng.close_cycle(cid)
    audit = eng.get_audit_log()
    ops = [e["operation"] for e in audit]
    assert "start_cycle" in ops
    assert "stage_completed" in ops
    assert "close_cycle" in ops


def test_T232_CACG_26_audit_events_have_chain_digests():
    """T232-CACG-26 · CACG-AUDIT-0: every audit event carries a chain_digest."""
    eng = _engine()
    cid = eng.start_cycle()
    _complete_all_stages(eng, cid)
    eng.close_cycle(cid)
    for event in eng.get_audit_log():
        assert event["chain_digest"] and len(event["chain_digest"]) == 64


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

def test_T232_CACG_27_api_start_and_close_cycle():
    """T232-CACG-27: POST /cacg/cycles/start → POST /cacg/cycles/{id}/close."""
    r = _client.post("/cacg/cycles/start")
    assert r.status_code == 201
    cid = r.json()["cycle_id"]

    now = time.time()
    for stage in ACI_STAGES:
        sr = _client.post(f"/cacg/cycles/{cid}/stages", json={
            "stage": stage,
            "started_at": now,
            "completed_at": now + 0.001,
        })
        assert sr.status_code == 201, f"Stage {stage} failed: {sr.text}"
        now += 0.001

    cr = _client.post(f"/cacg/cycles/{cid}/close", json={})
    assert cr.status_code == 200
    assert cr.json()["state"] == "COMPLETED"


def test_T232_CACG_28_api_unknown_stage_returns_422():
    """T232-CACG-28 · CACG-STAGES-0: POST /cacg/cycles/{id}/stages unknown stage → 422."""
    r = _client.post("/cacg/cycles/start")
    cid = r.json()["cycle_id"]
    now = time.time()
    sr = _client.post(f"/cacg/cycles/{cid}/stages", json={
        "stage": "BOGUS",
        "started_at": now,
        "completed_at": now + 1,
    })
    assert sr.status_code == 422


def test_T232_CACG_29_api_verify_chain():
    """T232-CACG-29 · CACG-CHAIN-0: GET /cacg/verify-chain returns chain_valid=true."""
    r = _client.get("/cacg/verify-chain")
    assert r.status_code == 200
    assert r.json()["chain_valid"] is True


def test_T232_CACG_30_api_status():
    """T232-CACG-30: GET /cacg/status returns module info and invariant list."""
    r = _client.get("/cacg/status")
    assert r.status_code == 200
    data = r.json()
    assert data["module"] == "CACG"
    assert data["innov"] == "INNOV-137"
    assert data["phase"] == 232
    assert len(data["invariants"]) == 10
