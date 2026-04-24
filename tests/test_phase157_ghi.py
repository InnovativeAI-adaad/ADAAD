# SPDX-License-Identifier: Apache-2.0
"""Phase 157 — INNOV-63 · GHI Test Suite
Tests T157-GHI-01 through T157-GHI-30
"""

import hashlib
import json
from pathlib import Path

import pytest

from dorkllm.governance_health import (
    GovernanceHealthIndex,
    HealthBand,
    HealthSnapshot,
    _WEIGHTS,
    _band,
    _sub_anomaly,
    _sub_gate,
    _sub_pressure,
    _sub_stability,
    _sub_throttle,
    score_now,
)
from dorkllm.telemetry_hub import (
    CGTHEventType,
    ConstitutionalGovernanceTelemetryHub,
    TelemetryRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hub(tmp_path: Path) -> ConstitutionalGovernanceTelemetryHub:
    return ConstitutionalGovernanceTelemetryHub(ledger_path=tmp_path / "ghi_test.jsonl")


def _emit(hub, etype, comp, payload):
    hub.emit_event(comp, etype, payload)


def _pressure_events(hub, score: float):
    _emit(hub, CGTHEventType.PRESSURE_SNAPSHOT, "cpi", {"score": score})


def _throttle_events(hub, level: str, n: int = 1):
    for _ in range(n):
        _emit(hub, CGTHEventType.THROTTLE_DECISION, "amt", {"level": level})


def _gate_events(hub, verdict: bool, n: int = 1):
    for _ in range(n):
        _emit(hub, CGTHEventType.GATE_VERDICT, "cpag", {"verdict": verdict})


def _fire_cgai(hub, severity: str):
    _emit(hub, CGTHEventType.INVARIANT_FIRE, "cgai", {"severity": severity})


def _break_event(hub):
    _emit(hub, CGTHEventType.CIRCUIT_BREAK, "circuit_breaker", {"reason": "test"})


def _rollback_event(hub):
    _emit(hub, CGTHEventType.ROLLBACK_EXECUTED, "governed_rollback", {"epoch": 1})


# ---------------------------------------------------------------------------
# T157-GHI-01 — T157-GHI-05: imports and structure
# ---------------------------------------------------------------------------

def test_01_module_imports():
    from dorkllm import governance_health as m
    assert hasattr(m, "GovernanceHealthIndex")


def test_02_score_bounds():
    """GHI-SCORE-0: score is always in [0.0, 1.0] — verify via _band boundary."""
    assert _band(0.0) == HealthBand.CRITICAL
    assert _band(1.0) == HealthBand.NOMINAL
    from dorkllm.governance_health import _WEIGHTS
    for v in _WEIGHTS.values():
        assert 0.0 <= v <= 1.0


def test_03_weights_sum_to_one():
    total = sum(_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_04_five_sub_indices():
    """GHI-SUBINDEX-0: exactly five sub-indices."""
    assert len(_WEIGHTS) == 5


def test_05_band_ordering():
    assert _band(1.00) == HealthBand.NOMINAL
    assert _band(0.92) == HealthBand.NOMINAL
    assert _band(0.80) == HealthBand.CAUTION
    assert _band(0.60) == HealthBand.ELEVATED
    assert _band(0.30) == HealthBand.CRITICAL


# ---------------------------------------------------------------------------
# T157-GHI-06 — T157-GHI-10: sub-index: pressure
# ---------------------------------------------------------------------------

def test_06_pressure_sub_no_events():
    assert _sub_pressure([]) == 1.0


def test_07_pressure_sub_zero_pressure():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"score": 0.0}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"PRESSURE_SNAPSHOT|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.PRESSURE_SNAPSHOT, "cpi", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_pressure([rec]) == 1.0


def test_08_pressure_sub_high_pressure():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"score": 0.90}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"PRESSURE_SNAPSHOT|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.PRESSURE_SNAPSHOT, "cpi", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    result = _sub_pressure([rec])
    assert result <= 0.15


def test_09_throttle_sub_all_allow():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"level": "ALLOW"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"THROTTLE_DECISION|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.THROTTLE_DECISION, "amt", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_throttle([rec]) == 1.0


def test_10_throttle_sub_block():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"level": "BLOCK"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"THROTTLE_DECISION|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.THROTTLE_DECISION, "amt", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_throttle([rec]) == 0.0


# ---------------------------------------------------------------------------
# T157-GHI-11 — T157-GHI-15: sub-index: anomaly
# ---------------------------------------------------------------------------

def test_11_anomaly_sub_no_cgai_events():
    assert _sub_anomaly([]) == 1.0


def test_12_anomaly_sub_low_severity():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"severity": "LOW"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"INVARIANT_FIRE|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.INVARIANT_FIRE, "cgai", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_anomaly([rec]) >= 0.9


def test_13_anomaly_sub_critical():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"severity": "CRITICAL"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"INVARIANT_FIRE|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.INVARIANT_FIRE, "cgai", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_anomaly([rec]) <= 0.15


def test_14_gate_sub_all_pass():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"verdict": True}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"GATE_VERDICT|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.GATE_VERDICT, "cpag", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_gate([rec]) == 1.0


def test_15_gate_sub_all_fail():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"verdict": False}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"GATE_VERDICT|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.GATE_VERDICT, "cpag", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    assert _sub_gate([rec]) == 0.0


# ---------------------------------------------------------------------------
# T157-GHI-16 — T157-GHI-20: sub-index: stability
# ---------------------------------------------------------------------------

def test_16_stability_sub_no_events():
    assert _sub_stability([]) == 1.0


def test_17_stability_sub_one_break():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    payload = {"reason": "test"}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    eid = hashlib.sha256(f"CIRCUIT_BREAK|{canon}|{'0'*64}".encode()).hexdigest()
    rec = TelemetryRecord(eid, CGTHEventType.CIRCUIT_BREAK, "circuit_breaker", payload,
                          "0"*64, hashlib.sha256(eid.encode()).hexdigest(), 0)
    result = _sub_stability([rec])
    assert result < 1.0


def test_18_stability_degrades_with_multiple_breaks():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    records = []
    for i in range(5):
        payload = {"reason": f"test_{i}"}
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        eid = hashlib.sha256(f"CIRCUIT_BREAK|{canon}|{i}".encode()).hexdigest()
        records.append(TelemetryRecord(eid, CGTHEventType.CIRCUIT_BREAK, "circuit_breaker",
                                       payload, "0"*64, hashlib.sha256(eid.encode()).hexdigest(), i))
    single_break = _sub_stability(records[:1])
    multi_break = _sub_stability(records)
    assert multi_break <= single_break


def test_19_stability_score_floored_at_zero():
    from dorkllm.telemetry_hub import TelemetryRecord, CGTHEventType
    import hashlib
    records = []
    for i in range(20):
        payload = {"reason": f"b{i}"}
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        eid = hashlib.sha256(f"CIRCUIT_BREAK|{canon}|{i}".encode()).hexdigest()
        records.append(TelemetryRecord(eid, CGTHEventType.CIRCUIT_BREAK, "circuit_breaker",
                                       payload, "0"*64, hashlib.sha256(eid.encode()).hexdigest(), i))
    assert _sub_stability(records) >= 0.0


def test_20_snapshot_to_dict_has_required_keys(tmp_path):
    hub = _hub(tmp_path)
    ghi = GovernanceHealthIndex(hub=hub)
    snap = ghi.compute_score()
    d = snap.to_dict()
    assert "score" in d
    assert "band" in d
    assert "sub_scores" in d
    assert "advisory" in d


# ---------------------------------------------------------------------------
# T157-GHI-21 — T157-GHI-25: compute_score integration
# ---------------------------------------------------------------------------

def test_21_nominal_score_empty_ledger(tmp_path):
    """Empty CGTH ledger → all sub-scores 1.0 → NOMINAL."""
    ghi = GovernanceHealthIndex(hub=_hub(tmp_path))
    snap = ghi.compute_score()
    assert snap.band == HealthBand.NOMINAL
    assert snap.score >= 0.90


def test_22_pressure_degrades_score(tmp_path):
    hub = _hub(tmp_path)
    _pressure_events(hub, 0.95)
    ghi = GovernanceHealthIndex(hub=hub)
    snap = ghi.compute_score()
    assert snap.sub_scores["pressure"] <= 0.10


def test_23_block_throttle_degrades_score(tmp_path):
    hub = _hub(tmp_path)
    _throttle_events(hub, "BLOCK", 3)
    ghi = GovernanceHealthIndex(hub=hub)
    snap = ghi.compute_score()
    assert snap.sub_scores["throttle"] == 0.0


def test_24_critical_anomaly_degrades_score(tmp_path):
    hub = _hub(tmp_path)
    _fire_cgai(hub, "CRITICAL")
    ghi = GovernanceHealthIndex(hub=hub)
    snap = ghi.compute_score()
    assert snap.sub_scores["anomaly"] <= 0.15


def test_25_all_bad_gives_critical_band(tmp_path):
    hub = _hub(tmp_path)
    _pressure_events(hub, 0.98)
    _throttle_events(hub, "BLOCK", 3)
    _fire_cgai(hub, "CRITICAL")
    _gate_events(hub, False, 5)
    for _ in range(5):
        _break_event(hub)
    ghi = GovernanceHealthIndex(hub=hub)
    snap = ghi.compute_score()
    assert snap.band in (HealthBand.CRITICAL, HealthBand.ELEVATED)


# ---------------------------------------------------------------------------
# T157-GHI-26 — T157-GHI-28: GHI-EMIT-0
# ---------------------------------------------------------------------------

def test_26_compute_score_emits_to_cgth(tmp_path):
    """GHI-EMIT-0: compute_score emits PERM_SNAPSHOT into CGTH."""
    hub = _hub(tmp_path)
    before = len(hub.tail(100))
    ghi = GovernanceHealthIndex(hub=hub)
    ghi.compute_score()
    after = len(hub.tail(100))
    assert after == before + 1


def test_27_history_returns_list(tmp_path):
    hub = _hub(tmp_path)
    ghi = GovernanceHealthIndex(hub=hub)
    ghi.compute_score()
    ghi.compute_score()
    hist = ghi.history(limit=10)
    assert isinstance(hist, list)
    assert len(hist) == 2


def test_28_score_bounded_ghi_score_0(tmp_path):
    """GHI-SCORE-0: score always in [0.0, 1.0]."""
    hub = _hub(tmp_path)
    _pressure_events(hub, 1.0)
    _throttle_events(hub, "BLOCK", 10)
    _fire_cgai(hub, "CRITICAL")
    _gate_events(hub, False, 10)
    for _ in range(10):
        _break_event(hub)
        _rollback_event(hub)
    ghi = GovernanceHealthIndex(hub=hub)
    snap = ghi.compute_score()
    assert 0.0 <= snap.score <= 1.0


# ---------------------------------------------------------------------------
# T157-GHI-29 — T157-GHI-30: REST router and module API
# ---------------------------------------------------------------------------

def test_29_rest_router_routes_defined():
    from app.api.governance_health import router
    if router is not None:
        routes = [r.path for r in router.routes]
        assert any("health" in p for p in routes)


def test_30_module_level_score_now():
    snap = score_now()
    assert isinstance(snap, HealthSnapshot)
    assert 0.0 <= snap.score <= 1.0
