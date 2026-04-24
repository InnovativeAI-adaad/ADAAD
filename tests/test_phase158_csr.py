# SPDX-License-Identifier: Apache-2.0
"""Phase 158 — INNOV-64 · CSR — Constitutional Self-Repair Engine
Acceptance test suite T158-CSR-01 .. T158-CSR-30  (30/30 required)
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_snapshot(score: float):
    """Construct a minimal HealthSnapshot-compatible object via the real class."""
    from dorkllm.governance_health import HealthSnapshot, HealthBand

    def band_for(s: float):
        if s >= 0.90: return HealthBand.NOMINAL
        if s >= 0.75: return HealthBand.CAUTION
        if s >= 0.50: return HealthBand.ELEVATED
        return HealthBand.CRITICAL

    sub = {
        "pressure":  score,
        "throttle":  score,
        "anomaly":   score,
        "gate":      score,
        "stability": score,
    }
    return HealthSnapshot(
        score=score,
        band=band_for(score),
        sub_scores=sub,
        event_count=5,
        advisory="synthetic snapshot" if score < 0.90 else None,
    )


@pytest.fixture
def tmp_hub(tmp_path):
    """Return a CGTH hub backed by a temporary ledger file."""
    from dorkllm.telemetry_hub import ConstitutionalGovernanceTelemetryHub
    return ConstitutionalGovernanceTelemetryHub(ledger_path=tmp_path / "test_cgth.jsonl")


@pytest.fixture
def csr(tmp_hub):
    """Return a CSR engine backed by the temporary hub."""
    from dorkllm.self_repair import ConstitutionalSelfRepairEngine
    return ConstitutionalSelfRepairEngine(hub=tmp_hub)


# ---------------------------------------------------------------------------
# T158-CSR-01  module imports cleanly
# ---------------------------------------------------------------------------
def test_01_module_imports():
    from dorkllm import self_repair
    assert hasattr(self_repair, "ConstitutionalSelfRepairEngine")
    assert hasattr(self_repair, "RepairProposal")
    assert hasattr(self_repair, "RepairRun")
    assert hasattr(self_repair, "repair_now")
    assert hasattr(self_repair, "get_csr")


# ---------------------------------------------------------------------------
# T158-CSR-02  RepairAction enum coverage
# ---------------------------------------------------------------------------
def test_02_repair_action_enum():
    from dorkllm.self_repair import RepairAction
    values = {a.value for a in RepairAction}
    assert "ESCALATE_TO_HUMAN0" in values
    assert "NO_ACTION" in values
    assert "REDUCE_MUTATION_RATE" in values


# ---------------------------------------------------------------------------
# T158-CSR-03  RepairPriority enum coverage
# ---------------------------------------------------------------------------
def test_03_repair_priority_enum():
    from dorkllm.self_repair import RepairPriority
    assert {p.value for p in RepairPriority} == {"LOW", "STANDARD", "URGENT"}


# ---------------------------------------------------------------------------
# T158-CSR-04  RepairProposal proposal_id is deterministic (CSR-DETERM-0)
# ---------------------------------------------------------------------------
def test_04_proposal_id_deterministic():
    from dorkllm.self_repair import RepairProposal, RepairAction, RepairPriority
    p1 = RepairProposal(RepairAction.REDUCE_MUTATION_RATE, "pressure", "test", RepairPriority.LOW)
    p2 = RepairProposal(RepairAction.REDUCE_MUTATION_RATE, "pressure", "test", RepairPriority.LOW)
    assert p1.proposal_id == p2.proposal_id


# ---------------------------------------------------------------------------
# T158-CSR-05  RepairProposal proposal_id changes with action
# ---------------------------------------------------------------------------
def test_05_proposal_id_changes_with_action():
    from dorkllm.self_repair import RepairProposal, RepairAction, RepairPriority
    p1 = RepairProposal(RepairAction.REDUCE_MUTATION_RATE, "pressure", "test", RepairPriority.LOW)
    p2 = RepairProposal(RepairAction.ESCALATE_TO_HUMAN0,  "pressure", "test", RepairPriority.LOW)
    assert p1.proposal_id != p2.proposal_id


# ---------------------------------------------------------------------------
# T158-CSR-06  RepairProposal to_dict contains required keys
# ---------------------------------------------------------------------------
def test_06_proposal_to_dict_keys():
    from dorkllm.self_repair import RepairProposal, RepairAction, RepairPriority
    p = RepairProposal(RepairAction.AUDIT_GATE_CONFIGURATION, "gate", "r", RepairPriority.STANDARD)
    d = p.to_dict()
    for key in ("proposal_id", "action", "target", "rationale", "priority", "evidence"):
        assert key in d


# ---------------------------------------------------------------------------
# T158-CSR-07  NOMINAL band produces no proposals
# ---------------------------------------------------------------------------
def test_07_nominal_no_proposals(csr):
    snap = _make_snapshot(0.95)
    run = csr.generate(snap)
    assert len(run.proposals) == 0


# ---------------------------------------------------------------------------
# T158-CSR-08  NOMINAL band returns NOMINAL RepairRun
# ---------------------------------------------------------------------------
def test_08_nominal_run_band(csr):
    from dorkllm.governance_health import HealthBand
    snap = _make_snapshot(0.95)
    run = csr.generate(snap)
    assert run.band == HealthBand.NOMINAL


# ---------------------------------------------------------------------------
# T158-CSR-09  CAUTION band produces proposals
# ---------------------------------------------------------------------------
def test_09_caution_produces_proposals(csr):
    snap = _make_snapshot(0.80)
    run = csr.generate(snap)
    assert len(run.proposals) > 0


# ---------------------------------------------------------------------------
# T158-CSR-10  ELEVATED band produces proposals
# ---------------------------------------------------------------------------
def test_10_elevated_produces_proposals(csr):
    snap = _make_snapshot(0.60)
    run = csr.generate(snap)
    assert len(run.proposals) > 0


# ---------------------------------------------------------------------------
# T158-CSR-11  CRITICAL band produces proposals
# ---------------------------------------------------------------------------
def test_11_critical_produces_proposals(csr):
    snap = _make_snapshot(0.30)
    run = csr.generate(snap)
    assert len(run.proposals) > 0


# ---------------------------------------------------------------------------
# T158-CSR-12  CRITICAL band includes ESCALATE_TO_HUMAN0 proposal
# ---------------------------------------------------------------------------
def test_12_critical_escalation_proposal(csr):
    from dorkllm.self_repair import RepairAction
    snap = _make_snapshot(0.30)
    run = csr.generate(snap)
    actions = [p.action for p in run.proposals]
    assert RepairAction.ESCALATE_TO_HUMAN0 in actions


# ---------------------------------------------------------------------------
# T158-CSR-13  CRITICAL band emits alert to CGTH (CSR-CRITICAL-0)
# ---------------------------------------------------------------------------
def test_13_critical_alert_emitted(csr, tmp_hub):
    from dorkllm.telemetry_hub import CGTHEventType
    snap = _make_snapshot(0.30)
    run = csr.generate(snap)
    assert run.alert_emitted is True
    alerts = tmp_hub.query(event_type=CGTHEventType.HUMAN0_AUTHORISATION)
    assert len(alerts) >= 1


# ---------------------------------------------------------------------------
# T158-CSR-14  CAUTION band does NOT emit alert
# ---------------------------------------------------------------------------
def test_14_caution_no_alert(csr, tmp_hub):
    from dorkllm.telemetry_hub import CGTHEventType
    snap = _make_snapshot(0.80)
    run = csr.generate(snap)
    assert run.alert_emitted is False
    alerts = tmp_hub.query(event_type=CGTHEventType.HUMAN0_AUTHORISATION)
    assert len(alerts) == 0


# ---------------------------------------------------------------------------
# T158-CSR-15  CAUTION band emits CSR_PROPOSAL event (CSR-EMIT-0)
# ---------------------------------------------------------------------------
def test_15_caution_emits_proposal_event(csr, tmp_hub):
    from dorkllm.telemetry_hub import CGTHEventType
    snap = _make_snapshot(0.80)
    csr.generate(snap)
    events = tmp_hub.query(event_type=CGTHEventType.MUTATION_PROPOSED)
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# T158-CSR-16  NOMINAL band emits nothing to CGTH
# ---------------------------------------------------------------------------
def test_16_nominal_emits_nothing(csr, tmp_hub):
    snap = _make_snapshot(0.95)
    csr.generate(snap)
    assert len(tmp_hub.query()) == 0


# ---------------------------------------------------------------------------
# T158-CSR-17  proposal count bounded by MAX_PROPOSALS_PER_RUN (CSR-BOUNDED-0)
# ---------------------------------------------------------------------------
def test_17_bounded_proposals(tmp_hub):
    from dorkllm.self_repair import ConstitutionalSelfRepairEngine
    csr_tight = ConstitutionalSelfRepairEngine(hub=tmp_hub, max_proposals=3)
    snap = _make_snapshot(0.20)
    run = csr_tight.generate(snap)
    assert len(run.proposals) <= 3


# ---------------------------------------------------------------------------
# T158-CSR-18  pressure sub-index degraded → REDUCE_MUTATION_RATE proposed
# ---------------------------------------------------------------------------
def test_18_pressure_degraded_proposals():
    from dorkllm.self_repair import _proposals_for_pressure, RepairAction
    from dorkllm.governance_health import HealthBand
    props = _proposals_for_pressure(0.40, HealthBand.ELEVATED)
    actions = [p.action for p in props]
    assert RepairAction.REDUCE_MUTATION_RATE in actions


# ---------------------------------------------------------------------------
# T158-CSR-19  throttle sub-index degraded → INCREASE_THROTTLE_FLOOR proposed
# ---------------------------------------------------------------------------
def test_19_throttle_degraded_proposals():
    from dorkllm.self_repair import _proposals_for_throttle, RepairAction
    from dorkllm.governance_health import HealthBand
    props = _proposals_for_throttle(0.50, HealthBand.ELEVATED)
    actions = [p.action for p in props]
    assert RepairAction.INCREASE_THROTTLE_FLOOR in actions


# ---------------------------------------------------------------------------
# T158-CSR-20  anomaly sub-index degraded → FLUSH_ANOMALY_BACKLOG proposed
# ---------------------------------------------------------------------------
def test_20_anomaly_degraded_proposals():
    from dorkllm.self_repair import _proposals_for_anomaly, RepairAction
    from dorkllm.governance_health import HealthBand
    props = _proposals_for_anomaly(0.45, HealthBand.ELEVATED)
    actions = [p.action for p in props]
    assert RepairAction.FLUSH_ANOMALY_BACKLOG in actions


# ---------------------------------------------------------------------------
# T158-CSR-21  gate sub-index degraded → AUDIT_GATE_CONFIGURATION proposed
# ---------------------------------------------------------------------------
def test_21_gate_degraded_proposals():
    from dorkllm.self_repair import _proposals_for_gate, RepairAction
    from dorkllm.governance_health import HealthBand
    props = _proposals_for_gate(0.50, HealthBand.ELEVATED)
    actions = [p.action for p in props]
    assert RepairAction.AUDIT_GATE_CONFIGURATION in actions


# ---------------------------------------------------------------------------
# T158-CSR-22  stability sub-index degraded → REVIEW_CIRCUIT_BREAKER proposed
# ---------------------------------------------------------------------------
def test_22_stability_degraded_proposals():
    from dorkllm.self_repair import _proposals_for_stability, RepairAction
    from dorkllm.governance_health import HealthBand
    props = _proposals_for_stability(0.60, HealthBand.ELEVATED)
    actions = [p.action for p in props]
    assert RepairAction.REVIEW_CIRCUIT_BREAKER in actions


# ---------------------------------------------------------------------------
# T158-CSR-23  healthy sub-index returns empty proposals list
# ---------------------------------------------------------------------------
def test_23_healthy_subindex_no_proposals():
    from dorkllm.self_repair import _proposals_for_pressure
    from dorkllm.governance_health import HealthBand
    props = _proposals_for_pressure(0.95, HealthBand.NOMINAL)
    assert props == []


# ---------------------------------------------------------------------------
# T158-CSR-24  RepairRun to_dict contains required keys
# ---------------------------------------------------------------------------
def test_24_repair_run_to_dict(csr):
    snap = _make_snapshot(0.70)
    run = csr.generate(snap)
    d = run.to_dict()
    for key in ("band", "ghi_score", "proposal_count", "alert_emitted", "proposals"):
        assert key in d


# ---------------------------------------------------------------------------
# T158-CSR-25  proposal_count in to_dict matches len(proposals)
# ---------------------------------------------------------------------------
def test_25_run_proposal_count_matches(csr):
    snap = _make_snapshot(0.60)
    run = csr.generate(snap)
    d = run.to_dict()
    assert d["proposal_count"] == len(run.proposals)


# ---------------------------------------------------------------------------
# T158-CSR-26  CRITICAL band URGENT priority on escalation proposal
# ---------------------------------------------------------------------------
def test_26_critical_escalation_is_urgent(csr):
    from dorkllm.self_repair import RepairAction, RepairPriority
    snap = _make_snapshot(0.25)
    run = csr.generate(snap)
    escalation = [p for p in run.proposals if p.action == RepairAction.ESCALATE_TO_HUMAN0]
    assert len(escalation) >= 1
    assert escalation[0].priority == RepairPriority.URGENT


# ---------------------------------------------------------------------------
# T158-CSR-27  quick_status returns healthy=True for NOMINAL
# ---------------------------------------------------------------------------
def test_27_quick_status_nominal(csr):
    with patch("dorkllm.self_repair.score_now", return_value=_make_snapshot(0.92)):
        status = csr.quick_status()
    assert status["healthy"] is True
    assert status["band"] == "NOMINAL"


# ---------------------------------------------------------------------------
# T158-CSR-28  quick_status returns healthy=False for ELEVATED
# ---------------------------------------------------------------------------
def test_28_quick_status_elevated(csr):
    with patch("dorkllm.self_repair.score_now", return_value=_make_snapshot(0.60)):
        status = csr.quick_status()
    assert status["healthy"] is False
    assert status["band"] == "ELEVATED"


# ---------------------------------------------------------------------------
# T158-CSR-29  REST router has expected routes
# ---------------------------------------------------------------------------
def test_29_rest_router_routes():
    from app.api.self_repair import router
    if router is None:
        pytest.skip("FastAPI not available")
    paths = {r.path for r in router.routes}
    assert "/api/governance/repair/status" in paths
    assert "/api/governance/repair/run" in paths
    assert "/api/governance/repair/actions" in paths


# ---------------------------------------------------------------------------
# T158-CSR-30  module-level repair_now returns RepairRun
# ---------------------------------------------------------------------------
def test_30_module_repair_now():
    from dorkllm.self_repair import repair_now, RepairRun
    with patch("dorkllm.self_repair.score_now", return_value=_make_snapshot(0.92)):
        run = repair_now()
    assert isinstance(run, RepairRun)
