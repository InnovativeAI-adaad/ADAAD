# SPDX-License-Identifier: Apache-2.0
"""Phase 156 — INNOV-62 · CGAI — Constitutional Governance Anomaly Inspector

Autonomous runtime monitor that ingests the CGTH telemetry stream, detects
governance anomaly patterns, scores each finding by severity, and emits findings
back into CGTH — closing the telemetry feedback loop.

Detected anomaly patterns
==========================
GATE_SPIKE        : Abnormal gate rejection rate (≥ SPIKE_THRESHOLD rejections in
                    window of WINDOW_SIZE GATE_VERDICT events).
PRESSURE_SURGE    : Constitutional pressure index exceeds surge threshold (≥ 0.85).
THROTTLE_SAT      : Adaptive throttle saturated (level == 'BLOCK' or severity
                    fraction of THROTTLE_DECISION events in window is high).
FIRE_CLUSTER      : Invariant fires clustered (≥ CLUSTER_THRESHOLD INVARIANT_FIRE
                    events from the same component_id in the rolling window).
CIRCUIT_CASCADE   : Multiple CIRCUIT_BREAK events within a short sequence window.
ROLLBACK_REPEAT   : Repeated ROLLBACK_EXECUTED events within the window — indicates
                    persistent instability.
CHAIN_GAP         : Sequence numbers in the CGTH ledger are non-contiguous —
                    possible tamper or write error.

Constitutional Invariants
==========================
CGAI-DETECT-0 : All seven detector functions must be present and callable at
                module import time.
CGAI-SEVERITY-0 : AnomalySeverity ordinal ordering is LOW < MEDIUM < HIGH < CRITICAL.
CGAI-EMIT-0   : Findings of severity >= MEDIUM are emitted as INVARIANT_FIRE events
                into CGTH from the 'cgai' component.
CGAI-DETERM-0 : report_id is a pure function of (anomaly_type, evidence_canonical);
                wall-clock time must not influence report_id.

Patent note (InnovativeAI LLC): The combination of multi-pattern governance anomaly
detection over a cryptographically chained telemetry stream, with findings re-emitted
into the same governed ledger, constitutes a novel closed-loop Constitutional Anomaly
Detection architecture for autonomous AI governance systems.

Author: DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

import hashlib
import json
from enum import IntEnum
from typing import Any, Dict, List, Optional, Sequence

from dorkllm.telemetry_hub import (
    CGTHEventType,
    ConstitutionalGovernanceTelemetryHub,
    TelemetryRecord,
    get_hub,
)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

WINDOW_SIZE: int = 20            # rolling event window for rate-based detectors
GATE_SPIKE_THRESHOLD: int = 5    # rejections in WINDOW_SIZE GATE_VERDICT events
CLUSTER_THRESHOLD: int = 4       # same-component invariant fires in window
CASCADE_THRESHOLD: int = 3       # CIRCUIT_BREAK events in circuit cascade window
CASCADE_WINDOW: int = 10         # events scanned for circuit cascade
ROLLBACK_REPEAT_THRESHOLD: int = 2
PRESSURE_SURGE_THRESHOLD: float = 0.85
PRESSURE_SURGE_CRITICAL: float = 0.95


# ---------------------------------------------------------------------------
# Severity (CGAI-SEVERITY-0)
# ---------------------------------------------------------------------------

class AnomalySeverity(IntEnum):
    LOW      = 1
    MEDIUM   = 2
    HIGH     = 3
    CRITICAL = 4


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class AnomalyReport:
    """Immutable finding produced by an anomaly detector."""

    __slots__ = ("report_id", "anomaly_type", "severity", "evidence", "advisory")

    def __init__(
        self,
        anomaly_type: str,
        severity: AnomalySeverity,
        evidence: Dict[str, Any],
        advisory: str = "",
    ) -> None:
        self.anomaly_type = anomaly_type
        self.severity     = severity
        self.evidence     = evidence
        self.advisory     = advisory
        # CGAI-DETERM-0 — deterministic id
        canon = json.dumps({"t": anomaly_type, "e": evidence}, sort_keys=True,
                           separators=(",", ":"), default=str)
        self.report_id = hashlib.sha256(f"{anomaly_type}|{canon}".encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id":    self.report_id,
            "anomaly_type": self.anomaly_type,
            "severity":     self.severity.name,
            "evidence":     self.evidence,
            "advisory":     self.advisory,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tail(records: List[TelemetryRecord], n: int) -> List[TelemetryRecord]:
    return records[-n:] if len(records) >= n else records


def _filter(records: List[TelemetryRecord], etype: CGTHEventType) -> List[TelemetryRecord]:
    return [r for r in records if r.event_type == etype]


# ---------------------------------------------------------------------------
# Detector functions (CGAI-DETECT-0 — all seven must exist)
# ---------------------------------------------------------------------------

def detect_gate_spike(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """GATE_SPIKE: high rejection rate in recent GATE_VERDICT events."""
    gate_events = _filter(_tail(records, WINDOW_SIZE * 3), CGTHEventType.GATE_VERDICT)[-WINDOW_SIZE:]
    if not gate_events:
        return None
    rejections = sum(1 for r in gate_events if not r.payload.get("verdict", True))
    if rejections >= GATE_SPIKE_THRESHOLD * 2:
        sev = AnomalySeverity.CRITICAL
    elif rejections >= GATE_SPIKE_THRESHOLD:
        sev = AnomalySeverity.HIGH
    else:
        return None
    return AnomalyReport(
        "GATE_SPIKE", sev,
        {"rejections": rejections, "window": len(gate_events)},
        advisory="Investigate mutation proposer for systematic constitutional violations.",
    )


def detect_pressure_surge(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """PRESSURE_SURGE: constitutional pressure index exceeds threshold."""
    pressure_events = _filter(_tail(records, WINDOW_SIZE), CGTHEventType.PRESSURE_SNAPSHOT)
    if not pressure_events:
        return None
    latest = pressure_events[-1]
    score = latest.payload.get("score", 0.0)
    if score >= PRESSURE_SURGE_CRITICAL:
        sev = AnomalySeverity.CRITICAL
    elif score >= PRESSURE_SURGE_THRESHOLD:
        sev = AnomalySeverity.HIGH
    else:
        return None
    return AnomalyReport(
        "PRESSURE_SURGE", sev,
        {"score": score, "threshold": PRESSURE_SURGE_THRESHOLD},
        advisory="Constitutional pressure critical — consider HUMAN-0 review before next mutation.",
    )


def detect_throttle_saturation(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """THROTTLE_SAT: adaptive throttle saturated at BLOCK level."""
    throttle_events = _filter(_tail(records, WINDOW_SIZE), CGTHEventType.THROTTLE_DECISION)
    if not throttle_events:
        return None
    blocked = sum(1 for r in throttle_events if r.payload.get("level") == "BLOCK")
    if blocked == 0:
        return None
    fraction = blocked / len(throttle_events)
    sev = AnomalySeverity.CRITICAL if fraction >= 0.5 else AnomalySeverity.HIGH
    return AnomalyReport(
        "THROTTLE_SAT", sev,
        {"blocked": blocked, "total": len(throttle_events), "fraction": round(fraction, 3)},
        advisory="Mutation throttle saturated — pressure reduction required.",
    )


def detect_fire_cluster(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """FIRE_CLUSTER: invariant fires concentrated in one component."""
    fire_events = _filter(_tail(records, WINDOW_SIZE * 2), CGTHEventType.INVARIANT_FIRE)
    if not fire_events:
        return None
    from collections import Counter
    counts = Counter(r.component_id for r in fire_events)
    top_component, top_count = counts.most_common(1)[0]
    if top_count < CLUSTER_THRESHOLD:
        return None
    sev = AnomalySeverity.CRITICAL if top_count >= CLUSTER_THRESHOLD * 2 else AnomalySeverity.HIGH
    return AnomalyReport(
        "FIRE_CLUSTER", sev,
        {"component": top_component, "count": top_count, "window": len(fire_events)},
        advisory=f"Component '{top_component}' producing repeated invariant violations.",
    )


def detect_circuit_cascade(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """CIRCUIT_CASCADE: multiple CIRCUIT_BREAK events in short window."""
    recent = _tail(records, CASCADE_WINDOW)
    breaks = _filter(recent, CGTHEventType.CIRCUIT_BREAK)
    if len(breaks) < CASCADE_THRESHOLD:
        return None
    sev = AnomalySeverity.CRITICAL if len(breaks) >= CASCADE_THRESHOLD * 2 else AnomalySeverity.HIGH
    return AnomalyReport(
        "CIRCUIT_CASCADE", sev,
        {"break_count": len(breaks), "window": CASCADE_WINDOW},
        advisory="Circuit breaker firing repeatedly — systemic governance instability.",
    )


def detect_rollback_repeat(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """ROLLBACK_REPEAT: repeated rollbacks indicate persistent instability."""
    rollback_events = _filter(_tail(records, WINDOW_SIZE), CGTHEventType.ROLLBACK_EXECUTED)
    count = len(rollback_events)
    if count < ROLLBACK_REPEAT_THRESHOLD:
        return None
    sev = AnomalySeverity.HIGH if count < ROLLBACK_REPEAT_THRESHOLD * 3 else AnomalySeverity.CRITICAL
    return AnomalyReport(
        "ROLLBACK_REPEAT", sev,
        {"count": count, "window": WINDOW_SIZE},
        advisory="Persistent rollback pattern — mutation proposals may be constitutionally unsound.",
    )


def detect_chain_gap(records: List[TelemetryRecord]) -> Optional[AnomalyReport]:
    """CHAIN_GAP: non-contiguous sequence numbers in CGTH ledger."""
    if len(records) < 2:
        return None
    gaps = []
    for i in range(1, len(records)):
        expected = records[i - 1].seq + 1
        if records[i].seq != expected:
            gaps.append({"at": records[i].seq, "expected": expected})
    if not gaps:
        return None
    return AnomalyReport(
        "CHAIN_GAP", AnomalySeverity.CRITICAL,
        {"gaps": gaps, "total_records": len(records)},
        advisory="CGTH ledger sequence gap detected — possible tamper or write failure. HUMAN-0 review required.",
    )


# ---------------------------------------------------------------------------
# All detectors registry (CGAI-DETECT-0)
# ---------------------------------------------------------------------------

ALL_DETECTORS = [
    detect_gate_spike,
    detect_pressure_surge,
    detect_throttle_saturation,
    detect_fire_cluster,
    detect_circuit_cascade,
    detect_rollback_repeat,
    detect_chain_gap,
]

assert len(ALL_DETECTORS) == 7, "CGAI-DETECT-0: exactly 7 detectors required"


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------

class ConstitutionalGovernanceAnomalyInspector:
    """CGAI — autonomous governance anomaly inspector.

    Reads the CGTH telemetry stream, runs all detectors, and emits findings
    back into CGTH for any anomaly of severity >= MEDIUM (CGAI-EMIT-0).
    """

    def __init__(self, hub: Optional[ConstitutionalGovernanceTelemetryHub] = None) -> None:
        self._hub = hub or get_hub()

    def inspect(self, limit: int = 500) -> List[AnomalyReport]:
        """Run all detectors against the current CGTH stream.

        Returns list of AnomalyReport findings (may be empty).
        CGAI-EMIT-0: emits MEDIUM+ findings into CGTH.
        """
        records = self._hub.tail(limit)
        findings: List[AnomalyReport] = []
        for detector in ALL_DETECTORS:
            report = detector(list(records))
            if report is not None:
                findings.append(report)
                if report.severity >= AnomalySeverity.MEDIUM:
                    # CGAI-EMIT-0 — emit back into CGTH
                    self._hub.emit_event(
                        component_id="cgai",
                        event_type=CGTHEventType.INVARIANT_FIRE,
                        payload=report.to_dict(),
                    )
        return findings

    def inspect_one(self, anomaly_type: str, limit: int = 500) -> Optional[AnomalyReport]:
        """Run a single named detector by anomaly_type string."""
        detector_map = {d.__name__.replace("detect_", "").upper(): d for d in ALL_DETECTORS}
        # normalise: detect_gate_spike → GATE_SPIKE
        mapped = {
            "GATE_SPIKE": detect_gate_spike,
            "PRESSURE_SURGE": detect_pressure_surge,
            "THROTTLE_SAT": detect_throttle_saturation,
            "FIRE_CLUSTER": detect_fire_cluster,
            "CIRCUIT_CASCADE": detect_circuit_cascade,
            "ROLLBACK_REPEAT": detect_rollback_repeat,
            "CHAIN_GAP": detect_chain_gap,
        }
        fn = mapped.get(anomaly_type.upper())
        if fn is None:
            return None
        records = list(self._hub.tail(limit))
        return fn(records)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_inspector: Optional[ConstitutionalGovernanceAnomalyInspector] = None


def get_inspector() -> ConstitutionalGovernanceAnomalyInspector:
    global _default_inspector
    if _default_inspector is None:
        _default_inspector = ConstitutionalGovernanceAnomalyInspector()
    return _default_inspector


def inspect_now() -> List[AnomalyReport]:
    """Module-level inspect — delegates to singleton inspector."""
    return get_inspector().inspect()
