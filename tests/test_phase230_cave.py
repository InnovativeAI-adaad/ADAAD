# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase230_cave.py
Phase 230 · INNOV-135 · CAVE — Constitutional Autonomous Verdict Executor
30-test acceptance suite — T230-CAVE-01 through T230-CAVE-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 06
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_verdict_executor import (
    CAVEEngine,
    CAVEViolation,
    ChainBreakError,
    ImmutabilityViolation,
    ScopeViolation,
    ReEvalError,
    HUMAN0ReleaseError,
    OriginViolation,
    VerdictClass,
    QuarantineState,
    ReEvalStatus,
    VerdictRouter,
    QuarantineEngine,
    CHIReEvaluator,
    QuarantineLedger,
    CAVEAuditor,
    _VERDICT_CLASSES,
)
from app.api.cave import router

pytestmark = pytest.mark.phase230

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def engine() -> CAVEEngine:
    return CAVEEngine()


@pytest.fixture
def cade_id() -> str:
    return "CADE-REC-ABCDEF123456"


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-01  Module import and engine instantiation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_01_engine_instantiation():
    """T230-CAVE-01: CAVEEngine instantiates without error."""
    eng = CAVEEngine()
    assert eng is not None


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-02  CAVE-SCOPE-0: exactly 3 verdict classes
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_02_scope_exactly_three_classes():
    """T230-CAVE-02: CAVE-SCOPE-0 — exactly 3 verdict classes: HOLD, REJECT, DEFER."""
    assert len(_VERDICT_CLASSES) == 3
    assert "HOLD" in _VERDICT_CLASSES
    assert "REJECT" in _VERDICT_CLASSES
    assert "DEFER" in _VERDICT_CLASSES


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-03  CAVE-ORIGIN-0: empty cade_record_id raises OriginViolation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_03_origin_empty_cade_id(engine):
    """T230-CAVE-03: CAVE-ORIGIN-0 — empty cade_record_id raises OriginViolation."""
    with pytest.raises(OriginViolation):
        engine.execute("", "REJECT", "mut-001", 0.30)


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-04  CAVE-SCOPE-0: unknown verdict raises ScopeViolation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_04_scope_unknown_verdict(engine, cade_id):
    """T230-CAVE-04: CAVE-SCOPE-0 — unknown verdict raises ScopeViolation."""
    with pytest.raises(ScopeViolation):
        engine.execute(cade_id, "PROMOTE", "mut-001", 0.90)


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-05  CAVE-QUARANTINE-0: REJECT sealed into quarantine
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_05_reject_quarantine_sealed(engine, cade_id):
    """T230-CAVE-05: CAVE-QUARANTINE-0 — REJECT verdict sealed into quarantine."""
    result = engine.execute(cade_id, "REJECT", "mut-001", 0.30)
    assert result["verdict"] == "REJECT"
    assert result["state"] == QuarantineState.SEALED.value


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-06  CAVE-REEVAL-0: HOLD verdict issues re-eval trigger
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_06_hold_reeval_trigger(engine, cade_id):
    """T230-CAVE-06: CAVE-REEVAL-0 — HOLD verdict produces CHI re-eval trigger."""
    result = engine.execute(cade_id, "HOLD", "mut-002", 0.65)
    assert result["verdict"] == "HOLD"
    assert "reeval_trigger_id" in result
    trigger_id = result["reeval_trigger_id"]
    trigger = engine.get_trigger(trigger_id)
    assert trigger is not None
    assert trigger.status == ReEvalStatus.PENDING


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-07  CAVE-DETERM-0: identical inputs produce deterministic routing
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_07_deterministic_routing(cade_id):
    """T230-CAVE-07: CAVE-DETERM-0 — verdict routing is deterministic."""
    e1 = CAVEEngine()
    e2 = CAVEEngine()
    r1 = e1.execute(cade_id, "REJECT", "mut-det", 0.30)
    r2 = e2.execute(cade_id, "REJECT", "mut-det", 0.30)
    assert r1["verdict"] == r2["verdict"] == "REJECT"
    assert r1["status"] == r2["status"]


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-08  CAVE-CHAIN-0: ledger chain verifies after single append
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_08_chain_verify_single(engine, cade_id):
    """T230-CAVE-08: CAVE-CHAIN-0 — ledger chain verifies after one record."""
    engine.execute(cade_id, "REJECT", "mut-chain", 0.20)
    assert engine.verify_chain() is True


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-09  CAVE-CHAIN-0: ledger chain verifies after multiple appends
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_09_chain_verify_multiple(engine, cade_id):
    """T230-CAVE-09: CAVE-CHAIN-0 — chain verifies after 5 records."""
    for i in range(5):
        v = "HOLD" if i % 2 == 0 else "REJECT"
        engine.execute(f"{cade_id}-{i}", v, f"mut-{i:03d}", 0.40)
    assert engine.verify_chain() is True


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-10  CAVE-HUMAN0-0: release with empty released_by raises error
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_10_human0_empty_released_by(engine, cade_id):
    """T230-CAVE-10: CAVE-HUMAN0-0 — empty released_by raises HUMAN0ReleaseError."""
    result = engine.execute(cade_id, "REJECT", "mut-h0", 0.25)
    with pytest.raises(HUMAN0ReleaseError):
        engine.release_quarantine(result["record_id"], "", "reason")


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-11  CAVE-HUMAN0-0: valid release transitions SEALED → RELEASED
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_11_human0_valid_release(engine, cade_id):
    """T230-CAVE-11: CAVE-HUMAN0-0 — valid HUMAN-0 release transitions state."""
    result = engine.execute(cade_id, "REJECT", "mut-rel", 0.20)
    record = engine.release_quarantine(
        result["record_id"], "DUSTIN L. REID", "approved for retry"
    )
    assert record.state == QuarantineState.RELEASED
    assert record.released_by == "DUSTIN L. REID"


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-12  CAVE-IMMUT-0: double-release raises ImmutabilityViolation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_12_immut_double_release(engine, cade_id):
    """T230-CAVE-12: CAVE-IMMUT-0 — double-release raises ImmutabilityViolation."""
    result = engine.execute(cade_id, "REJECT", "mut-immut", 0.20)
    engine.release_quarantine(result["record_id"], "DUSTIN L. REID", "first release")
    with pytest.raises(ImmutabilityViolation):
        engine.release_quarantine(result["record_id"], "DUSTIN L. REID", "second release")


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-13  CAVE-REEVAL-0: completing trigger with new CHI marks COMPLETED
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_13_reeval_complete(engine, cade_id):
    """T230-CAVE-13: CAVE-REEVAL-0 — complete trigger transitions to COMPLETED."""
    result = engine.execute(cade_id, "HOLD", "mut-reeval", 0.60)
    trigger_id = result["reeval_trigger_id"]
    trigger = engine.complete_reeval(trigger_id, 0.85)
    assert trigger.status == ReEvalStatus.COMPLETED
    assert trigger.new_chi == 0.85


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-14  CAVE-REEVAL-0: double-complete raises ReEvalError
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_14_reeval_double_complete(engine, cade_id):
    """T230-CAVE-14: CAVE-REEVAL-0 — completing a non-PENDING trigger raises error."""
    result = engine.execute(cade_id, "HOLD", "mut-reeval2", 0.58)
    trigger_id = result["reeval_trigger_id"]
    engine.complete_reeval(trigger_id, 0.80)
    with pytest.raises(ReEvalError):
        engine.complete_reeval(trigger_id, 0.90)


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-15  CAVE-REEVAL-0: CHIReEvaluator rejects non-HOLD verdicts
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_15_reeval_only_for_hold():
    """T230-CAVE-15: CAVE-REEVAL-0 — CHIReEvaluator raises for non-HOLD record."""
    from dorkllm.constitutional_autonomous_verdict_executor import VerdictRecord
    import time
    record = VerdictRecord(
        record_id="REC-999",
        cade_record_id="CADE-999",
        verdict=VerdictClass.REJECT,
        mutation_ref="mut-x",
        chi_score=0.2,
        sealed_ts=time.time(),
    )
    reeval = CHIReEvaluator()
    with pytest.raises(ReEvalError):
        reeval.issue_trigger(record)


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-16  CAVE-QUARANTINE-0: DEFER sealed into quarantine
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_16_defer_quarantine_sealed(engine, cade_id):
    """T230-CAVE-16: CAVE-QUARANTINE-0 — DEFER verdict sealed into quarantine."""
    result = engine.execute(cade_id, "DEFER", "mut-defer", 0.48)
    assert result["verdict"] == "DEFER"
    assert result["state"] == QuarantineState.SEALED.value
    record = engine.get_record(result["record_id"])
    assert record is not None


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-17  CAVE-AUDIT-0: audit log grows with each operation
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_17_audit_log_grows(engine, cade_id):
    """T230-CAVE-17: CAVE-AUDIT-0 — audit log records every operation."""
    before = len(engine.audit_log())
    engine.execute(cade_id, "REJECT", "mut-audit", 0.20)
    after = len(engine.audit_log())
    assert after > before


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-18  CAVE-AUDIT-0: audit entries are HMAC-chained
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_18_audit_entries_have_hashes(engine, cade_id):
    """T230-CAVE-18: CAVE-AUDIT-0 — each audit entry has entry_hash."""
    engine.execute(cade_id, "HOLD", "mut-ah", 0.60)
    for entry in engine.audit_log():
        assert "entry_hash" in entry
        assert len(entry["entry_hash"]) == 64


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-19  CAVE-ORIGIN-0: whitespace-only cade_record_id rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_19_origin_whitespace_cade_id(engine):
    """T230-CAVE-19: CAVE-ORIGIN-0 — whitespace-only cade_record_id raises OriginViolation."""
    with pytest.raises(OriginViolation):
        engine.execute("   ", "REJECT", "mut-ws", 0.20)


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-20  CAVE-ORIGIN-0: empty mutation_ref rejected
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_20_origin_empty_mutation_ref(engine, cade_id):
    """T230-CAVE-20: CAVE-ORIGIN-0 — empty mutation_ref raises OriginViolation."""
    with pytest.raises(OriginViolation):
        engine.execute(cade_id, "REJECT", "", 0.20)


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-21  Pending triggers list only includes PENDING triggers
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_21_pending_triggers_filter(engine, cade_id):
    """T230-CAVE-21: pending_triggers() returns only PENDING state triggers."""
    r1 = engine.execute(f"{cade_id}-A", "HOLD", "mut-p1", 0.60)
    r2 = engine.execute(f"{cade_id}-B", "HOLD", "mut-p2", 0.62)
    engine.complete_reeval(r1["reeval_trigger_id"], 0.85)
    pending = engine.pending_triggers()
    ids = [t.trigger_id for t in pending]
    assert r2["reeval_trigger_id"] in ids
    assert r1["reeval_trigger_id"] not in ids


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-22  Quarantined records list only includes SEALED records
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_22_quarantined_filter(engine, cade_id):
    """T230-CAVE-22: quarantined_records() returns only SEALED state records."""
    r1 = engine.execute(f"{cade_id}-X", "REJECT", "mut-q1", 0.20)
    r2 = engine.execute(f"{cade_id}-Y", "REJECT", "mut-q2", 0.22)
    engine.release_quarantine(r1["record_id"], "DUSTIN L. REID", "test release")
    sealed = [r.record_id for r in engine.quarantined_records()]
    assert r2["record_id"] in sealed
    assert r1["record_id"] not in sealed


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-23  Status endpoint returns correct metadata
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_23_status_metadata(engine):
    """T230-CAVE-23: status() returns correct module metadata."""
    s = engine.status()
    assert s["module"] == "CAVE"
    assert s["innov"] == "INNOV-135"
    assert s["phase"] == 230


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-24  API: POST /cave/execute REJECT returns 200
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_24_api_execute_reject():
    """T230-CAVE-24: POST /cave/execute with REJECT returns 200."""
    resp = _client.post("/cave/execute", json={
        "cade_record_id": "CADE-API-001",
        "verdict": "REJECT",
        "mutation_ref": "mut-api-01",
        "chi_score": 0.30,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "REJECT"
    assert data["status"] == "VERDICT_EXECUTED"


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-25  API: POST /cave/execute HOLD returns reeval_trigger_id
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_25_api_execute_hold():
    """T230-CAVE-25: POST /cave/execute with HOLD returns reeval_trigger_id."""
    resp = _client.post("/cave/execute", json={
        "cade_record_id": "CADE-API-002",
        "verdict": "HOLD",
        "mutation_ref": "mut-api-02",
        "chi_score": 0.65,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "reeval_trigger_id" in data


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-26  API: POST /cave/execute unknown verdict returns 422
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_26_api_execute_unknown_verdict():
    """T230-CAVE-26: POST /cave/execute with unknown verdict returns 422."""
    resp = _client.post("/cave/execute", json={
        "cade_record_id": "CADE-API-003",
        "verdict": "APPROVE",
        "mutation_ref": "mut-api-03",
        "chi_score": 0.50,
    })
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-27  API: GET /cave/records lists records
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_27_api_list_records():
    """T230-CAVE-27: GET /cave/records returns record list."""
    resp = _client.get("/cave/records")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "count" in data


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-28  API: GET /cave/verify-chain returns chain_intact=true
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_28_api_verify_chain():
    """T230-CAVE-28: GET /cave/verify-chain returns chain_intact true."""
    resp = _client.get("/cave/verify-chain")
    assert resp.status_code == 200
    assert resp.json()["chain_intact"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-29  API: GET /cave/status returns CAVE module metadata
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_29_api_status():
    """T230-CAVE-29: GET /cave/status returns correct module info."""
    resp = _client.get("/cave/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["module"] == "CAVE"
    assert data["innov"] == "INNOV-135"


# ═══════════════════════════════════════════════════════════════════════════════
# T230-CAVE-30  API: POST /cave/release/{record_id} with empty released_by → 403
# ═══════════════════════════════════════════════════════════════════════════════
def test_T230_CAVE_30_api_release_empty_human0():
    """T230-CAVE-30: POST /cave/release with empty released_by returns 403."""
    # First create a REJECT record
    exec_resp = _client.post("/cave/execute", json={
        "cade_record_id": "CADE-API-REL",
        "verdict": "REJECT",
        "mutation_ref": "mut-rel-api",
        "chi_score": 0.20,
    })
    record_id = exec_resp.json()["record_id"]
    # Attempt release with empty released_by
    rel_resp = _client.post(f"/cave/release/{record_id}", json={
        "released_by": "",
        "reason": "test",
    })
    assert rel_resp.status_code == 403
