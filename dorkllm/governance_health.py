# SPDX-License-Identifier: Apache-2.0
"""Phase 157 — INNOV-63 · GHI — Governance Health Index

A composite runtime constitutional health score (0.0–1.0) synthesized from
all active CGTH telemetry sources: constitutional pressure, throttle state,
CGAI anomaly severity, gate pass-rate, circuit breaker activity, and rollback
frequency.

The GHI answers the question every CCO and General Counsel will ask:
"Is our AI governance system healthy right now?" — with a single deterministic,
cryptographically timestamped number.

Score bands
===========
0.90 – 1.00  NOMINAL     — all subsystems green
0.75 – 0.89  CAUTION     — degraded in ≥1 dimension
0.50 – 0.74  ELEVATED    — material governance concern; escalate
0.00 – 0.49  CRITICAL    — fail-close recommended; HUMAN-0 required

Constitutional Invariants
==========================
GHI-SCORE-0   : GHI score is always in [0.0, 1.0].  A score outside this
                range is a Hard-class violation.
GHI-DETERM-0  : Given identical CGTH telemetry snapshots the score computation
                produces the same result.  No wall-clock randomness.
GHI-EMIT-0    : Every compute_score() call emits a GHI_SNAPSHOT event into
                CGTH from the 'ghi' component.
GHI-SUBINDEX-0: The composite score is the weighted mean of exactly five
                sub-indices: pressure, throttle, anomaly, gate, stability.

Patent note (InnovativeAI LLC): A composite constitutional health index derived
from a hash-chained multi-subsystem telemetry stream, with score emission back
into the governed ledger, constitutes a novel Constitutional Health Index
architecture for autonomous AI governance systems.

Author: DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from dorkllm.anomaly_inspector import (
    AnomalySeverity,
    ConstitutionalGovernanceAnomalyInspector,
)
from dorkllm.telemetry_hub import (
    CGTHEventType,
    ConstitutionalGovernanceTelemetryHub,
    TelemetryRecord,
    get_hub,
)

# ---------------------------------------------------------------------------
# Score band
# ---------------------------------------------------------------------------

class HealthBand(str, Enum):
    NOMINAL   = "NOMINAL"
    CAUTION   = "CAUTION"
    ELEVATED  = "ELEVATED"
    CRITICAL  = "CRITICAL"


def _band(score: float) -> HealthBand:
    if score >= 0.90:
        return HealthBand.NOMINAL
    if score >= 0.75:
        return HealthBand.CAUTION
    if score >= 0.50:
        return HealthBand.ELEVATED
    return HealthBand.CRITICAL


# ---------------------------------------------------------------------------
# Sub-index weights (GHI-SUBINDEX-0: exactly five)
# ---------------------------------------------------------------------------

_WEIGHTS: Dict[str, float] = {
    "pressure":  0.25,   # constitutional pressure index
    "throttle":  0.20,   # adaptive throttle state
    "anomaly":   0.25,   # CGAI anomaly severity
    "gate":      0.20,   # gate pass-rate
    "stability": 0.10,   # circuit breaks + rollbacks
}

assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "GHI-SUBINDEX-0: weights must sum to 1.0"
assert len(_WEIGHTS) == 5, "GHI-SUBINDEX-0: exactly five sub-indices required"

WINDOW: int = 50   # telemetry events considered per computation


# ---------------------------------------------------------------------------
# Health snapshot
# ---------------------------------------------------------------------------

@dataclass
class HealthSnapshot:
    score: float
    band: HealthBand
    sub_scores: Dict[str, float]
    event_count: int
    advisory: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score":      round(self.score, 4),
            "band":       self.band.value,
            "sub_scores": {k: round(v, 4) for k, v in self.sub_scores.items()},
            "event_count": self.event_count,
            "advisory":   self.advisory,
        }


# ---------------------------------------------------------------------------
# Sub-index computers (GHI-DETERM-0 — pure functions of record lists)
# ---------------------------------------------------------------------------

def _sub_pressure(records: List[TelemetryRecord]) -> float:
    """1.0 = no pressure; lower as CPI score rises."""
    snapshots = [r for r in records if r.event_type == CGTHEventType.PRESSURE_SNAPSHOT]
    if not snapshots:
        return 1.0
    latest_score = snapshots[-1].payload.get("score", 0.0)
    return max(0.0, 1.0 - latest_score)


def _sub_throttle(records: List[TelemetryRecord]) -> float:
    """1.0 = all ALLOW; degrades with REDUCE/BLOCK events."""
    throttle = [r for r in records if r.event_type == CGTHEventType.THROTTLE_DECISION]
    if not throttle:
        return 1.0
    level_score = {"ALLOW": 1.0, "REDUCE": 0.5, "BLOCK": 0.0}
    scores = [level_score.get(r.payload.get("level", "ALLOW"), 0.5) for r in throttle]
    return sum(scores) / len(scores)


def _sub_anomaly(records: List[TelemetryRecord]) -> float:
    """1.0 = no anomaly findings; degrades by severity of most recent CGAI finding."""
    cgai_fires = [
        r for r in records
        if r.event_type == CGTHEventType.INVARIANT_FIRE
        and r.component_id == "cgai"
    ]
    if not cgai_fires:
        return 1.0
    severity_penalty = {
        AnomalySeverity.LOW.name:      0.05,
        AnomalySeverity.MEDIUM.name:   0.20,
        AnomalySeverity.HIGH.name:     0.50,
        AnomalySeverity.CRITICAL.name: 0.90,
    }
    worst = max(
        severity_penalty.get(r.payload.get("severity", "LOW"), 0.0)
        for r in cgai_fires
    )
    return max(0.0, 1.0 - worst)


def _sub_gate(records: List[TelemetryRecord]) -> float:
    """Pass-rate of GATE_VERDICT events; 1.0 = all pass."""
    gate_events = [r for r in records if r.event_type == CGTHEventType.GATE_VERDICT]
    if not gate_events:
        return 1.0
    passes = sum(1 for r in gate_events if r.payload.get("verdict", True))
    return passes / len(gate_events)


def _sub_stability(records: List[TelemetryRecord]) -> float:
    """1.0 = no circuit breaks or rollbacks; degrades with each event."""
    breaks = sum(1 for r in records if r.event_type == CGTHEventType.CIRCUIT_BREAK)
    rollbacks = sum(1 for r in records if r.event_type == CGTHEventType.ROLLBACK_EXECUTED)
    instability = breaks + rollbacks
    if instability == 0:
        return 1.0
    return max(0.0, 1.0 - (instability * 0.15))


_SUB_COMPUTERS = {
    "pressure":  _sub_pressure,
    "throttle":  _sub_throttle,
    "anomaly":   _sub_anomaly,
    "gate":      _sub_gate,
    "stability": _sub_stability,
}

assert set(_SUB_COMPUTERS) == set(_WEIGHTS), "GHI-SUBINDEX-0: sub-index mismatch"


# ---------------------------------------------------------------------------
# Advisory generator
# ---------------------------------------------------------------------------

def _advisory(band: HealthBand, sub_scores: Dict[str, float]) -> str:
    worst = min(sub_scores, key=sub_scores.get)  # type: ignore[arg-type]
    worst_score = sub_scores[worst]
    if band == HealthBand.NOMINAL:
        return "All governance subsystems operating nominally."
    if band == HealthBand.CAUTION:
        return f"Governance caution: '{worst}' sub-index at {worst_score:.2f}. Monitor closely."
    if band == HealthBand.ELEVATED:
        return (
            f"Governance elevated: '{worst}' sub-index at {worst_score:.2f}. "
            "Consider pausing non-critical mutations pending HUMAN-0 review."
        )
    return (
        f"GOVERNANCE CRITICAL: '{worst}' sub-index at {worst_score:.2f}. "
        "Fail-close recommended. HUMAN-0 review required before proceeding."
    )


# ---------------------------------------------------------------------------
# GHI Engine
# ---------------------------------------------------------------------------

class GovernanceHealthIndex:
    """GHI — composite constitutional health index.

    Usage::

        ghi = GovernanceHealthIndex()
        snapshot = ghi.compute_score()
        print(snapshot.score, snapshot.band)
    """

    def __init__(
        self,
        hub: Optional[ConstitutionalGovernanceTelemetryHub] = None,
        window: int = WINDOW,
    ) -> None:
        self._hub    = hub or get_hub()
        self._window = window

    def compute_score(self) -> HealthSnapshot:
        """Compute the current GHI score.

        GHI-SCORE-0   : score ∈ [0.0, 1.0].
        GHI-DETERM-0  : deterministic given same telemetry.
        GHI-EMIT-0    : emits GHI_SNAPSHOT (via PERM_SNAPSHOT type) into CGTH.
        GHI-SUBINDEX-0: weighted mean of five sub-indices.
        """
        records = list(self._hub.tail(self._window))

        sub_scores: Dict[str, float] = {}
        for name, fn in _SUB_COMPUTERS.items():
            raw = fn(records)
            # GHI-SCORE-0 — clamp sub-scores
            sub_scores[name] = max(0.0, min(1.0, raw))

        # Weighted composite (GHI-SUBINDEX-0)
        score = sum(_WEIGHTS[k] * sub_scores[k] for k in _WEIGHTS)
        score = max(0.0, min(1.0, score))  # GHI-SCORE-0 final clamp

        band     = _band(score)
        advisory = _advisory(band, sub_scores)

        snapshot = HealthSnapshot(
            score=score,
            band=band,
            sub_scores=sub_scores,
            event_count=len(records),
            advisory=advisory,
        )

        # GHI-EMIT-0 — persist into CGTH
        self._hub.emit_event(
            component_id="ghi",
            event_type=CGTHEventType.PERM_SNAPSHOT,
            payload={
                "engine_id": "ghi",
                "data": snapshot.to_dict(),
            },
        )

        return snapshot

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent GHI_SNAPSHOT records from CGTH."""
        records = self._hub.query(
            event_type=CGTHEventType.PERM_SNAPSHOT,
            component_id="ghi",
            limit=limit,
        )
        return [r.payload.get("data", {}) for r in records]


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_ghi: Optional[GovernanceHealthIndex] = None


def get_ghi() -> GovernanceHealthIndex:
    global _default_ghi
    if _default_ghi is None:
        _default_ghi = GovernanceHealthIndex()
    return _default_ghi


def score_now() -> HealthSnapshot:
    """Module-level score — delegates to singleton GHI."""
    return get_ghi().compute_score()
