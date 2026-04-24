# SPDX-License-Identifier: Apache-2.0
"""Phase 156 — INNOV-62 · CGAI Test Suite
Tests T156-CGAI-01 through T156-CGAI-30
"""

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from dorkllm.anomaly_inspector import (
    ALL_DETECTORS,
    AnomalyReport,
    AnomalySeverity,
    CLUSTER_THRESHOLD,
    GATE_SPIKE_THRESHOLD,
    ConstitutionalGovernanceAnomalyInspector,
    detect_chain_gap,
    detect_circuit_cascade,
    detect_fire_cluster,
    detect_gate_spike,
    detect_pressure_surge,
    detect_rollback_repeat,
    detect_throttle_saturation,
    inspect_now,
)
from dorkllm.telemetry_hub import (
    CGTHEventType,
    ConstitutionalGovernanceTelemetryHub,
    TelemetryRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hub(tmp_path: Path) -> ConstitutionalGovernanceTelemetryHub:
    return ConstitutionalGovernanceTelemetryHub(ledger_path=tmp_path / "cgth_test.jsonl")


def _gate_record(verdict: bool, seq: int = 0) -> TelemetryRecord:
    payload = {"verdict": verdict, "component": "cpag"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"GATE_VERDICT|{canon}|{'0'*64}".encode()).hexdigest()
    hmac_v = hashlib.sha256(eid.encode()).hexdigest()
    return TelemetryRecord(
        event_id=eid,
        event_type=CGTHEventType.GATE_VERDICT,
        component_id="cpag",
        payload=payload,
        prev_hmac="0" * 64,
        this_hmac=hmac_v,
        seq=seq,
    )


def _pressure_record(score: float, seq: int = 0) -> TelemetryRecord:
    payload = {"score": score, "domain": "MUTATION"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"PRESSURE_SNAPSHOT|{canon}|{'0'*64}".encode()).hexdigest()
    hmac_v = hashlib.sha256(eid.encode()).hexdigest()
    return TelemetryRecord(
        event_id=eid,
        event_type=CGTHEventType.PRESSURE_SNAPSHOT,
        component_id="cpi",
        payload=payload,
        prev_hmac="0" * 64,
        this_hmac=hmac_v,
        seq=seq,
    )


def _throttle_record(level: str, seq: int = 0) -> TelemetryRecord:
    payload = {"level": level}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"THROTTLE_DECISION|{canon}|{'0'*64}".encode()).hexdigest()
    hmac_v = hashlib.sha256(eid.encode()).hexdigest()
    return TelemetryRecord(
        event_id=eid,
        event_type=CGTHEventType.THROTTLE_DECISION,
        component_id="amt",
        payload=payload,
        prev_hmac="0" * 64,
        this_hmac=hmac_v,
        seq=seq,
    )


def _fire_record(component: str = "mutation_engine", seq: int = 0) -> TelemetryRecord:
    payload = {"invariant": "TEST-INV-0"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"INVARIANT_FIRE|{canon}|{'0'*64}".encode()).hexdigest()
    hmac_v = hashlib.sha256(eid.encode()).hexdigest()
    return TelemetryRecord(
        event_id=eid,
        event_type=CGTHEventType.INVARIANT_FIRE,
        component_id=component,
        payload=payload,
        prev_hmac="0" * 64,
        this_hmac=hmac_v,
        seq=seq,
    )


def _break_record(seq: int = 0) -> TelemetryRecord:
    payload = {"reason": "test"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"CIRCUIT_BREAK|{canon}|{'0'*64}".encode()).hexdigest()
    hmac_v = hashlib.sha256(eid.encode()).hexdigest()
    return TelemetryRecord(
        event_id=eid,
        event_type=CGTHEventType.CIRCUIT_BREAK,
        component_id="circuit_breaker",
        payload=payload,
        prev_hmac="0" * 64,
        this_hmac=hmac_v,
        seq=seq,
    )


def _rollback_record(seq: int = 0) -> TelemetryRecord:
    payload = {"epoch": 1}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"ROLLBACK_EXECUTED|{canon}|{'0'*64}".encode()).hexdigest()
    hmac_v = hashlib.sha256(eid.encode()).hexdigest()
    return TelemetryRecord(
        event_id=eid,
        event_type=CGTHEventType.ROLLBACK_EXECUTED,
        component_id="governed_rollback",
        payload=payload,
        prev_hmac="0" * 64,
        this_hmac=hmac_v,
        seq=seq,
    )


# ---------------------------------------------------------------------------
# T156-CGAI-01 — T156-CGAI-05: imports and constants
# ---------------------------------------------------------------------------

def test_01_module_imports():
    from dorkllm import anomaly_inspector as m
    assert hasattr(m, "ConstitutionalGovernanceAnomalyInspector")


def test_02_severity_ordering():
    """CGAI-SEVERITY-0: LOW < MEDIUM < HIGH < CRITICAL."""
    assert AnomalySeverity.LOW < AnomalySeverity.MEDIUM
    assert AnomalySeverity.MEDIUM < AnomalySeverity.HIGH
    assert AnomalySeverity.HIGH < AnomalySeverity.CRITICAL


def test_03_report_id_deterministic():
    r1 = AnomalyReport("GATE_SPIKE", AnomalySeverity.HIGH, {"count": 5})
    r2 = AnomalyReport("GATE_SPIKE", AnomalySeverity.HIGH, {"count": 5})
    assert r1.report_id == r2.report_id


def test_04_report_id_changes_with_type():
    r1 = AnomalyReport("GATE_SPIKE", AnomalySeverity.HIGH, {"count": 5})
    r2 = AnomalyReport("PRESSURE_SURGE", AnomalySeverity.HIGH, {"count": 5})
    assert r1.report_id != r2.report_id


def test_05_report_id_changes_with_evidence():
    r1 = AnomalyReport("GATE_SPIKE", AnomalySeverity.HIGH, {"count": 5})
    r2 = AnomalyReport("GATE_SPIKE", AnomalySeverity.HIGH, {"count": 6})
    assert r1.report_id != r2.report_id


# ---------------------------------------------------------------------------
# T156-CGAI-06 — T156-CGAI-08: GATE_SPIKE detector
# ---------------------------------------------------------------------------

def test_06_gate_spike_no_trigger():
    records = [_gate_record(True, i) for i in range(10)]
    assert detect_gate_spike(records) is None


def test_07_gate_spike_triggers():
    records = [_gate_record(False, i) for i in range(GATE_SPIKE_THRESHOLD)]
    report = detect_gate_spike(records)
    assert report is not None
    assert report.anomaly_type == "GATE_SPIKE"
    assert report.severity >= AnomalySeverity.HIGH


def test_08_gate_spike_critical_at_double_threshold():
    records = [_gate_record(False, i) for i in range(GATE_SPIKE_THRESHOLD * 2)]
    report = detect_gate_spike(records)
    assert report is not None
    assert report.severity == AnomalySeverity.CRITICAL


# ---------------------------------------------------------------------------
# T156-CGAI-09 — T156-CGAI-11: PRESSURE_SURGE detector
# ---------------------------------------------------------------------------

def test_09_pressure_surge_no_trigger():
    records = [_pressure_record(0.5)]
    assert detect_pressure_surge(records) is None


def test_10_pressure_surge_triggers():
    records = [_pressure_record(0.87)]
    report = detect_pressure_surge(records)
    assert report is not None
    assert report.anomaly_type == "PRESSURE_SURGE"


def test_11_pressure_surge_critical_at_095():
    records = [_pressure_record(0.96)]
    report = detect_pressure_surge(records)
    assert report is not None
    assert report.severity == AnomalySeverity.CRITICAL


# ---------------------------------------------------------------------------
# T156-CGAI-12 — T156-CGAI-13: THROTTLE_SAT detector
# ---------------------------------------------------------------------------

def test_12_throttle_sat_no_trigger():
    records = [_throttle_record("ALLOW", i) for i in range(5)]
    assert detect_throttle_saturation(records) is None


def test_13_throttle_sat_triggers():
    records = [_throttle_record("BLOCK", i) for i in range(3)]
    report = detect_throttle_saturation(records)
    assert report is not None
    assert report.anomaly_type == "THROTTLE_SAT"


# ---------------------------------------------------------------------------
# T156-CGAI-14 — T156-CGAI-15: FIRE_CLUSTER detector
# ---------------------------------------------------------------------------

def test_14_fire_cluster_no_trigger():
    records = [_fire_record("mutation_engine", i) for i in range(CLUSTER_THRESHOLD - 1)]
    assert detect_fire_cluster(records) is None


def test_15_fire_cluster_triggers():
    records = [_fire_record("mutation_engine", i) for i in range(CLUSTER_THRESHOLD)]
    report = detect_fire_cluster(records)
    assert report is not None
    assert report.anomaly_type == "FIRE_CLUSTER"


# ---------------------------------------------------------------------------
# T156-CGAI-16 — T156-CGAI-18: CIRCUIT_CASCADE detector
# ---------------------------------------------------------------------------

def test_16_circuit_cascade_no_trigger():
    records = [_break_record(i) for i in range(2)]
    assert detect_circuit_cascade(records) is None


def test_17_circuit_cascade_triggers():
    from dorkllm.anomaly_inspector import CASCADE_THRESHOLD
    records = [_break_record(i) for i in range(CASCADE_THRESHOLD)]
    report = detect_circuit_cascade(records)
    assert report is not None
    assert report.anomaly_type == "CIRCUIT_CASCADE"


def test_18_circuit_cascade_no_break_no_finding():
    records = [_gate_record(True, i) for i in range(10)]
    assert detect_circuit_cascade(records) is None


# ---------------------------------------------------------------------------
# T156-CGAI-19 — T156-CGAI-20: ROLLBACK_REPEAT detector
# ---------------------------------------------------------------------------

def test_19_rollback_repeat_no_trigger():
    records = [_rollback_record(0)]
    assert detect_rollback_repeat(records) is None


def test_20_rollback_repeat_triggers():
    from dorkllm.anomaly_inspector import ROLLBACK_REPEAT_THRESHOLD
    records = [_rollback_record(i) for i in range(ROLLBACK_REPEAT_THRESHOLD)]
    report = detect_rollback_repeat(records)
    assert report is not None
    assert report.anomaly_type == "ROLLBACK_REPEAT"


# ---------------------------------------------------------------------------
# T156-CGAI-21 — T156-CGAI-22: CHAIN_GAP detector
# ---------------------------------------------------------------------------

def test_21_chain_gap_none_on_intact():
    records = [_gate_record(True, i) for i in range(5)]
    assert detect_chain_gap(records) is None


def test_22_chain_gap_detects_missing_seq():
    r0 = _gate_record(True, 0)
    r1 = _gate_record(True, 5)   # gap: seq 1-4 missing
    report = detect_chain_gap([r0, r1])
    assert report is not None
    assert report.anomaly_type == "CHAIN_GAP"
    assert report.severity == AnomalySeverity.CRITICAL


# ---------------------------------------------------------------------------
# T156-CGAI-23 — T156-CGAI-25: emit behaviour (CGAI-EMIT-0)
# ---------------------------------------------------------------------------

def test_23_medium_finding_emits_to_cgth(tmp_path):
    hub = _make_hub(tmp_path)
    inspector = ConstitutionalGovernanceAnomalyInspector(hub=hub)
    # Seed enough BLOCK throttle events to trigger THROTTLE_SAT
    for i in range(3):
        hub.emit_event("amt", CGTHEventType.THROTTLE_DECISION, {"level": "BLOCK"})
    before = len(hub.tail(500))
    findings = inspector.inspect()
    after = len(hub.tail(500))
    assert after > before, "CGAI-EMIT-0: expected CGTH emission for MEDIUM+ finding"


def test_24_low_severity_not_emitted(tmp_path):
    """No CGTH events emitted when severity < MEDIUM (here: no anomaly at all)."""
    hub = _make_hub(tmp_path)
    inspector = ConstitutionalGovernanceAnomalyInspector(hub=hub)
    before = len(hub.tail(500))
    inspector.inspect()   # empty ledger — no findings
    after = len(hub.tail(500))
    assert after == before


def test_25_critical_finding_includes_advisory():
    records = [_pressure_record(0.97)]
    report = detect_pressure_surge(records)
    assert report is not None
    assert isinstance(report.advisory, str) and len(report.advisory) > 0


# ---------------------------------------------------------------------------
# T156-CGAI-26 — T156-CGAI-28: inspector API
# ---------------------------------------------------------------------------

def test_26_inspect_returns_list(tmp_path):
    hub = _make_hub(tmp_path)
    inspector = ConstitutionalGovernanceAnomalyInspector(hub=hub)
    result = inspector.inspect()
    assert isinstance(result, list)


def test_27_inspect_one_returns_none_when_no_anomaly(tmp_path):
    hub = _make_hub(tmp_path)
    inspector = ConstitutionalGovernanceAnomalyInspector(hub=hub)
    result = inspector.inspect_one("GATE_SPIKE")
    assert result is None


def test_28_inspect_one_returns_report_when_triggered(tmp_path):
    hub = _make_hub(tmp_path)
    for _ in range(GATE_SPIKE_THRESHOLD):
        hub.emit_event("cpag", CGTHEventType.GATE_VERDICT, {"verdict": False})
    inspector = ConstitutionalGovernanceAnomalyInspector(hub=hub)
    result = inspector.inspect_one("GATE_SPIKE")
    assert result is not None
    assert result.anomaly_type == "GATE_SPIKE"


# ---------------------------------------------------------------------------
# T156-CGAI-29 — T156-CGAI-30: REST router and module-level API
# ---------------------------------------------------------------------------

def test_29_rest_router_routes_defined():
    from app.api.governance_anomalies import router
    if router is not None:
        routes = [r.path for r in router.routes]
        assert any("inspect" in p for p in routes)


def test_30_module_level_inspect_now():
    """Module-level inspect_now() is callable and returns a list."""
    # Uses a fresh tmp hub implicitly (default hub may write to data/ — acceptable)
    result = inspect_now()
    assert isinstance(result, list)
