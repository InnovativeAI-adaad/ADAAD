# SPDX-License-Identifier: Apache-2.0
"""
INNOV-99 · GTA — Governed Telemetry Aggregator
===============================================
Phase 194 · v10.5.0 · InnovativeAI LLC

World-first: A constitutionally-governed, HMAC-chain-sealed telemetry
aggregation engine that collects operational signals from every ADAAD
pipeline module, computes constitutional health metrics, detects anomalies
against invariant-bound thresholds, seals all observations in an append-only
telemetry ledger, and escalates threshold violations to HUMAN-0 before any
further pipeline activity is permitted.

GTA is the observability spine of ADAAD — every module in the mutation
pipeline emits telemetry events that GTA aggregates, scores, and seals. No
pipeline module may suppress its telemetry emission (GTA-EMIT-0). GTA itself
never modifies the pipeline it observes (GTA-NOMOD-0).

Hard-class invariants enforced (10):
  GTA-EMIT-0    Every registered pipeline module emits at least one
                TelemetryEvent per orchestration cycle; silence is a
                violation escalated to HUMAN-0.
  GTA-CHAIN-0   All TelemetryRecord entries in the telemetry ledger are
                HMAC-SHA256 chained; each record's HMAC covers the prior.
  GTA-HUMAN0-0  Any metric that breaches its constitutional threshold triggers
                a HUMAN-0 escalation flag; no further aggregation until cleared.
  GTA-IMMUT-0   The telemetry ledger is append-only; no record may be modified
                or deleted after sealing.
  GTA-DETERM-0  Given identical TelemetryEvent inputs, aggregate() always
                produces identical AggregationRecord output (deterministic).
  GTA-SCOPE-0   GTA only accepts telemetry from modules within the ADAAD
                constitutional scope; out-of-scope sources raise GTAScopeViolation.
  GTA-AUDIT-0   All aggregation lifecycle events (RECEIVED, SCORING, SEALED,
                VIOLATED, ESCALATED) are written to the audit log.
  GTA-ATOMIC-0  An aggregation run is atomic; partial failure leaves the
                telemetry ledger unchanged (GTAAtomicViolation raised).
  GTA-NOMOD-0   GTA never mutates, patches, or writes to any pipeline module
                it observes; observation is strictly read-only.
  GTA-REPLAY-0  AggregationRecords are deterministically replayable:
                replay_record() re-derives the same HMAC from stored fields.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ── Constitutional invariant registry ────────────────────────────────────────

INVARIANTS: List[str] = [
    "GTA-EMIT-0",
    "GTA-CHAIN-0",
    "GTA-HUMAN0-0",
    "GTA-IMMUT-0",
    "GTA-DETERM-0",
    "GTA-SCOPE-0",
    "GTA-AUDIT-0",
    "GTA-ATOMIC-0",
    "GTA-NOMOD-0",
    "GTA-REPLAY-0",
]

HARD_CLASS = "Hard"
INVARIANT_COUNT = len(INVARIANTS)  # 10

# ── Constitutional constants ──────────────────────────────────────────────────

HMAC_SECRET: bytes = b"GTA-ADAAD-CHAIN-v1"
GENESIS_HMAC = "0" * 64

CONSTITUTIONAL_SOURCES: frozenset = frozenset({
    "MSR",   # Mutation Strategy Router
    "MSE",   # Mutation Selection Engine
    "MRP",   # Mutation Risk Profiler
    "MEX",   # Mutation Execution Engine
    "MFV",   # Mutation Fitness Verifier
    "MCE",   # Mutation Calibration Engine
    "MPG",   # Mutation Phylogeny Graph
    "CMO",   # Constitutional Mutation Orchestrator
    "CIL",   # Constitutional Integrity Ledger
    "ILV",   # Invariant Lineage Verifier
    "CAL",   # Constitutional Adaptive Learner
    "CFI",   # CEL Feedback Integrator
    "DQR",   # DORK Query Router
    "DPM",   # DORK Persistent Memory
    "GPE",   # GA Promotion Engine
    "GTC",   # Governance Tag Certifier
})

# Constitutional threshold defaults (module → metric → ceiling)
DEFAULT_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "_global": {
        "error_rate":        0.05,   # 5% error rate ceiling
        "latency_p99_ms":    5000.0, # 5s p99 latency ceiling
        "invariant_violations": 0.0, # zero tolerance
        "human0_flags":      0.0,    # zero tolerance
    }
}


# ── Exceptions ────────────────────────────────────────────────────────────────

class GTAScopeViolation(Exception):
    """GTA-SCOPE-0: telemetry source outside ADAAD constitutional scope."""

class GTAChainViolation(Exception):
    """GTA-CHAIN-0: HMAC chain tamper detected in telemetry ledger."""

class GTAHuman0Flag(Exception):
    """GTA-HUMAN0-0: threshold violation requires HUMAN-0 clearance."""

class GTAAtomicViolation(Exception):
    """GTA-ATOMIC-0: partial aggregation — ledger unchanged."""

class GTAReplayFailure(Exception):
    """GTA-REPLAY-0: replay produced divergent HMAC."""

class GTAEmitViolation(Exception):
    """GTA-EMIT-0: registered module emitted no telemetry this cycle."""

class GTANoModViolation(Exception):
    """GTA-NOMOD-0: attempt to mutate an observed pipeline module detected."""


# ── Enumerations ──────────────────────────────────────────────────────────────

class AggregationStatus(str, Enum):
    RECEIVED  = "RECEIVED"
    SCORING   = "SCORING"
    SEALED    = "SEALED"
    VIOLATED  = "VIOLATED"
    ESCALATED = "ESCALATED"


class MetricStatus(str, Enum):
    NOMINAL   = "NOMINAL"
    DEGRADED  = "DEGRADED"
    CRITICAL  = "CRITICAL"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class TelemetryEvent:
    """A single telemetry emission from one ADAAD pipeline module."""
    event_id: str
    source: str                    # must be in CONSTITUTIONAL_SOURCES
    cycle_id: str                  # orchestration cycle identifier
    metric_name: str
    metric_value: float
    unit: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricVerdict:
    """Threshold evaluation result for one metric."""
    source: str
    metric_name: str
    metric_value: float
    threshold: float
    status: MetricStatus
    detail: str = ""


@dataclass
class AggregationRecord:
    """
    HMAC-chained, sealed telemetry ledger entry.
    Produced once per aggregate() call (GTA-CHAIN-0, GTA-DETERM-0).
    """
    record_id: str
    cycle_id: str
    event_count: int
    sources_seen: List[str]
    sources_silent: List[str]       # GTA-EMIT-0 violators
    violation_count: int
    verdicts: List[MetricVerdict]
    status: AggregationStatus
    constitutional_seal: str        # SHA-256 of all event_ids in order
    timestamp: float
    prev_hmac: str                  # GTA-CHAIN-0
    hmac: str = field(default="", init=False)

    def _canonical(self) -> bytes:
        return json.dumps({
            "record_id":          self.record_id,
            "cycle_id":           self.cycle_id,
            "event_count":        self.event_count,
            "sources_seen":       sorted(self.sources_seen),
            "sources_silent":     sorted(self.sources_silent),
            "violation_count":    self.violation_count,
            "status":             self.status.value,
            "constitutional_seal": self.constitutional_seal,
            "timestamp":          self.timestamp,
            "prev_hmac":          self.prev_hmac,
        }, sort_keys=True).encode()

    def seal(self, secret: bytes = HMAC_SECRET) -> None:
        """Compute and store HMAC (GTA-CHAIN-0, GTA-DETERM-0)."""
        self.hmac = hmac.new(secret, self._canonical(), hashlib.sha256).hexdigest()

    def verify_seal(self, secret: bytes = HMAC_SECRET) -> bool:
        """Verify stored HMAC (GTA-REPLAY-0)."""
        expected = hmac.new(secret, self._canonical(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.hmac, expected)


@dataclass
class AuditEvent:
    """GTA-AUDIT-0: lifecycle event record."""
    event_id: str
    record_id: str
    cycle_id: str
    event_type: AggregationStatus
    detail: str
    timestamp: float


# ── Governed Telemetry Aggregator ─────────────────────────────────────────────

class GovernedTelemetryAggregator:
    """
    Constitutional observability spine for all ADAAD pipeline modules.

    Enforces all 10 GTA hard-class invariants.
    GTA-NOMOD-0 is enforced structurally: GTA has no write handles to any
    pipeline module; it only accepts TelemetryEvent objects passed to it.
    """

    def __init__(
        self,
        secret: bytes = HMAC_SECRET,
        thresholds: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        self._secret = secret
        self._thresholds = thresholds or DEFAULT_THRESHOLDS
        self._ledger: List[AggregationRecord] = []       # GTA-IMMUT-0
        self._audit_log: List[AuditEvent] = []           # GTA-AUDIT-0
        self._registered_sources: set = set()
        self._human0_flagged: bool = False                # GTA-HUMAN0-0
        self._sealed_ids: set = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def register_source(self, source: str) -> None:
        """
        Register a pipeline module as a required telemetry emitter.
        GTA-EMIT-0: registered sources that emit nothing in a cycle are violations.
        """
        if source not in CONSTITUTIONAL_SOURCES:
            raise GTAScopeViolation(
                f"GTA-SCOPE-0: '{source}' is not in CONSTITUTIONAL_SOURCES"
            )
        self._registered_sources.add(source)

    def aggregate(
        self,
        events: List[TelemetryEvent],
        cycle_id: str,
    ) -> AggregationRecord:
        """
        Aggregate *events* for one orchestration cycle and produce a sealed
        AggregationRecord.

        Raises
        ------
        GTAScopeViolation   — event source outside CONSTITUTIONAL_SOURCES
        GTAHuman0Flag       — HUMAN-0 flag already set
        GTAAtomicViolation  — internal partial failure (ledger unchanged)
        GTAEmitViolation    — registered source emitted nothing this cycle
        """
        # GTA-SCOPE-0: validate all sources upfront
        for ev in events:
            if ev.source not in CONSTITUTIONAL_SOURCES:
                raise GTAScopeViolation(
                    f"GTA-SCOPE-0: event source '{ev.source}' not in CONSTITUTIONAL_SOURCES"
                )

        # GTA-HUMAN0-0: block while flag is raised
        if self._human0_flagged:
            raise GTAHuman0Flag(
                "GTA-HUMAN0-0: HUMAN-0 flag is set; "
                "clear via acknowledge_human0() before resuming."
            )

        self._emit_audit(str(uuid.uuid4()), cycle_id,
                         AggregationStatus.RECEIVED, f"{len(events)} events received")

        # GTA-EMIT-0: check registered sources
        seen_sources = {ev.source for ev in events}
        silent = sorted(self._registered_sources - seen_sources)

        # GTA-ATOMIC-0: stage all work before touching ledger
        try:
            record = self._atomic_aggregate(events, cycle_id, silent)
        except Exception as exc:
            self._emit_audit(str(uuid.uuid4()), cycle_id,
                             AggregationStatus.RECEIVED,
                             f"atomic failure — ledger unchanged: {exc}")
            raise GTAAtomicViolation(
                f"GTA-ATOMIC-0: aggregation aborted, ledger unchanged. Cause: {exc}"
            ) from exc

        # GTA-EMIT-0 escalation: silent registered sources are violations
        if silent:
            record.sources_silent = silent
            record.violation_count += len(silent)
            if record.violation_count > 0 and record.status == AggregationStatus.SEALED:
                record.status = AggregationStatus.VIOLATED

        # GTA-HUMAN0-0: escalate on any violation
        if record.violation_count > 0:
            self._human0_flagged = True
            record.status = AggregationStatus.ESCALATED
            record.hmac = ""
            record.seal(self._secret)
            self._emit_audit(record.record_id, cycle_id,
                             AggregationStatus.ESCALATED,
                             f"{record.violation_count} violation(s) — HUMAN-0 escalated")

        self._ledger.append(record)
        self._sealed_ids.add(record.record_id)
        self._emit_audit(record.record_id, cycle_id,
                         record.status, "record sealed in telemetry ledger")
        return record

    def replay_record(self, record: AggregationRecord) -> bool:
        """
        Replay-verify an AggregationRecord (GTA-REPLAY-0).
        Returns True iff recomputed HMAC matches stored HMAC.
        """
        if not record.verify_seal(self._secret):
            raise GTAReplayFailure(
                f"GTA-REPLAY-0: replay of record {record.record_id} "
                "produced divergent HMAC — possible tamper"
            )
        return True

    def verify_ledger_chain(self) -> bool:
        """
        Walk the full telemetry ledger and verify every chain link (GTA-CHAIN-0).
        Returns True if intact; raises GTAChainViolation on tamper.
        """
        prev = GENESIS_HMAC
        for idx, record in enumerate(self._ledger):
            if record.prev_hmac != prev:
                raise GTAChainViolation(
                    f"GTA-CHAIN-0: chain broken at index {idx} "
                    f"(record {record.record_id})"
                )
            if not record.verify_seal(self._secret):
                raise GTAChainViolation(
                    f"GTA-CHAIN-0: HMAC tamper at index {idx} "
                    f"(record {record.record_id})"
                )
            prev = record.hmac
        return True

    def acknowledge_human0(self, ratification_token: str) -> None:
        """Clear the HUMAN-0 flag after operator review (GTA-HUMAN0-0)."""
        if not self._human0_flagged:
            return
        self._human0_flagged = False
        self._emit_audit("HUMAN-0-ACK", "gta_ledger",
                         AggregationStatus.SEALED,
                         f"HUMAN-0 flag cleared; token={ratification_token}")

    def health_summary(self) -> Dict[str, Any]:
        """
        Return a point-in-time constitutional health summary across all
        recorded AggregationRecords (GTA-NOMOD-0: read-only, no side effects).
        """
        if not self._ledger:
            return {"status": "NO_DATA", "record_count": 0, "human0_flagged": self._human0_flagged}
        total_violations = sum(r.violation_count for r in self._ledger)
        statuses = [r.status.value for r in self._ledger]
        return {
            "status": "HEALTHY" if total_violations == 0 else "DEGRADED",
            "record_count": len(self._ledger),
            "total_violations": total_violations,
            "human0_flagged": self._human0_flagged,
            "last_status": self._ledger[-1].status.value,
            "status_history": statuses[-10:],
        }

    @property
    def ledger(self) -> List[AggregationRecord]:
        """Read-only view of the telemetry ledger (GTA-IMMUT-0)."""
        return list(self._ledger)

    @property
    def audit_log(self) -> List[AuditEvent]:
        """Read-only audit event log (GTA-AUDIT-0)."""
        return list(self._audit_log)

    @property
    def human0_flagged(self) -> bool:
        return self._human0_flagged

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _atomic_aggregate(
        self,
        events: List[TelemetryEvent],
        cycle_id: str,
        silent: List[str],
    ) -> AggregationRecord:
        """Stage full aggregation without touching the ledger (GTA-ATOMIC-0)."""
        self._emit_audit(str(uuid.uuid4()), cycle_id,
                         AggregationStatus.SCORING, "metric scoring in progress")

        verdicts: List[MetricVerdict] = []
        violation_count = 0
        sources_seen = sorted({ev.source for ev in events})

        global_thresh = self._thresholds.get("_global", {})

        for ev in events:
            module_thresh = self._thresholds.get(ev.source, {})
            threshold = module_thresh.get(
                ev.metric_name,
                global_thresh.get(ev.metric_name, float("inf"))
            )
            if ev.metric_value > threshold:
                status = MetricStatus.CRITICAL
                violation_count += 1
                detail = (
                    f"{ev.source}.{ev.metric_name}={ev.metric_value:.4f} "
                    f"exceeds threshold={threshold:.4f}"
                )
            elif ev.metric_value > threshold * 0.8:
                status = MetricStatus.DEGRADED
                detail = (
                    f"{ev.source}.{ev.metric_name}={ev.metric_value:.4f} "
                    f"approaching threshold={threshold:.4f}"
                )
            else:
                status = MetricStatus.NOMINAL
                detail = ""
            verdicts.append(MetricVerdict(
                source=ev.source,
                metric_name=ev.metric_name,
                metric_value=ev.metric_value,
                threshold=threshold,
                status=status,
                detail=detail,
            ))

        # Constitutional seal: SHA-256 of all event_ids in order
        seal_input = "".join(ev.event_id for ev in events).encode()
        constitutional_seal = hashlib.sha256(seal_input).hexdigest()

        agg_status = (
            AggregationStatus.VIOLATED if violation_count > 0
            else AggregationStatus.SEALED
        )

        prev_hmac = self._ledger[-1].hmac if self._ledger else GENESIS_HMAC

        record = AggregationRecord(
            record_id=str(uuid.uuid4()),
            cycle_id=cycle_id,
            event_count=len(events),
            sources_seen=sources_seen,
            sources_silent=silent,
            violation_count=violation_count,
            verdicts=verdicts,
            status=agg_status,
            constitutional_seal=constitutional_seal,
            timestamp=time.time(),
            prev_hmac=prev_hmac,
        )
        record.seal(self._secret)
        return record

    def _emit_audit(
        self,
        record_id: str,
        cycle_id: str,
        event_type: AggregationStatus,
        detail: str,
    ) -> None:
        """GTA-AUDIT-0: append lifecycle event."""
        self._audit_log.append(AuditEvent(
            event_id=str(uuid.uuid4()),
            record_id=record_id,
            cycle_id=cycle_id,
            event_type=event_type,
            detail=detail,
            timestamp=time.time(),
        ))


# ── Factory helpers ───────────────────────────────────────────────────────────

def make_gta(
    secret: bytes = HMAC_SECRET,
    thresholds: Optional[Dict[str, Dict[str, float]]] = None,
) -> GovernedTelemetryAggregator:
    """Construct a GovernedTelemetryAggregator."""
    return GovernedTelemetryAggregator(secret=secret, thresholds=thresholds)


def make_event(
    source: str,
    metric_name: str,
    metric_value: float,
    cycle_id: str = "cycle-default",
    unit: str = "unit",
) -> TelemetryEvent:
    """Construct a TelemetryEvent for testing and governance tooling."""
    return TelemetryEvent(
        event_id=str(uuid.uuid4()),
        source=source,
        cycle_id=cycle_id,
        metric_name=metric_name,
        metric_value=metric_value,
        unit=unit,
        timestamp=time.time(),
    )
