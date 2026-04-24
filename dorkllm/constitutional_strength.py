# SPDX-License-Identifier: Apache-2.0
"""Phase 159 - INNOV-65 . CSI - Constitutional Strength Index

The Constitutional Strength Index is the single authoritative number (0-100)
representing the overall constitutional integrity of an ADAAD instance.

Six Sub-Dimensions
==================
1. invariant_compliance  (0.30) - gate pass-rate over last WINDOW events
2. pressure_headroom     (0.20) - inverse of constitutional pressure
3. anomaly_resilience    (0.20) - inverse CGAI anomaly severity
4. agent_stability       (0.15) - penalises circuit breaks + rollbacks
5. governance_velocity   (0.10) - rewards active regulated mutation pipeline
6. repair_responsiveness (0.05) - rewards CSR proposal activity

Constitutional Invariants
==========================
CSI-SCORE-0 : score is always int in [0, 100]
CSI-DETERM-0: identical CGTH records => identical CSISnapshot
CSI-EMIT-0  : every compute() MUST emit PERM_SNAPSHOT(csi) into CGTH
CSI-GATE-0  : score < 70 MUST emit HUMAN0_AUTHORISATION advisory
CSI-BAND-0  : band deterministic from score

Patent note (InnovativeAI LLC): CSI architecture is novel art in AI governance.
Author: DEVADAAD . InnovativeAI LLC
"""

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
from dorkllm.telemetry_hub import CGTHEventType, TelemetryRecord, get_hub


class CSIBand(str, Enum):
    EXCELLENT = "EXCELLENT"
    HEALTHY   = "HEALTHY"
    CAUTION   = "CAUTION"
    CRITICAL  = "CRITICAL"


def _band(score: int) -> CSIBand:
    """CSI-BAND-0: deterministic band from score."""
    if score >= 85:
        return CSIBand.EXCELLENT
    if score >= 70:
        return CSIBand.HEALTHY
    if score >= 50:
        return CSIBand.CAUTION
    return CSIBand.CRITICAL


_WEIGHTS: Dict[str, float] = {
    "invariant_compliance":  0.30,
    "pressure_headroom":     0.20,
    "anomaly_resilience":    0.20,
    "agent_stability":       0.15,
    "governance_velocity":   0.10,
    "repair_responsiveness": 0.05,
}

assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9
assert len(_WEIGHTS) == 6

WINDOW: int = 100

_SEVERITY_WEIGHT: Dict[str, float] = {
    "INFO": 0.00, "LOW": 0.25, "MEDIUM": 0.50, "HIGH": 0.75, "CRITICAL": 1.00,
}


@dataclass
class CSISnapshot:
    score: int
    band: CSIBand
    sub_scores: Dict[str, int]
    event_count: int
    advisory: Optional[str]
    snapshot_id: str
    human0_alert: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score, "band": self.band.value,
            "sub_scores": self.sub_scores, "event_count": self.event_count,
            "advisory": self.advisory, "snapshot_id": self.snapshot_id,
            "human0_alert": self.human0_alert,
        }


def _tail(records: List[TelemetryRecord], n: int) -> List[TelemetryRecord]:
    return records[-n:] if len(records) > n else records


def _ftype(records: List[TelemetryRecord], etype: CGTHEventType) -> List[TelemetryRecord]:
    return [r for r in records if r.event_type == etype]


def _score_invariant_compliance(records: List[TelemetryRecord]) -> int:
    gate = _ftype(_tail(records, WINDOW), CGTHEventType.GATE_VERDICT)
    if not gate:
        return 75
    passed = sum(
        1 for r in gate
        if str((r.payload or {}).get("verdict", "")).upper()
        in ("PASS", "ADMIT", "APPROVED", "OK", "ALLOWED", "TRUE", "1")
    )
    return round((passed / len(gate)) * 100)


def _score_pressure_headroom(records: List[TelemetryRecord]) -> int:
    events = _ftype(_tail(records, WINDOW), CGTHEventType.PRESSURE_SNAPSHOT)
    if not events:
        return 80
    values: List[float] = []
    for r in events:
        p = r.payload if isinstance(r.payload, dict) else {}
        val = p.get("pressure", p.get("score", p.get("value")))
        if val is not None:
            try:
                values.append(float(val))
            except (TypeError, ValueError):
                pass
    if not values:
        return 80
    mean_p = sum(values) / len(values)
    if mean_p > 1.0:
        mean_p /= 100.0
    mean_p = max(0.0, min(1.0, mean_p))
    return round(max(0.0, 1.0 - mean_p) * 100)


def _score_anomaly_resilience(records: List[TelemetryRecord]) -> int:
    cgai = [
        r for r in _tail(records, WINDOW)
        if r.event_type == CGTHEventType.PERM_SNAPSHOT
        and isinstance(r.payload, dict)
        and r.payload.get("component_id") == "cgai"
    ]
    fires = _ftype(_tail(records, WINDOW), CGTHEventType.INVARIANT_FIRE)
    if not cgai and not fires:
        return 90
    sev_sum = sum(
        _SEVERITY_WEIGHT.get(str((r.payload or {}).get("severity", "INFO")).upper(), 0.0)
        for r in cgai
    ) + len(fires) * _SEVERITY_WEIGHT["HIGH"]
    count = len(cgai) + len(fires)
    if count == 0:
        return 90
    return round((1.0 - sev_sum / count) * 100)


def _score_agent_stability(records: List[TelemetryRecord]) -> int:
    w = _tail(records, WINDOW)
    return max(0, min(100, 100 - 10 * len(_ftype(w, CGTHEventType.CIRCUIT_BREAK))
                      - 20 * len(_ftype(w, CGTHEventType.ROLLBACK_EXECUTED))))


def _score_governance_velocity(records: List[TelemetryRecord]) -> int:
    return min(100, 10 * len(_ftype(_tail(records, WINDOW), CGTHEventType.THROTTLE_DECISION)))


def _score_repair_responsiveness(records: List[TelemetryRecord]) -> int:
    csr = [
        r for r in _tail(records, WINDOW)
        if r.event_type == CGTHEventType.PERM_SNAPSHOT
        and isinstance(r.payload, dict) and r.payload.get("component_id") == "csr"
    ]
    return min(100, 20 * len(csr))


def _snapshot_id(sub_scores: Dict[str, int], event_count: int) -> str:
    canonical = json.dumps(
        {"sub_scores": sub_scores, "event_count": event_count},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class ConstitutionalStrengthIndex:
    """Computes the CSI from live CGTH telemetry."""

    def __init__(self, hub=None) -> None:
        self._hub = hub or get_hub()

    def compute(self) -> CSISnapshot:
        """Compute and emit the Constitutional Strength Index."""
        records: List[TelemetryRecord] = list(self._hub.query())

        sub_raw = {
            "invariant_compliance":  _score_invariant_compliance(records),
            "pressure_headroom":     _score_pressure_headroom(records),
            "anomaly_resilience":    _score_anomaly_resilience(records),
            "agent_stability":       _score_agent_stability(records),
            "governance_velocity":   _score_governance_velocity(records),
            "repair_responsiveness": _score_repair_responsiveness(records),
        }

        composite = sum(sub_raw[d] * w for d, w in _WEIGHTS.items())
        score = max(0, min(100, round(composite)))  # CSI-SCORE-0
        sub_scores: Dict[str, int] = {k: round(v) for k, v in sub_raw.items()}
        band = _band(score)  # CSI-BAND-0

        advisory: Optional[str] = None
        human0_alert = False
        if score < 70:  # CSI-GATE-0
            weakest = min(sub_scores, key=sub_scores.get)
            advisory = (
                f"CSI {score}/100 below HEALTHY threshold (70). "
                f"Governance review required. "
                f"Weakest: {weakest} ({sub_scores[weakest]}/100)."
            )
            human0_alert = True

        sid = _snapshot_id(sub_scores, len(records))  # CSI-DETERM-0

        # CSI-EMIT-0
        self._hub.emit_event(
            component_id="csi",
            event_type=CGTHEventType.PERM_SNAPSHOT,
            payload={
                "component_id": "csi", "score": score, "band": band.value,
                "sub_scores": sub_scores, "snapshot_id": sid,
                "event_count": len(records),
            },
        )

        if human0_alert:  # CSI-GATE-0
            self._hub.emit_event(
                component_id="csi",
                event_type=CGTHEventType.HUMAN0_AUTHORISATION,
                payload={
                    "advisory": True, "csi_score": score,
                    "csi_band": band.value, "message": advisory,
                    "snapshot_id": sid,
                },
            )

        return CSISnapshot(
            score=score, band=band, sub_scores=sub_scores,
            event_count=len(records), advisory=advisory,
            snapshot_id=sid, human0_alert=human0_alert,
        )


def compute_csi(hub=None) -> CSISnapshot:
    """Module-level convenience: compute and return current CSI."""
    return ConstitutionalStrengthIndex(hub=hub).compute()
