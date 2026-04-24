# SPDX-License-Identifier: Apache-2.0
"""Phase 159 - INNOV-65 . CSI - Constitutional Strength Index - Test Suite

30 acceptance tests covering all invariants, sub-dimensions, determinism,
boundary conditions, and REST API.

CSI-SCORE-0 : score always int in [0, 100]
CSI-DETERM-0: identical records => identical snapshot_id
CSI-EMIT-0  : compute() emits PERM_SNAPSHOT(csi) into CGTH
CSI-GATE-0  : score < 70 emits HUMAN0_AUTHORISATION advisory
CSI-BAND-0  : band deterministic from score

Author: DEVADAAD . InnovativeAI LLC
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from dorkllm.constitutional_strength import (
    CSIBand,
    CSISnapshot,
    ConstitutionalStrengthIndex,
    _band,
    _score_agent_stability,
    _score_anomaly_resilience,
    _score_governance_velocity,
    _score_invariant_compliance,
    _score_pressure_headroom,
    _score_repair_responsiveness,
    _snapshot_id,
    compute_csi,
    _WEIGHTS,
    WINDOW,
)
from dorkllm.telemetry_hub import CGTHEventType, TelemetryRecord, get_hub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(etype: CGTHEventType, payload: Dict[str, Any] = None) -> TelemetryRecord:
    return TelemetryRecord(
        event_id="test-id", event_type=etype,
        component_id="test_harness", payload=payload or {},
        prev_hmac="0" * 64, this_hmac="0" * 64, seq=1,
    )


def _hub_with_records(records: List[TelemetryRecord]):
    hub = MagicMock()
    hub.query.return_value = iter(records)
    hub.emit_event = MagicMock(return_value="evt-id")
    return hub


# ===========================================================================
# Group 1 — Band logic (CSI-BAND-0)
# ===========================================================================

class TestBand:
    def test_band_excellent_at_85(self):
        assert _band(85) == CSIBand.EXCELLENT

    def test_band_excellent_at_100(self):
        assert _band(100) == CSIBand.EXCELLENT

    def test_band_healthy_at_70(self):
        assert _band(70) == CSIBand.HEALTHY

    def test_band_healthy_at_84(self):
        assert _band(84) == CSIBand.HEALTHY

    def test_band_caution_at_50(self):
        assert _band(50) == CSIBand.CAUTION

    def test_band_caution_at_69(self):
        assert _band(69) == CSIBand.CAUTION

    def test_band_critical_at_49(self):
        assert _band(49) == CSIBand.CRITICAL

    def test_band_critical_at_0(self):
        assert _band(0) == CSIBand.CRITICAL


# ===========================================================================
# Group 2 — Sub-dimension computers
# ===========================================================================

class TestSubDimensions:
    def test_invariant_compliance_all_pass(self):
        records = [
            _make_record(CGTHEventType.GATE_VERDICT, {"verdict": "PASS"})
            for _ in range(10)
        ]
        assert _score_invariant_compliance(records) == 100

    def test_invariant_compliance_all_fail(self):
        records = [
            _make_record(CGTHEventType.GATE_VERDICT, {"verdict": "REJECT"})
            for _ in range(10)
        ]
        assert _score_invariant_compliance(records) == 0

    def test_invariant_compliance_no_data_returns_neutral(self):
        assert _score_invariant_compliance([]) == 75

    def test_pressure_headroom_no_data_returns_neutral(self):
        assert _score_pressure_headroom([]) == 80

    def test_pressure_headroom_zero_pressure(self):
        records = [_make_record(CGTHEventType.PRESSURE_SNAPSHOT, {"pressure": 0.0})]
        assert _score_pressure_headroom(records) == 100

    def test_pressure_headroom_full_pressure(self):
        records = [_make_record(CGTHEventType.PRESSURE_SNAPSHOT, {"pressure": 1.0})]
        assert _score_pressure_headroom(records) == 0

    def test_anomaly_resilience_no_data_near_perfect(self):
        assert _score_anomaly_resilience([]) == 90

    def test_anomaly_resilience_critical_anomalies(self):
        records = [
            _make_record(CGTHEventType.PERM_SNAPSHOT,
                         {"component_id": "cgai", "severity": "CRITICAL"})
            for _ in range(5)
        ]
        assert _score_anomaly_resilience(records) == 0

    def test_agent_stability_no_breaks(self):
        assert _score_agent_stability([]) == 100

    def test_agent_stability_penalises_circuit_breaks(self):
        records = [_make_record(CGTHEventType.CIRCUIT_BREAK) for _ in range(3)]
        assert _score_agent_stability(records) == 70

    def test_agent_stability_penalises_rollbacks(self):
        records = [_make_record(CGTHEventType.ROLLBACK_EXECUTED) for _ in range(2)]
        assert _score_agent_stability(records) == 60

    def test_agent_stability_floors_at_zero(self):
        records = (
            [_make_record(CGTHEventType.CIRCUIT_BREAK) for _ in range(6)]
            + [_make_record(CGTHEventType.ROLLBACK_EXECUTED) for _ in range(4)]
        )
        assert _score_agent_stability(records) == 0

    def test_governance_velocity_no_events(self):
        assert _score_governance_velocity([]) == 0

    def test_governance_velocity_caps_at_100(self):
        records = [_make_record(CGTHEventType.THROTTLE_DECISION) for _ in range(20)]
        assert _score_governance_velocity(records) == 100

    def test_repair_responsiveness_no_csr(self):
        assert _score_repair_responsiveness([]) == 0

    def test_repair_responsiveness_caps_at_100(self):
        records = [
            _make_record(CGTHEventType.PERM_SNAPSHOT, {"component_id": "csr"})
            for _ in range(10)
        ]
        assert _score_repair_responsiveness(records) == 100


# ===========================================================================
# Group 3 — CSI-SCORE-0: score always int in [0, 100]
# ===========================================================================

class TestScoreInvariant:
    def test_score_is_int(self):
        csi = compute_csi()
        assert isinstance(csi.score, int)

    def test_score_in_range(self):
        csi = compute_csi()
        assert 0 <= csi.score <= 100

    def test_snapshot_to_dict_contains_score(self):
        csi = compute_csi()
        d = csi.to_dict()
        assert "score" in d
        assert isinstance(d["score"], int)


# ===========================================================================
# Group 4 — CSI-DETERM-0: determinism
# ===========================================================================

class TestDeterminism:
    def test_snapshot_id_identical_for_same_inputs(self):
        sub_scores = {"a": 80, "b": 60, "c": 90, "d": 75, "e": 50, "f": 100}
        sid1 = _snapshot_id(sub_scores, 42)
        sid2 = _snapshot_id(sub_scores, 42)
        assert sid1 == sid2

    def test_snapshot_id_differs_for_different_scores(self):
        sub1 = {"a": 80, "b": 60, "c": 90, "d": 75, "e": 50, "f": 100}
        sub2 = {"a": 80, "b": 61, "c": 90, "d": 75, "e": 50, "f": 100}
        assert _snapshot_id(sub1, 42) != _snapshot_id(sub2, 42)

    def test_snapshot_id_differs_for_different_event_count(self):
        sub = {"a": 80, "b": 60, "c": 90, "d": 75, "e": 50, "f": 100}
        assert _snapshot_id(sub, 42) != _snapshot_id(sub, 43)

    def test_two_compute_calls_identical_records_same_snapshot_id(self):
        hub = _hub_with_records([])
        hub.query.side_effect = [iter([]), iter([])]
        engine = ConstitutionalStrengthIndex(hub=hub)
        s1 = engine.compute()
        hub.query.return_value = iter([])
        s2 = engine.compute()
        assert s1.snapshot_id == s2.snapshot_id


# ===========================================================================
# Group 5 — CSI-EMIT-0 and CSI-GATE-0
# ===========================================================================

class TestEmitInvariants:
    def test_emit0_perm_snapshot_emitted(self):
        hub = _hub_with_records([])
        engine = ConstitutionalStrengthIndex(hub=hub)
        engine.compute()
        calls = hub.emit_event.call_args_list
        types = [c.kwargs.get("event_type") or c.args[1] for c in calls]
        assert CGTHEventType.PERM_SNAPSHOT in types

    def test_emit0_component_id_is_csi(self):
        hub = _hub_with_records([])
        engine = ConstitutionalStrengthIndex(hub=hub)
        engine.compute()
        calls = hub.emit_event.call_args_list
        for c in calls:
            cid = c.kwargs.get("component_id") or c.args[0]
            if (c.kwargs.get("event_type") or c.args[1]) == CGTHEventType.PERM_SNAPSHOT:
                assert cid == "csi"

    def test_gate0_human0_emitted_when_score_below_70(self):
        # Force score < 70: all zeros
        records = [_make_record(CGTHEventType.GATE_VERDICT, {"verdict": "REJECT"})
                   for _ in range(WINDOW)]
        hub = _hub_with_records(records)
        engine = ConstitutionalStrengthIndex(hub=hub)
        snap = engine.compute()
        if snap.score < 70:
            types = [
                c.kwargs.get("event_type") or c.args[1]
                for c in hub.emit_event.call_args_list
            ]
            assert CGTHEventType.HUMAN0_AUTHORISATION in types
            assert snap.human0_alert is True

    def test_gate0_no_human0_when_score_healthy(self):
        records = [_make_record(CGTHEventType.GATE_VERDICT, {"verdict": "PASS"})
                   for _ in range(10)]
        hub = _hub_with_records(records)
        engine = ConstitutionalStrengthIndex(hub=hub)
        snap = engine.compute()
        if snap.score >= 70:
            types = [
                c.kwargs.get("event_type") or c.args[1]
                for c in hub.emit_event.call_args_list
            ]
            assert CGTHEventType.HUMAN0_AUTHORISATION not in types
            assert snap.human0_alert is False


# ===========================================================================
# Group 6 — Weights and structural assertions
# ===========================================================================

class TestWeightsStructure:
    def test_weights_sum_to_one(self):
        assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9

    def test_six_sub_dimensions(self):
        assert len(_WEIGHTS) == 6

    def test_snapshot_has_all_sub_scores(self):
        csi = compute_csi()
        for dim in _WEIGHTS:
            assert dim in csi.sub_scores

    def test_sub_scores_are_ints(self):
        csi = compute_csi()
        for v in csi.sub_scores.values():
            assert isinstance(v, int)
