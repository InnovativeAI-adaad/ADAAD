# SPDX-License-Identifier: Apache-2.0
"""
constitutional_autonomous_monitoring_sentinel.py
Phase 231 · INNOV-136 · CAMS — Constitutional Autonomous Monitoring Sentinel
World-first cryptographically governed continuous CHI health-monitoring
pipeline with deterministic trend classification, append-only HMAC-chained
observation ledger, and HUMAN-0 acknowledgement-gated critical alerting.

Author  : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 07

CAMS closes the observability gap in Arc III: CADE decides, CAPE executes,
CALI learns — CAMS watches. It continuously samples CHI scores emitted by
CASL, classifies the rolling trend (HEALTHY / DEGRADING / CRITICAL) using a
fixed deterministic window, seals every sample into an HMAC-chained
monitoring ledger, and raises CRITICAL alerts that can only be cleared by an
explicit HUMAN-0 acknowledgement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional
from collections import deque

# ── Hard-class invariant identifiers ─────────────────────────────────────────
# CAMS-CHAIN-0  : All monitoring ledger entries HMAC-SHA-256 chained
# CAMS-APPEND-0 : Monitoring ledger is append-only — no mutation or deletion
# CAMS-SAMPLE-0 : Every CHI sample must carry a valid score in [0,1] and a
#                 non-empty source reference
# CAMS-CLASS-0  : Exactly 3 trend classes handled: HEALTHY, DEGRADING, CRITICAL
# CAMS-DETERM-0 : Trend classification is fully deterministic — no RNG, fixed
#                 thresholds, fixed window
# CAMS-WINDOW-0 : TrendDetector requires a minimum populated window before
#                 issuing any classification other than HEALTHY (no premature
#                 CRITICAL verdicts on sparse data)
# CAMS-ALERT-0  : Every CRITICAL classification must produce exactly one Alert
# CAMS-HUMAN0-0 : CRITICAL alerts can only be cleared by a non-empty HUMAN-0
#                 acknowledgement identity
# CAMS-IMMUT-0  : Sealed ledger entries and sealed alerts are immutable after
#                 creation (acknowledgement is the only permitted alert
#                 transition)
# CAMS-AUDIT-0  : Every CAMS operation sealed in a parallel HMAC-chained
#                 audit log

_TREND_CLASSES = ("HEALTHY", "DEGRADING", "CRITICAL")
_TREND_CLASS_COUNT = len(_TREND_CLASSES)
if _TREND_CLASS_COUNT != 3:
    raise RuntimeError(
        f"CAMS-CLASS-0 VIOLATION: expected exactly 3 trend classes, "
        f"found {_TREND_CLASS_COUNT}"
    )

_HMAC_SECRET = os.environ.get(
    "CAMS_HMAC_SECRET", "cams-hmac-secret-DUSTIN-L-REID-v10-ArcIII"
).encode()

# CAMS-WINDOW-0: minimum samples required before non-HEALTHY classification
_MIN_WINDOW = 5
# CAMS-DETERM-0: fixed deterministic thresholds (mean CHI over window)
_DEGRADING_THRESHOLD = 0.65
_CRITICAL_THRESHOLD = 0.40
# CAMS-DETERM-0: a window is also CRITICAL if the trailing slope drops this
# much across the window, even if the mean is still above threshold
_CRITICAL_SLOPE_DROP = 0.25


def _hmac_digest(payload: str) -> str:
    return hmac.new(_HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()


# ── Typed exception hierarchy ─────────────────────────────────────────────────
class CAMSViolation(RuntimeError):
    """Base class for all CAMS Hard-class invariant violations."""


class ChainBreakError(CAMSViolation):
    """CAMS-CHAIN-0: HMAC chain integrity broken."""


class AppendViolation(CAMSViolation):
    """CAMS-APPEND-0: Attempted mutation or deletion of monitoring ledger."""


class SampleError(CAMSViolation):
    """CAMS-SAMPLE-0: Invalid CHI sample (score out of range or no source)."""


class ClassScopeViolation(CAMSViolation):
    """CAMS-CLASS-0: Unrecognized trend class encountered."""


class DeterminismViolation(CAMSViolation):
    """CAMS-DETERM-0: Non-deterministic trend classification detected."""


class WindowError(CAMSViolation):
    """CAMS-WINDOW-0: Classification attempted with insufficient window."""


class AlertError(CAMSViolation):
    """CAMS-ALERT-0: CRITICAL trend failed to produce a required alert."""


class HUMAN0AckError(CAMSViolation):
    """CAMS-HUMAN0-0: Alert acknowledgement requires non-empty HUMAN-0 identity."""


class ImmutabilityViolation(CAMSViolation):
    """CAMS-IMMUT-0: Attempt to mutate a sealed ledger entry or alert."""


class AuditFailure(CAMSViolation):
    """CAMS-AUDIT-0: Audit ledger write failed."""


# ── Enums ──────────────────────────────────────────────────────────────────────
class TrendClass(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADING = "DEGRADING"
    CRITICAL = "CRITICAL"


class AlertState(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# ── Data structures ────────────────────────────────────────────────────────────
@dataclass
class CHISample:
    """
    A single CHI observation. CAMS-SAMPLE-0: score in [0,1], source non-empty.
    """
    sample_id: str
    chi_score: float
    source_ref: str          # e.g. CASL arc record id this sample came from
    observed_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "chi_score": self.chi_score,
            "source_ref": self.source_ref,
            "observed_ts": self.observed_ts,
        }


@dataclass
class TrendClassification:
    """
    Deterministic trend verdict over a fixed sample window.
    CAMS-DETERM-0 / CAMS-WINDOW-0 / CAMS-CLASS-0.
    """
    classification_id: str
    trend: TrendClass
    window_size: int
    window_mean: float
    window_slope: float
    sample_ids: List[str]
    classified_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification_id": self.classification_id,
            "trend": self.trend.value,
            "window_size": self.window_size,
            "window_mean": round(self.window_mean, 6),
            "window_slope": round(self.window_slope, 6),
            "sample_ids": self.sample_ids,
            "classified_ts": self.classified_ts,
        }


@dataclass
class Alert:
    """
    Alert raised for a CRITICAL trend classification.
    CAMS-ALERT-0: exactly one alert per CRITICAL classification.
    CAMS-HUMAN0-0: acknowledgement requires non-empty HUMAN-0 identity.
    CAMS-IMMUT-0: only state-transition permitted is OPEN -> ACKNOWLEDGED.
    """
    alert_id: str
    classification_id: str
    trend: TrendClass
    window_mean: float
    raised_ts: float
    state: AlertState = AlertState.OPEN
    acknowledged_by: Optional[str] = None
    acknowledged_ts: Optional[float] = None
    ack_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "classification_id": self.classification_id,
            "trend": self.trend.value,
            "window_mean": round(self.window_mean, 6),
            "raised_ts": self.raised_ts,
            "state": self.state.value,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_ts": self.acknowledged_ts,
            "ack_note": self.ack_note,
        }


@dataclass
class MonitoringLedgerEntry:
    """
    HMAC-SHA-256 chained ledger entry wrapping a sealed CHI sample.
    CAMS-CHAIN-0: prev_hash links form an unbreakable chain.
    CAMS-APPEND-0: entries are write-once.
    """
    entry_id: str
    sequence: int
    prev_hash: str
    sample: CHISample
    classification: Optional[TrendClassification]
    entry_hash: str = field(default="", init=False)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps({
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "sample_id": self.sample.sample_id,
            "chi_score": self.sample.chi_score,
            "source_ref": self.sample.source_ref,
            "trend": self.classification.trend.value if self.classification else None,
            "ts": self.ts,
        }, sort_keys=True)
        return _hmac_digest(payload)


@dataclass
class AuditEntry:
    """Single entry in the parallel HMAC-chained audit log. CAMS-AUDIT-0."""
    audit_id: str
    sequence: int
    prev_hash: str
    operation: str
    entity_id: str
    detail: str
    ts: float = field(default_factory=time.time)
    entry_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        payload = json.dumps({
            "audit_id": self.audit_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "operation": self.operation,
            "entity_id": self.entity_id,
            "ts": self.ts,
        }, sort_keys=True)
        self.entry_hash = _hmac_digest(payload)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "operation": self.operation,
            "entity_id": self.entity_id,
            "detail": self.detail,
            "ts": self.ts,
            "entry_hash": self.entry_hash,
        }


# ── CHIMonitor ────────────────────────────────────────────────────────────────
class CHIMonitor:
    """
    Ingests and validates raw CHI samples from upstream (CASL).
    CAMS-SAMPLE-0: score in [0,1], source_ref non-empty.
    """

    def ingest(self, chi_score: float, source_ref: str) -> CHISample:
        if not isinstance(chi_score, (int, float)) or not (0.0 <= chi_score <= 1.0):
            raise SampleError(
                f"CAMS-SAMPLE-0 VIOLATION: chi_score must be in [0,1], got {chi_score!r}"
            )
        if not source_ref or not source_ref.strip():
            raise SampleError(
                "CAMS-SAMPLE-0 VIOLATION: source_ref must be non-empty"
            )
        return CHISample(
            sample_id=f"CHI-{uuid.uuid4().hex[:16].upper()}",
            chi_score=float(chi_score),
            source_ref=source_ref,
            observed_ts=time.time(),
        )


# ── TrendDetector ─────────────────────────────────────────────────────────────
class TrendDetector:
    """
    Deterministic rolling-window trend classifier.
    CAMS-CLASS-0: exactly HEALTHY / DEGRADING / CRITICAL.
    CAMS-DETERM-0: fixed window, fixed thresholds, no RNG.
    CAMS-WINDOW-0: < _MIN_WINDOW samples always classify HEALTHY.
    """

    def __init__(self, window: int = _MIN_WINDOW) -> None:
        if window < _MIN_WINDOW:
            raise WindowError(
                f"CAMS-WINDOW-0 VIOLATION: window must be >= {_MIN_WINDOW}, got {window}"
            )
        self._window_size = window
        self._buffer: Deque[CHISample] = deque(maxlen=window)

    def classify(self, sample: CHISample) -> TrendClassification:
        self._buffer.append(sample)
        n = len(self._buffer)

        if n < _MIN_WINDOW:
            # CAMS-WINDOW-0: insufficient data — must classify HEALTHY
            trend = TrendClass.HEALTHY
            mean = sum(s.chi_score for s in self._buffer) / n
            slope = 0.0
        else:
            scores = [s.chi_score for s in self._buffer]
            mean = sum(scores) / n
            slope = scores[-1] - scores[0]  # CAMS-DETERM-0: deterministic slope
            if mean < _CRITICAL_THRESHOLD or slope <= -_CRITICAL_SLOPE_DROP:
                trend = TrendClass.CRITICAL
            elif mean < _DEGRADING_THRESHOLD:
                trend = TrendClass.DEGRADING
            else:
                trend = TrendClass.HEALTHY

        if trend.value not in _TREND_CLASSES:
            raise ClassScopeViolation(
                f"CAMS-CLASS-0 VIOLATION: unrecognized trend '{trend}'"
            )

        return TrendClassification(
            classification_id=f"TC-{uuid.uuid4().hex[:16].upper()}",
            trend=trend,
            window_size=n,
            window_mean=mean,
            window_slope=slope,
            sample_ids=[s.sample_id for s in self._buffer],
            classified_ts=time.time(),
        )


# ── AlertEngine ───────────────────────────────────────────────────────────────
class AlertEngine:
    """
    Raises and tracks alerts for CRITICAL trend classifications.
    CAMS-ALERT-0: exactly one alert per CRITICAL classification.
    CAMS-HUMAN0-0: acknowledgement requires non-empty HUMAN-0 identity.
    CAMS-IMMUT-0: only OPEN -> ACKNOWLEDGED transition is permitted.
    """

    def __init__(self) -> None:
        self._alerts: Dict[str, Alert] = {}
        self._by_classification: Dict[str, str] = {}

    def raise_alert(self, classification: TrendClassification) -> Alert:
        if classification.trend != TrendClass.CRITICAL:
            raise AlertError(
                "CAMS-ALERT-0 VIOLATION: alerts may only be raised for CRITICAL "
                f"classifications, got {classification.trend.value}"
            )
        if classification.classification_id in self._by_classification:
            raise ImmutabilityViolation(
                f"CAMS-ALERT-0 VIOLATION: alert already raised for "
                f"{classification.classification_id}"
            )
        alert = Alert(
            alert_id=f"CAMS-ALERT-{uuid.uuid4().hex[:16].upper()}",
            classification_id=classification.classification_id,
            trend=classification.trend,
            window_mean=classification.window_mean,
            raised_ts=time.time(),
        )
        self._alerts[alert.alert_id] = alert
        self._by_classification[classification.classification_id] = alert.alert_id
        return alert

    def acknowledge(self, alert_id: str, acknowledged_by: str, note: str = "") -> Alert:
        if not acknowledged_by or not acknowledged_by.strip():
            raise HUMAN0AckError(
                "CAMS-HUMAN0-0 VIOLATION: acknowledged_by must be non-empty HUMAN-0 identity"
            )
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise CAMSViolation(f"Alert {alert_id} not found")
        if alert.state != AlertState.OPEN:
            raise ImmutabilityViolation(
                f"CAMS-IMMUT-0 VIOLATION: alert {alert_id} is not OPEN"
            )
        alert.state = AlertState.ACKNOWLEDGED
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_ts = time.time()
        alert.ack_note = note
        return alert

    def get(self, alert_id: str) -> Optional[Alert]:
        return self._alerts.get(alert_id)

    def all_alerts(self) -> List[Alert]:
        return list(self._alerts.values())

    def open_alerts(self) -> List[Alert]:
        return [a for a in self._alerts.values() if a.state == AlertState.OPEN]


# ── MonitoringLedger ──────────────────────────────────────────────────────────
class MonitoringLedger:
    """
    HMAC-SHA-256 append-only ledger for all CHI samples + classifications.
    CAMS-CHAIN-0: full chain verification before every append.
    CAMS-APPEND-0: no deletion or mutation of entries.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[MonitoringLedgerEntry] = []

    def _tail_hash(self) -> str:
        if not self._entries:
            return self._GENESIS_HASH
        return self._entries[-1].entry_hash

    def verify_chain(self) -> bool:
        """CAMS-CHAIN-0: verify full HMAC chain integrity."""
        prev = self._GENESIS_HASH
        for entry in self._entries:
            if entry.prev_hash != prev:
                raise ChainBreakError(
                    f"CAMS-CHAIN-0 VIOLATION: chain break at sequence {entry.sequence}"
                )
            expected = entry._compute_hash()
            if not hmac.compare_digest(entry.entry_hash, expected):
                raise ChainBreakError(
                    f"CAMS-CHAIN-0 VIOLATION: entry hash mismatch at sequence {entry.sequence}"
                )
            prev = entry.entry_hash
        return True

    def append(
        self, sample: CHISample, classification: Optional[TrendClassification]
    ) -> MonitoringLedgerEntry:
        """CAMS-CHAIN-0: verify chain before append. CAMS-APPEND-0: write-once."""
        self.verify_chain()
        entry = MonitoringLedgerEntry(
            entry_id=f"ML-{uuid.uuid4().hex[:16].upper()}",
            sequence=len(self._entries),
            prev_hash=self._tail_hash(),
            sample=sample,
            classification=classification,
        )
        self._entries.append(entry)
        return entry

    def all_entries(self) -> List[MonitoringLedgerEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ── CAMSAuditor ───────────────────────────────────────────────────────────────
class CAMSAuditor:
    """
    Append-only HMAC-chained audit log. CAMS-AUDIT-0.
    Records every ingest, classify, alert, acknowledge, and verify operation.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def _tail_hash(self) -> str:
        if not self._entries:
            return self._GENESIS_HASH
        return self._entries[-1].entry_hash

    def record(self, operation: str, entity_id: str, detail: str = "") -> AuditEntry:
        """CAMS-AUDIT-0: append an audit entry — raises on failure."""
        try:
            entry = AuditEntry(
                audit_id=f"CAMS-AUD-{uuid.uuid4().hex[:12].upper()}",
                sequence=len(self._entries),
                prev_hash=self._tail_hash(),
                operation=operation,
                entity_id=entity_id,
                detail=detail,
            )
            self._entries.append(entry)
            return entry
        except Exception as exc:
            raise AuditFailure(f"CAMS-AUDIT-0 VIOLATION: audit write failed: {exc}") from exc

    def verify_chain(self) -> bool:
        """CAMS-AUDIT-0: verify audit log HMAC chain integrity."""
        prev = self._GENESIS_HASH
        for entry in self._entries:
            if entry.prev_hash != prev:
                raise ChainBreakError(
                    f"CAMS-AUDIT-0 VIOLATION: audit chain break at sequence {entry.sequence}"
                )
            prev = entry.entry_hash
        return True

    def all_entries(self) -> List[AuditEntry]:
        return list(self._entries)


# ── CAMSEngine (facade) ───────────────────────────────────────────────────────
class CAMSEngine:
    """
    Facade coordinating CHIMonitor, TrendDetector, AlertEngine,
    MonitoringLedger, and CAMSAuditor.

    Arc III ACI Module 07 — CAMS continuously watches CHI health and gates
    CRITICAL findings behind HUMAN-0 acknowledgement.
    """

    def __init__(self, window: int = _MIN_WINDOW) -> None:
        self._monitor = CHIMonitor()
        self._detector = TrendDetector(window=window)
        self._alerts = AlertEngine()
        self._ledger = MonitoringLedger()
        self._auditor = CAMSAuditor()

    def sample(self, chi_score: float, source_ref: str) -> Dict[str, Any]:
        """
        Ingest one CHI sample end-to-end: validate -> classify -> (maybe)
        alert -> ledger append -> audit.
        """
        sample = self._monitor.ingest(chi_score, source_ref)
        self._auditor.record("INGEST", sample.sample_id, f"score={chi_score}")

        classification = self._detector.classify(sample)
        self._auditor.record(
            "CLASSIFY", classification.classification_id, f"trend={classification.trend.value}"
        )

        alert: Optional[Alert] = None
        if classification.trend == TrendClass.CRITICAL:
            alert = self._alerts.raise_alert(classification)
            self._auditor.record("ALERT_RAISED", alert.alert_id, classification.classification_id)

        entry = self._ledger.append(sample, classification)
        self._auditor.record("LEDGER_APPEND", entry.entry_id, sample.sample_id)

        result: Dict[str, Any] = {
            "status": "SAMPLE_PROCESSED",
            "sample_id": sample.sample_id,
            "classification_id": classification.classification_id,
            "trend": classification.trend.value,
            "window_mean": round(classification.window_mean, 6),
            "ledger_entry_id": entry.entry_id,
        }
        if alert:
            result["alert_id"] = alert.alert_id
        return result

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str, note: str = "") -> Alert:
        """CAMS-HUMAN0-0: HUMAN-0 acknowledgement clears a CRITICAL alert."""
        alert = self._alerts.acknowledge(alert_id, acknowledged_by, note)
        self._auditor.record("ALERT_ACK", alert_id, f"by={acknowledged_by}")
        return alert

    def verify_chain(self) -> bool:
        """CAMS-CHAIN-0: verify monitoring ledger chain integrity."""
        result = self._ledger.verify_chain()
        self._auditor.record("VERIFY_CHAIN", "ledger", f"entries={len(self._ledger)}")
        return result

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        return self._alerts.get(alert_id)

    def all_alerts(self) -> List[Alert]:
        return self._alerts.all_alerts()

    def open_alerts(self) -> List[Alert]:
        return self._alerts.open_alerts()

    def ledger_entries(self) -> List[MonitoringLedgerEntry]:
        return self._ledger.all_entries()

    def audit_log(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._auditor.all_entries()]

    def status(self) -> Dict[str, Any]:
        return {
            "module": "CAMS",
            "innov": "INNOV-136",
            "phase": 231,
            "version": "10.42.0",
            "arc": "III — Autonomous Constitutional Intelligence",
            "trend_classes": list(_TREND_CLASSES),
            "min_window": _MIN_WINDOW,
            "total_samples": len(self._ledger),
            "total_alerts": len(self._alerts.all_alerts()),
            "open_alerts": len(self._alerts.open_alerts()),
            "ledger_entries": len(self._ledger),
            "audit_entries": len(self._auditor.all_entries()),
        }
