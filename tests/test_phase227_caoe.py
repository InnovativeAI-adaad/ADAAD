# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase227_caoe.py
Phase 227 · INNOV-132 · CAOE — Constitutional Autonomous Outcome Evaluator
30-test acceptance suite · T227-CAOE-01 through T227-CAOE-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

import pytest
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_outcome_evaluator import (
    AcknowledgementStatus,
    CAOEEngine,
    CAOEViolation,
    ChainBreakError,
    CollectionError,
    EvaluationRecord,
    HUMAN0NotificationError,
    ImmutabilityViolation,
    OriginError,
    OutcomeClassification,
    OutcomeCollector,
    OutcomeEvaluator,
    OutcomeLedger,
    ScopeError,
    _hmac_verify,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _cape_record(
    record_id="exec-001",
    status="COMPLETED",
    stages=None,
    chi_score=0.85,
    decision_id="dec-001",
    synthesis_id="synth-001",
    mutation_ref="mut-ref-001",
    approved_by="DUSTIN-L-REID",
):
    return {
        "record_id": record_id,
        "entry_id": "entry-001",
        "decision_id": decision_id,
        "synthesis_id": synthesis_id,
        "chi_score": chi_score,
        "mutation_ref": mutation_ref,
        "approved_by": approved_by,
        "stages_completed": stages or ["VALIDATE", "STAGE", "EXECUTE", "SEAL", "RECORD"],
        "status": status,
        "executed_at": 1_700_000_000.0,
        "proof": "abc123",
        "prev_hmac": "CAPE-GENESIS",
        "hmac_seal": "seal-abc",
    }


@pytest.fixture
def engine():
    return CAOEEngine()


@pytest.fixture
def client():
    from app.api.caoe import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── T227-CAOE-01: Module imports cleanly ─────────────────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_01_imports():
    from dorkllm.constitutional_autonomous_outcome_evaluator import CAOEEngine
    assert CAOEEngine is not None


# ── T227-CAOE-02: CAOEEngine instantiates ────────────────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_02_engine_instantiates(engine):
    assert engine is not None


# ── T227-CAOE-03: OutcomeCollector accepts valid COMPLETED record ─────────────
@pytest.mark.phase227
def test_T227_CAOE_03_collector_valid(engine):
    rec = _cape_record()
    result = engine.collect(rec)
    assert result["record_id"] == "exec-001"


# ── T227-CAOE-04: CAOE-COLLECT-0 rejects non-COMPLETED status ────────────────
@pytest.mark.phase227
def test_T227_CAOE_04_collect_rejects_non_completed(engine):
    rec = _cape_record(status="PENDING")
    with pytest.raises(CollectionError):
        engine.collect(rec)


# ── T227-CAOE-05: CAOE-SCOPE-0 rejects missing pipeline stages ───────────────
@pytest.mark.phase227
def test_T227_CAOE_05_scope_rejects_missing_stages(engine):
    rec = _cape_record(stages=["VALIDATE", "STAGE", "EXECUTE"])
    with pytest.raises(ScopeError):
        engine.collect(rec)


# ── T227-CAOE-06: CAOE-ORIGIN-0 rejects empty execution_id ──────────────────
@pytest.mark.phase227
def test_T227_CAOE_06_origin_rejects_empty_id(engine):
    rec = _cape_record(record_id="")
    with pytest.raises(OriginError):
        engine.collect(rec)


# ── T227-CAOE-07: IMPROVED classification for delta_chi > 0.05 ───────────────
@pytest.mark.phase227
def test_T227_CAOE_07_improved_classification(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.90)
    assert result.classification == OutcomeClassification.IMPROVED


# ── T227-CAOE-08: NEUTRAL classification for |delta_chi| <= 0.05 ─────────────
@pytest.mark.phase227
def test_T227_CAOE_08_neutral_classification(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.82)
    assert result.classification == OutcomeClassification.NEUTRAL


# ── T227-CAOE-09: DEGRADED classification for delta_chi < -0.05 ──────────────
@pytest.mark.phase227
def test_T227_CAOE_09_degraded_classification(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.70)
    assert result.classification == OutcomeClassification.DEGRADED


# ── T227-CAOE-10: DEGRADED outcome sets FLAGGED ack_status ───────────────────
@pytest.mark.phase227
def test_T227_CAOE_10_degraded_sets_flagged(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.70)
    assert result.ack_status == AcknowledgementStatus.FLAGGED


# ── T227-CAOE-11: IMPROVED outcome sets PENDING ack_status ───────────────────
@pytest.mark.phase227
def test_T227_CAOE_11_improved_sets_pending(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.92)
    assert result.ack_status == AcknowledgementStatus.PENDING


# ── T227-CAOE-12: delta_chi computed correctly ───────────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_12_delta_chi_correct(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.90)
    assert abs(result.delta_chi - 0.10) < 1e-9


# ── T227-CAOE-13: EvaluationRecord sealed with hmac_seal ─────────────────────
@pytest.mark.phase227
def test_T227_CAOE_13_record_has_hmac_seal(engine):
    rec = _cape_record()
    result = engine.evaluate(rec, post_chi=0.88)
    assert result.hmac_seal and len(result.hmac_seal) == 64


# ── T227-CAOE-14: CAOE-CHAIN-0 verify_chain passes on clean ledger ───────────
@pytest.mark.phase227
def test_T227_CAOE_14_verify_chain_clean(engine):
    rec = _cape_record()
    engine.evaluate(rec, post_chi=0.88)
    assert engine.verify_chain() is True


# ── T227-CAOE-15: Multiple evaluations chain correctly ───────────────────────
@pytest.mark.phase227
def test_T227_CAOE_15_multi_eval_chain(engine):
    for i in range(5):
        rec = _cape_record(record_id=f"exec-{i:03d}")
        engine.evaluate(rec, post_chi=0.85 + i * 0.01)
    assert engine.verify_chain() is True
    assert len(engine.list_evaluations()) == 5


# ── T227-CAOE-16: CAOE-HUMAN0-0 blocks acknowledge with empty notified_by ────
@pytest.mark.phase227
def test_T227_CAOE_16_human0_blocks_empty_notified_by(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.70)
    with pytest.raises(HUMAN0NotificationError):
        engine.acknowledge(result.eval_id, notified_by="")


# ── T227-CAOE-17: acknowledge DEGRADED record transitions to ACKNOWLEDGED ─────
@pytest.mark.phase227
def test_T227_CAOE_17_acknowledge_degraded(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.70)
    acked = engine.acknowledge(result.eval_id, notified_by="DUSTIN-L-REID")
    assert acked.ack_status == AcknowledgementStatus.ACKNOWLEDGED
    assert acked.notified_by == "DUSTIN-L-REID"


# ── T227-CAOE-18: CAOE-IMMUT-0 blocks double-acknowledge ─────────────────────
@pytest.mark.phase227
def test_T227_CAOE_18_immut_blocks_double_acknowledge(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.70)
    engine.acknowledge(result.eval_id, notified_by="DUSTIN-L-REID")
    with pytest.raises(ImmutabilityViolation):
        engine.acknowledge(result.eval_id, notified_by="DUSTIN-L-REID")


# ── T227-CAOE-19: get_evaluation returns correct record ──────────────────────
@pytest.mark.phase227
def test_T227_CAOE_19_get_evaluation(engine):
    rec = _cape_record()
    result = engine.evaluate(rec, post_chi=0.88)
    fetched = engine.get_evaluation(result.eval_id)
    assert fetched is not None
    assert fetched.eval_id == result.eval_id


# ── T227-CAOE-20: get_evaluation returns None for unknown id ─────────────────
@pytest.mark.phase227
def test_T227_CAOE_20_get_evaluation_unknown(engine):
    assert engine.get_evaluation("nonexistent-id") is None


# ── T227-CAOE-21: audit log records all operations ───────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_21_audit_log_populated(engine):
    rec = _cape_record()
    engine.collect(rec)
    engine.evaluate(rec, post_chi=0.88)
    log = engine.audit_log()
    ops = [e.operation for e in log]
    assert "collect" in ops
    assert "evaluate" in ops


# ── T227-CAOE-22: audit log grows with acknowledge ───────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_22_audit_log_acknowledge(engine):
    rec = _cape_record(chi_score=0.80)
    result = engine.evaluate(rec, post_chi=0.70)
    engine.acknowledge(result.eval_id, notified_by="DUSTIN-L-REID")
    ops = [e.operation for e in engine.audit_log()]
    assert "acknowledge" in ops


# ── T227-CAOE-23: audit log grows with verify_chain ──────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_23_audit_log_verify(engine):
    engine.verify_chain()
    ops = [e.operation for e in engine.audit_log()]
    assert "verify_chain" in ops


# ── T227-CAOE-24: status returns correct engine metadata ─────────────────────
@pytest.mark.phase227
def test_T227_CAOE_24_status(engine):
    st = engine.status()
    assert st["engine"] == "CAOE"
    assert st["phase"] == 227
    assert st["governor"] == "DUSTIN L REID"


# ── T227-CAOE-25: status counts evaluations correctly ────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_25_status_counts(engine):
    engine.evaluate(_cape_record(record_id="e1"), post_chi=0.92)  # IMPROVED
    engine.evaluate(_cape_record(record_id="e2"), post_chi=0.82)  # NEUTRAL
    engine.evaluate(_cape_record(record_id="e3"), post_chi=0.70)  # DEGRADED
    st = engine.status()
    assert st["total_evaluations"] == 3
    assert st["classification_counts"]["IMPROVED"] == 1
    assert st["classification_counts"]["NEUTRAL"] == 1
    assert st["classification_counts"]["DEGRADED"] == 1
    assert st["flagged_degraded"] == 1


# ── T227-CAOE-26: CAOE-DETERM-0 identical inputs yield identical delta ────────
@pytest.mark.phase227
def test_T227_CAOE_26_determinism(engine):
    ev = OutcomeEvaluator()
    d1, c1 = ev.evaluate(0.80, 0.90)
    d2, c2 = ev.evaluate(0.80, 0.90)
    assert d1 == d2
    assert c1 == c2


# ── T227-CAOE-27: POST /caoe/evaluate returns 200 ────────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_27_api_evaluate(client):
    # Use chi_score=0.70, post_chi=0.90 → delta=0.20 → IMPROVED (unambiguous)
    resp = client.post("/caoe/evaluate", json={
        "execution_record": _cape_record(record_id="exec-api-027", chi_score=0.70),
        "post_chi": 0.90,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "eval_id" in data
    assert data["classification"] == "IMPROVED"


# ── T227-CAOE-28: POST /caoe/collect returns 200 ─────────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_28_api_collect(client):
    resp = client.post("/caoe/collect", json={"execution_record": _cape_record()})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── T227-CAOE-29: GET /caoe/status returns 200 ───────────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_29_api_status(client):
    resp = client.get("/caoe/status")
    assert resp.status_code == 200
    assert resp.json()["engine"] == "CAOE"


# ── T227-CAOE-30: GET /caoe/verify-chain returns 200 ─────────────────────────
@pytest.mark.phase227
def test_T227_CAOE_30_api_verify_chain(client):
    resp = client.get("/caoe/verify-chain")
    assert resp.status_code == 200
    assert resp.json()["chain_intact"] is True
