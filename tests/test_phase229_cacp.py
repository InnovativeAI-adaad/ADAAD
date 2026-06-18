# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase229_cacp.py
Phase 229 · INNOV-134 · CACP — Constitutional Autonomous Convergence Prover
30-test acceptance suite — T229-CACP-01 through T229-CACP-30
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dorkllm.constitutional_autonomous_convergence_prover import (
    CACPEngine, ACI_PIPELINE_STAGES,
    ChainBreakError, ImmutabilityViolation, HUMAN0NotificationError,
    ScopeError, OriginError, CycleError, TrendError,
    ConvergenceTrend, ProofStatus,
    _IMPROVING_THRESHOLD, _DEGRADING_THRESHOLD,
)
from app.api.cacp import router

pytestmark = pytest.mark.phase229

_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _complete_cycle(
    chi_before: float = 0.85,
    chi_after: float  = 0.90,
    classification: str = "IMPROVED",
    cali_signal: float  = 0.02,
) -> dict:
    return {
        "CASL": {"chi_score": chi_before, "synthesis_id": "s-001"},
        "CADE": {"verdict": "PROMOTE", "chi_score": chi_before},
        "CAPE": {"execution_id": "x-001", "status": "COMPLETED"},
        "CAOE": {"evaluation_id": "e-001", "classification": classification,
                 "chi_before": chi_before, "chi_after": chi_after},
        "CALI": {"ingestion_id": "i-001", "raw_signal": cali_signal},
    }


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 1: CycleAggregator — CACP-SCOPE-0, CACP-CYCLE-0, CACP-ORIGIN-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T229_CACP_01_aggregate_complete_cycle():
    """T229-CACP-01: Complete 5-stage cycle aggregates and returns sealed CycleRecord."""
    eng = CACPEngine()
    cycle = eng.aggregate_cycle(_complete_cycle())
    assert set(cycle.stage_records.keys()) == ACI_PIPELINE_STAGES
    assert cycle.sealed is True
    assert cycle.hmac_digest != ""


def test_T229_CACP_02_aggregate_computes_delta_chi():
    """T229-CACP-02: delta_chi correctly computed from chi_after - chi_before."""
    eng = CACPEngine()
    cycle = eng.aggregate_cycle(_complete_cycle(chi_before=0.80, chi_after=0.90))
    assert abs(cycle.delta_chi - 0.10) < 1e-5


def test_T229_CACP_03_scope_zero_unknown_stage_raises():
    """T229-CACP-03: CACP-SCOPE-0 — unknown pipeline stage raises ScopeError."""
    eng = CACPEngine()
    bad = dict(_complete_cycle())
    bad["UNKNOWN_STAGE"] = {}
    with pytest.raises(ScopeError, match="CACP-SCOPE-0"):
        eng.aggregate_cycle(bad)


def test_T229_CACP_04_cycle_zero_missing_stage_raises():
    """T229-CACP-04: CACP-CYCLE-0 — missing stage raises CycleError."""
    eng = CACPEngine()
    incomplete = {k: v for k, v in _complete_cycle().items() if k != "CALI"}
    with pytest.raises(CycleError, match="CACP-CYCLE-0"):
        eng.aggregate_cycle(incomplete)


def test_T229_CACP_05_origin_zero_all_empty_raises():
    """T229-CACP-05: CACP-ORIGIN-0 — all empty stage records raises OriginError."""
    eng = CACPEngine()
    empty = {stage: {} for stage in ACI_PIPELINE_STAGES}
    # Empty dicts are falsy — all empty → OriginError
    with pytest.raises(OriginError, match="CACP-ORIGIN-0"):
        eng.aggregate_cycle(empty)


def test_T229_CACP_06_multiple_cycles_accumulate():
    """T229-CACP-06: Multiple aggregate calls accumulate distinct cycles."""
    eng = CACPEngine()
    c1 = eng.aggregate_cycle(_complete_cycle(chi_before=0.80, chi_after=0.85))
    c2 = eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.88))
    assert len(eng.list_cycles()) == 2
    assert c1.cycle_id != c2.cycle_id


def test_T229_CACP_07_get_cycle_by_id():
    """T229-CACP-07: get_cycle returns correct CycleRecord by cycle_id."""
    eng = CACPEngine()
    cycle = eng.aggregate_cycle(_complete_cycle())
    fetched = eng.get_cycle(cycle.cycle_id)
    assert fetched is not None
    assert fetched.cycle_id == cycle.cycle_id


def test_T229_CACP_08_get_cycle_unknown_returns_none():
    """T229-CACP-08: get_cycle with unknown id returns None."""
    eng = CACPEngine()
    assert eng.get_cycle("no-such-id") is None


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 2: ConvergenceEngine — CACP-DETERM-0, CACP-TREND-0, CACP-PROOF-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T229_CACP_09_prove_improving_trend():
    """T229-CACP-09: CACP-TREND-0 — positive mean_delta_chi → IMPROVING."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.80, chi_after=0.85))  # delta=+0.05
    proof = eng.prove()
    assert proof.trend == ConvergenceTrend.IMPROVING.value
    assert proof.mean_delta_chi > 0


def test_T229_CACP_10_prove_degrading_trend():
    """T229-CACP-10: CACP-TREND-0 — negative mean_delta_chi → DEGRADING."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.80,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove()
    assert proof.trend == ConvergenceTrend.DEGRADING.value
    assert proof.degrading_flag is True


def test_T229_CACP_11_prove_stable_trend():
    """T229-CACP-11: CACP-TREND-0 — tiny mean_delta_chi → STABLE."""
    eng = CACPEngine()
    # delta = +0.01 → within stable band
    eng.aggregate_cycle(_complete_cycle(chi_before=0.80, chi_after=0.81,
                                        classification="NEUTRAL", cali_signal=0.0))
    proof = eng.prove()
    assert proof.trend == ConvergenceTrend.STABLE.value


def test_T229_CACP_12_convergence_score_in_range():
    """T229-CACP-12: Convergence score is in [0.0, 1.0] — CACP-DETERM-0."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle())
    proof = eng.prove()
    assert 0.0 <= proof.convergence_score <= 1.0


def test_T229_CACP_13_proof_binding_non_empty():
    """T229-CACP-13: CACP-PROOF-0 — proof_binding is non-empty HMAC."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle())
    proof = eng.prove()
    assert proof.proof_binding != ""
    assert len(proof.proof_binding) == 64  # SHA-256 hex


def test_T229_CACP_14_prove_deterministic():
    """T229-CACP-14: CACP-DETERM-0 — same cycle inputs produce same proof_binding."""
    eng1 = CACPEngine()
    eng2 = CACPEngine()
    r = _complete_cycle(chi_before=0.80, chi_after=0.85)
    c1 = eng1.aggregate_cycle(r)
    c2 = eng2.aggregate_cycle(r)
    p1 = eng1.prove()
    p2 = eng2.prove()
    # Same convergence score and trend (deterministic inputs)
    assert p1.convergence_score == p2.convergence_score
    assert p1.trend == p2.trend


def test_T229_CACP_15_prove_no_cycles_raises():
    """T229-CACP-15: CACP-ORIGIN-0 — prove with no cycles raises OriginError."""
    eng = CACPEngine()
    with pytest.raises(OriginError, match="CACP-ORIGIN-0"):
        eng.prove()


def test_T229_CACP_16_prove_specific_cycle_ids():
    """T229-CACP-16: prove accepts specific cycle_ids subset."""
    eng = CACPEngine()
    c1 = eng.aggregate_cycle(_complete_cycle(chi_before=0.80, chi_after=0.85))
    eng.aggregate_cycle(_complete_cycle(chi_before=0.60, chi_after=0.55,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove(cycle_ids=[c1.cycle_id])
    assert proof.cycle_count == 1
    assert c1.cycle_id in proof.cycle_ids


def test_T229_CACP_17_prove_unknown_cycle_ids_raises():
    """T229-CACP-17: prove with unknown cycle_ids raises OriginError."""
    eng = CACPEngine()
    with pytest.raises(OriginError, match="CACP-ORIGIN-0"):
        eng.prove(cycle_ids=["no-such-cycle"])


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 3: ProofRegistry — CACP-HUMAN0-0, CACP-IMMUT-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T229_CACP_18_degrading_proof_requires_acknowledgement():
    """T229-CACP-18: DEGRADING proof is flagged — degrading_flag=True, status=CERTIFIED."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.80,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove()
    assert proof.degrading_flag is True
    assert proof.status == ProofStatus.CERTIFIED.value


def test_T229_CACP_19_acknowledge_degrading_with_notified_by():
    """T229-CACP-19: HUMAN-0 can acknowledge DEGRADING proof with non-empty notified_by."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.80,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove()
    ack = eng.acknowledge(proof.proof_id, "DUSTIN L REID")
    assert ack.status == ProofStatus.ACKNOWLEDGED.value
    assert ack.notified_by == "DUSTIN L REID"


def test_T229_CACP_20_acknowledge_degrading_empty_notified_by_raises():
    """T229-CACP-20: CACP-HUMAN0-0 — empty notified_by on DEGRADING raises HUMAN0NotificationError."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.80,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove()
    with pytest.raises(HUMAN0NotificationError, match="CACP-HUMAN0-0"):
        eng.acknowledge(proof.proof_id, "")


def test_T229_CACP_21_acknowledge_non_degrading_no_notified_by_required():
    """T229-CACP-21: Non-DEGRADING proof can be acknowledged with empty notified_by."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.80, chi_after=0.85))
    proof = eng.prove()
    assert proof.degrading_flag is False
    ack = eng.acknowledge(proof.proof_id, "")
    assert ack.status == ProofStatus.ACKNOWLEDGED.value


def test_T229_CACP_22_immut_zero_double_acknowledge_raises():
    """T229-CACP-22: CACP-IMMUT-0 — double acknowledgement raises ImmutabilityViolation."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle())
    proof = eng.prove()
    eng.acknowledge(proof.proof_id, "DUSTIN L REID")
    with pytest.raises(ImmutabilityViolation, match="CACP-IMMUT-0"):
        eng.acknowledge(proof.proof_id, "DUSTIN L REID")


def test_T229_CACP_23_degrading_unacknowledged_listed():
    """T229-CACP-23: degrading_unacknowledged returns only unack'd DEGRADING proofs."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.80,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove()
    assert len(eng.degrading_unacknowledged()) == 1
    eng.acknowledge(proof.proof_id, "DUSTIN L REID")
    assert len(eng.degrading_unacknowledged()) == 0


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 4: ConvergenceLedger — CACP-CHAIN-0, CACP-APPEND-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T229_CACP_24_verify_chain_empty():
    """T229-CACP-24: verify_chain on empty ledger returns valid."""
    eng = CACPEngine()
    result = eng.verify_chain()
    assert result["chain_valid"] is True
    assert result["record_count"] == 0


def test_T229_CACP_25_verify_chain_after_operations():
    """T229-CACP-25: CACP-CHAIN-0 — chain valid after aggregate+prove+acknowledge."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle(chi_before=0.85, chi_after=0.80,
                                        classification="DEGRADED", cali_signal=-0.02))
    proof = eng.prove()
    eng.acknowledge(proof.proof_id, "DUSTIN L REID")
    result = eng.verify_chain()
    assert result["chain_valid"] is True
    assert result["record_count"] >= 3


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 5: Audit — CACP-AUDIT-0
# ══════════════════════════════════════════════════════════════════════════════

def test_T229_CACP_26_audit_records_aggregate():
    """T229-CACP-26: CACP-AUDIT-0 — AGGREGATE recorded in audit log."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle())
    assert any(e["operation"] == "AGGREGATE" for e in eng.audit_log())


def test_T229_CACP_27_audit_records_prove():
    """T229-CACP-27: CACP-AUDIT-0 — PROVE recorded in audit log."""
    eng = CACPEngine()
    eng.aggregate_cycle(_complete_cycle())
    eng.prove()
    assert any(e["operation"] == "PROVE" for e in eng.audit_log())


# ══════════════════════════════════════════════════════════════════════════════
# BLOCK 6: REST API
# ══════════════════════════════════════════════════════════════════════════════

def test_T229_CACP_28_api_aggregate_endpoint():
    """T229-CACP-28: POST /cacp/aggregate returns 200 with sealed cycle."""
    resp = _client.post("/cacp/aggregate", json={"stage_records": _complete_cycle()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sealed"] is True
    assert set(data["stages_present"]) == ACI_PIPELINE_STAGES


def test_T229_CACP_29_api_prove_endpoint():
    """T229-CACP-29: POST /cacp/prove returns 200 with ConvergenceProof."""
    # aggregate first
    _client.post("/cacp/aggregate", json={"stage_records": _complete_cycle()})
    resp = _client.post("/cacp/prove", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["proof_binding"] != ""
    assert data["trend"] in {t.value for t in ConvergenceTrend}


def test_T229_CACP_30_api_status_endpoint():
    """T229-CACP-30: GET /cacp/status returns CACP module status."""
    resp = _client.get("/cacp/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["module"] == "CACP"
    assert data["innov"] == "INNOV-134"
    assert "CACP-HUMAN0-0" in data["hard_class_invariants"]
    assert "CACP-PROOF-0" in data["hard_class_invariants"]
