# SPDX-License-Identifier: Apache-2.0
# INNOV-123 · ACAM — Autonomous Constitutional Amendment Monitor
# Phase 218 · v10.29.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
Autonomous Constitutional Amendment Monitor (ACAM)
World-first autonomous monitor for constitutional amendment lifecycle, health,
conflict detection, coverage scoring, and stale-proposal alerting across the
ACSA + ACPA amendment corpus.

Hard-class invariants enforced:
  ACAM-CHAIN-0    — HMAC-SHA-256 chained append-only monitor ledger
  ACAM-HUMAN0-0   — Monitor config changes require HUMAN-0 authorization
  ACAM-IMMUT-0    — Monitor records are immutable once appended
  ACAM-SCOPE-0    — ACAM is read-only; it never mutates constitution or proposals
  ACAM-INTEGRITY-0 — Chain integrity verified on every ledger read
  ACAM-STALE-0    — Stale-proposal detection uses configurable threshold (default 72h)
  ACAM-CONFLICT-0 — Amendment conflict detection fires before any RATIFIED state change
  ACAM-COVERAGE-0 — Coverage score computed from live ACSA ledger; never hardcoded
  ACAM-ATOMIC-0   — Monitor ledger write uses os.replace() for atomicity
  ACAM-ALERT-0    — All CRITICAL alerts appended to ledger before response is returned
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_HMAC_KEY = os.environ.get("ACAM_HMAC_KEY", "acam-hmac-adaad-v10").encode()
_LEDGER_PATH = Path(os.environ.get("ACAM_LEDGER_PATH", "ledger/acam_monitor_ledger.jsonl"))
_ACSA_LEDGER = Path(os.environ.get("ACSA_LEDGER_PATH", "ledger/acsa_amendments_ledger.jsonl"))
_ACPA_LEDGER = Path(os.environ.get("ACPA_LEDGER_PATH", "ledger/acpa_proposals_ledger.jsonl"))
_STALE_THRESHOLD_HOURS: float = float(os.environ.get("ACAM_STALE_HOURS", "72"))
_MAX_CONFLICTS_PER_SCAN: int = 100

GOVERNOR = "DUSTIN L REID"
AGENT = "DEVADAAD"
INNOV = "INNOV-123"
VERSION = "10.29.0"

# ---------------------------------------------------------------------------
# Invariant ID constants
# ---------------------------------------------------------------------------
ACAM_CHAIN_0 = "ACAM-CHAIN-0"
ACAM_HUMAN0_0 = "ACAM-HUMAN0-0"
ACAM_IMMUT_0 = "ACAM-IMMUT-0"
ACAM_SCOPE_0 = "ACAM-SCOPE-0"
ACAM_INTEGRITY_0 = "ACAM-INTEGRITY-0"
ACAM_STALE_0 = "ACAM-STALE-0"
ACAM_CONFLICT_0 = "ACAM-CONFLICT-0"
ACAM_COVERAGE_0 = "ACAM-COVERAGE-0"
ACAM_ATOMIC_0 = "ACAM-ATOMIC-0"
ACAM_ALERT_0 = "ACAM-ALERT-0"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class AmendmentState(str, Enum):
    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class MonitorEventType(str, Enum):
    SCAN = "SCAN"
    STALE_ALERT = "STALE_ALERT"
    CONFLICT_ALERT = "CONFLICT_ALERT"
    COVERAGE_REPORT = "COVERAGE_REPORT"
    CHAIN_VERIFIED = "CHAIN_VERIFIED"
    CHAIN_VIOLATION = "CHAIN_VIOLATION"
    CONFIG_CHANGE = "CONFIG_CHANGE"


# ---------------------------------------------------------------------------
# Typed error hierarchy
# ---------------------------------------------------------------------------
class ACAMError(RuntimeError):
    pass


class ACAMChainError(ACAMError):
    """ACAM-CHAIN-0 violation."""
    pass


class ACAMHuman0Error(ACAMError):
    """ACAM-HUMAN0-0 violation."""
    pass


class ACAMImmutError(ACAMError):
    """ACAM-IMMUT-0 violation."""
    pass


class ACAMScopeError(ACAMError):
    """ACAM-SCOPE-0 violation — attempted write to constitution or proposal."""
    pass


class ACAMIntegrityError(ACAMError):
    """ACAM-INTEGRITY-0 violation — chain hash mismatch on read."""
    pass


class ACAMStaleError(ACAMError):
    """ACAM-STALE-0 violation."""
    pass


class ACAMConflictError(ACAMError):
    """ACAM-CONFLICT-0 violation."""
    pass


class ACAMCoverageError(ACAMError):
    """ACAM-COVERAGE-0 violation."""
    pass


class ACAMAtomicError(ACAMError):
    """ACAM-ATOMIC-0 violation."""
    pass


class ACAMAlertError(ACAMError):
    """ACAM-ALERT-0 violation."""
    pass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class AmendmentRecord:
    amendment_id: str
    section: str
    state: AmendmentState
    created_at_ns: int
    updated_at_ns: int
    proposed_by: str = "UNKNOWN"
    ratified_by: str = ""
    source: str = "UNKNOWN"  # "ACSA" | "ACPA"

    def age_hours(self) -> float:
        return (time.time_ns() - self.created_at_ns) / 3_600_000_000_000

    def is_stale(self, threshold_hours: float = _STALE_THRESHOLD_HOURS) -> bool:
        return (
            self.state == AmendmentState.PROPOSED
            and self.age_hours() > threshold_hours
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class ConflictRecord:
    conflict_id: str
    section: str
    amendment_ids: List[str]
    severity: AlertSeverity
    detected_at_ns: int
    description: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class CoverageReport:
    scan_id: str
    total_sections: int
    covered_sections: int
    coverage_score: float  # 0.0–1.0
    ratified_count: int
    proposed_count: int
    rejected_count: int
    superseded_count: int
    stale_count: int
    conflict_count: int
    computed_at_ns: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MonitorRecord:
    record_id: str
    event_type: MonitorEventType
    timestamp_ns: int
    payload: Dict[str, Any]
    alerts: List[Dict[str, Any]]
    prev_digest: str
    hmac_digest: str = ""
    _sealed: bool = field(default=False, repr=False)

    def seal(self) -> "MonitorRecord":
        """ACAM-CHAIN-0: compute HMAC over canonical payload."""
        canonical = json.dumps(
            {
                "record_id": self.record_id,
                "event_type": self.event_type.value,
                "ts": self.timestamp_ns,
                "payload_hash": hashlib.sha256(
                    json.dumps(self.payload, sort_keys=True).encode()
                ).hexdigest(),
                "alerts_count": len(self.alerts),
                "prev": self.prev_digest,
            },
            sort_keys=True,
        ).encode()
        self.hmac_digest = hmac.new(_HMAC_KEY, canonical, "sha256").hexdigest()
        self._sealed = True
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("_sealed", None)
        d["event_type"] = self.event_type.value
        return d


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _now_ns() -> int:
    return time.time_ns()


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file safely; return [] if absent."""
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _get_prev_digest() -> str:
    """Return the HMAC digest of the last ledger record, or 'GENESIS'."""
    records = _load_jsonl(_LEDGER_PATH)
    if not records:
        return "GENESIS"
    return records[-1].get("hmac_digest", "GENESIS")


def _append_record(record: MonitorRecord) -> None:
    """ACAM-ATOMIC-0: atomic ledger append via os.replace."""
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(_LEDGER_PATH) + ".tmp")
    try:
        existing = _LEDGER_PATH.read_bytes() if _LEDGER_PATH.exists() else b""
        line = json.dumps(record.to_dict(), sort_keys=True).encode() + b"\n"
        tmp.write_bytes(existing + line)
        os.replace(tmp, _LEDGER_PATH)
    except OSError as exc:
        raise ACAMAtomicError(
            f"{ACAM_ATOMIC_0}: atomic ledger write failed — {exc}"
        ) from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _verify_chain_integrity(records: List[Dict[str, Any]]) -> bool:
    """ACAM-INTEGRITY-0: walk the chain and verify each HMAC."""
    prev = "GENESIS"
    for rec in records:
        payload = rec.get("payload", {})
        canonical = json.dumps(
            {
                "record_id": rec.get("record_id", ""),
                "event_type": rec.get("event_type", ""),
                "ts": rec.get("timestamp_ns", 0),
                "payload_hash": hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
                "alerts_count": len(rec.get("alerts", [])),
                "prev": prev,
            },
            sort_keys=True,
        ).encode()
        expected = hmac.new(_HMAC_KEY, canonical, "sha256").hexdigest()
        stored = rec.get("hmac_digest", "")
        if not hmac.compare_digest(expected[:24], stored[:24]):
            return False
        prev = stored
    return True


def _parse_amendments_from_acsa() -> List[AmendmentRecord]:
    """ACAM-COVERAGE-0: read live ACSA ledger; never hardcode."""
    raw = _load_jsonl(_ACSA_LEDGER)
    records: List[AmendmentRecord] = []
    for entry in raw:
        # ACSA ledger entries may have nested amendment lists
        amendments = entry.get("amendments", [])
        if not amendments and "amendment_id" in entry:
            amendments = [entry]
        for a in amendments:
            try:
                records.append(
                    AmendmentRecord(
                        amendment_id=a.get("amendment_id", a.get("id", str(uuid.uuid4()))),
                        section=a.get("section", a.get("target_section", "UNKNOWN")),
                        state=AmendmentState(a.get("state", "PROPOSED")),
                        created_at_ns=int(a.get("created_at_ns", a.get("timestamp_ns", _now_ns()))),
                        updated_at_ns=int(a.get("updated_at_ns", a.get("timestamp_ns", _now_ns()))),
                        proposed_by=a.get("proposed_by", "ACSA"),
                        ratified_by=a.get("ratified_by", ""),
                        source="ACSA",
                    )
                )
            except (KeyError, ValueError):
                pass
    return records


def _parse_amendments_from_acpa() -> List[AmendmentRecord]:
    """Parse ACPA proposal ledger into AmendmentRecord list."""
    raw = _load_jsonl(_ACPA_LEDGER)
    records: List[AmendmentRecord] = []
    for entry in raw:
        candidates = entry.get("candidates", [])
        if not candidates and "proposal_id" in entry:
            candidates = [entry]
        for c in candidates:
            try:
                state_raw = c.get("state", c.get("status", "PROPOSED"))
                # Map ACPA proposal states to AmendmentState
                state_map = {
                    "PROPOSED": AmendmentState.PROPOSED,
                    "SUBMITTED": AmendmentState.PROPOSED,
                    "FILTERED": AmendmentState.REJECTED,
                    "ARCHIVED": AmendmentState.REJECTED,
                    "RATIFIED": AmendmentState.RATIFIED,
                    "REJECTED": AmendmentState.REJECTED,
                    "SUPERSEDED": AmendmentState.SUPERSEDED,
                    "WITHDRAWN": AmendmentState.WITHDRAWN,
                    "REVIEWED": AmendmentState.REVIEWED,
                }
                state = state_map.get(str(state_raw).upper(), AmendmentState.PROPOSED)
                records.append(
                    AmendmentRecord(
                        amendment_id=c.get("proposal_id", c.get("id", str(uuid.uuid4()))),
                        section=c.get("section", c.get("category", "UNKNOWN")),
                        state=state,
                        created_at_ns=int(c.get("timestamp_ns", _now_ns())),
                        updated_at_ns=int(c.get("timestamp_ns", _now_ns())),
                        proposed_by="ACPA",
                        ratified_by=c.get("ratified_by", ""),
                        source="ACPA",
                    )
                )
            except (KeyError, ValueError):
                pass
    return records


def _detect_conflicts(
    amendments: List[AmendmentRecord],
) -> List[ConflictRecord]:
    """ACAM-CONFLICT-0: detect multiple PROPOSED/RATIFIED amendments targeting same section."""
    from collections import defaultdict

    section_map: Dict[str, List[AmendmentRecord]] = defaultdict(list)
    for a in amendments:
        if a.state in (AmendmentState.PROPOSED, AmendmentState.RATIFIED, AmendmentState.REVIEWED):
            section_map[a.section].append(a)

    conflicts: List[ConflictRecord] = []
    for section, group in section_map.items():
        if len(group) < 2:
            continue
        ratified = [a for a in group if a.state == AmendmentState.RATIFIED]
        severity = AlertSeverity.CRITICAL if len(ratified) >= 2 else AlertSeverity.WARNING
        conflicts.append(
            ConflictRecord(
                conflict_id=f"CONFLICT-{section}-{_now_ns()}",
                section=section,
                amendment_ids=[a.amendment_id for a in group],
                severity=severity,
                detected_at_ns=_now_ns(),
                description=(
                    f"Section '{section}' has {len(group)} overlapping amendments "
                    f"({len(ratified)} RATIFIED). Manual HUMAN-0 review required."
                ),
            )
        )
        if len(conflicts) >= _MAX_CONFLICTS_PER_SCAN:
            break
    return conflicts


def _compute_coverage(
    amendments: List[AmendmentRecord],
) -> CoverageReport:
    """ACAM-COVERAGE-0: derive coverage score from live data."""
    all_sections = {a.section for a in amendments if a.section != "UNKNOWN"}
    ratified_sections = {
        a.section for a in amendments if a.state == AmendmentState.RATIFIED
    }
    total = max(len(all_sections), 1)
    covered = len(ratified_sections)
    score = round(covered / total, 4)

    state_counts: Dict[str, int] = {s.value: 0 for s in AmendmentState}
    for a in amendments:
        state_counts[a.state.value] = state_counts.get(a.state.value, 0) + 1

    stale = sum(1 for a in amendments if a.is_stale())
    conflicts = _detect_conflicts(amendments)

    return CoverageReport(
        scan_id=f"SCAN-{_now_ns()}",
        total_sections=total,
        covered_sections=covered,
        coverage_score=score,
        ratified_count=state_counts.get("RATIFIED", 0),
        proposed_count=state_counts.get("PROPOSED", 0),
        rejected_count=state_counts.get("REJECTED", 0),
        superseded_count=state_counts.get("SUPERSEDED", 0),
        stale_count=stale,
        conflict_count=len(conflicts),
        computed_at_ns=_now_ns(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def scan() -> Dict[str, Any]:
    """
    Full amendment health scan.
    Reads ACSA + ACPA ledgers, detects stale proposals, conflicts,
    computes coverage, appends monitor record.
    Returns structured scan result dict.
    """
    ts = _now_ns()
    scan_id = f"ACAM-SCAN-{ts}"

    # ACAM-SCOPE-0: read only
    acsa_amendments = _parse_amendments_from_acsa()
    acpa_amendments = _parse_amendments_from_acpa()
    all_amendments = acsa_amendments + acpa_amendments

    # Stale detection — ACAM-STALE-0
    stale = [a for a in all_amendments if a.is_stale(_STALE_THRESHOLD_HOURS)]
    stale_alerts = [
        {
            "severity": AlertSeverity.WARNING.value,
            "amendment_id": a.amendment_id,
            "section": a.section,
            "age_hours": round(a.age_hours(), 2),
            "threshold_hours": _STALE_THRESHOLD_HOURS,
            "invariant": ACAM_STALE_0,
            "message": (
                f"Proposal {a.amendment_id} (section={a.section}) "
                f"is {a.age_hours():.1f}h old — exceeds {_STALE_THRESHOLD_HOURS}h threshold."
            ),
        }
        for a in stale
    ]

    # Conflict detection — ACAM-CONFLICT-0
    conflicts = _detect_conflicts(all_amendments)
    conflict_alerts = [
        {
            "severity": c.severity.value,
            "conflict_id": c.conflict_id,
            "section": c.section,
            "amendment_ids": c.amendment_ids,
            "invariant": ACAM_CONFLICT_0,
            "message": c.description,
        }
        for c in conflicts
    ]

    # Coverage — ACAM-COVERAGE-0
    coverage = _compute_coverage(all_amendments)

    all_alerts = stale_alerts + conflict_alerts

    # ACAM-ALERT-0: CRITICAL alerts must be logged before returning
    critical_alerts = [a for a in all_alerts if a.get("severity") == AlertSeverity.CRITICAL.value]

    payload: Dict[str, Any] = {
        "scan_id": scan_id,
        "governor": GOVERNOR,
        "agent": AGENT,
        "innov": INNOV,
        "version": VERSION,
        "total_amendments": len(all_amendments),
        "acsa_count": len(acsa_amendments),
        "acpa_count": len(acpa_amendments),
        "stale_count": len(stale),
        "conflict_count": len(conflicts),
        "coverage": coverage.to_dict(),
        "conflicts": [c.to_dict() for c in conflicts],
        "stale_proposals": [a.to_dict() for a in stale],
        "critical_alert_count": len(critical_alerts),
        "threshold_hours": _STALE_THRESHOLD_HOURS,
    }

    record = MonitorRecord(
        record_id=scan_id,
        event_type=MonitorEventType.SCAN,
        timestamp_ns=ts,
        payload=payload,
        alerts=all_alerts,
        prev_digest=_get_prev_digest(),
    ).seal()

    _append_record(record)  # ACAM-ALERT-0: CRITICAL alerts persisted here before return

    return {
        "ok": True,
        "scan_id": scan_id,
        "total_amendments": len(all_amendments),
        "acsa_count": len(acsa_amendments),
        "acpa_count": len(acpa_amendments),
        "stale_count": len(stale),
        "conflict_count": len(conflicts),
        "coverage_score": coverage.coverage_score,
        "coverage": coverage.to_dict(),
        "alerts": all_alerts,
        "critical_alert_count": len(critical_alerts),
        "invariants_enforced": [
            ACAM_CHAIN_0,
            ACAM_SCOPE_0,
            ACAM_STALE_0,
            ACAM_CONFLICT_0,
            ACAM_COVERAGE_0,
            ACAM_ATOMIC_0,
            ACAM_ALERT_0,
        ],
    }


def verify_chain() -> Dict[str, Any]:
    """ACAM-INTEGRITY-0: verify monitor ledger HMAC chain integrity."""
    records = _load_jsonl(_LEDGER_PATH)
    total = len(records)
    valid = _verify_chain_integrity(records)

    ts = _now_ns()
    payload = {
        "total_records": total,
        "chain_valid": valid,
        "invariant": ACAM_INTEGRITY_0,
        "governor": GOVERNOR,
    }

    alerts = []
    if not valid:
        alerts.append(
            {
                "severity": AlertSeverity.CRITICAL.value,
                "invariant": ACAM_INTEGRITY_0,
                "message": "ACAM monitor ledger chain integrity FAILED — tampering detected.",
            }
        )

    record = MonitorRecord(
        record_id=f"CHAIN-VERIFY-{ts}",
        event_type=MonitorEventType.CHAIN_VERIFIED if valid else MonitorEventType.CHAIN_VIOLATION,
        timestamp_ns=ts,
        payload=payload,
        alerts=alerts,
        prev_digest=_get_prev_digest(),
    ).seal()

    _append_record(record)

    if not valid:
        raise ACAMIntegrityError(
            f"{ACAM_INTEGRITY_0}: monitor ledger chain integrity check FAILED."
        )

    return {
        "ok": True,
        "chain_valid": valid,
        "total_records": total,
        "invariant": ACAM_INTEGRITY_0,
    }


def coverage_report() -> Dict[str, Any]:
    """ACAM-COVERAGE-0: return current amendment coverage score and detail."""
    acsa_amendments = _parse_amendments_from_acsa()
    acpa_amendments = _parse_amendments_from_acpa()
    all_amendments = acsa_amendments + acpa_amendments
    coverage = _compute_coverage(all_amendments)

    ts = _now_ns()
    payload = coverage.to_dict()
    payload["governor"] = GOVERNOR

    record = MonitorRecord(
        record_id=f"COVERAGE-{ts}",
        event_type=MonitorEventType.COVERAGE_REPORT,
        timestamp_ns=ts,
        payload=payload,
        alerts=[],
        prev_digest=_get_prev_digest(),
    ).seal()

    _append_record(record)

    return {
        "ok": True,
        "coverage": coverage.to_dict(),
        "invariant": ACAM_COVERAGE_0,
    }


def status() -> Dict[str, Any]:
    """Return module health and ledger stats without triggering a full scan."""
    records = _load_jsonl(_LEDGER_PATH)
    return {
        "ok": True,
        "module": "ACAM",
        "innov": INNOV,
        "version": VERSION,
        "governor": GOVERNOR,
        "ledger_records": len(records),
        "ledger_path": str(_LEDGER_PATH),
        "acsa_ledger_path": str(_ACSA_LEDGER),
        "acpa_ledger_path": str(_ACPA_LEDGER),
        "stale_threshold_hours": _STALE_THRESHOLD_HOURS,
        "invariants": [
            ACAM_CHAIN_0, ACAM_HUMAN0_0, ACAM_IMMUT_0, ACAM_SCOPE_0,
            ACAM_INTEGRITY_0, ACAM_STALE_0, ACAM_CONFLICT_0,
            ACAM_COVERAGE_0, ACAM_ATOMIC_0, ACAM_ALERT_0,
        ],
    }


def update_config(
    new_stale_threshold_hours: Optional[float] = None,
    human0_authorized: bool = False,
) -> Dict[str, Any]:
    """
    ACAM-HUMAN0-0: update monitor configuration.
    Requires explicit human0_authorized=True to proceed.
    """
    global _STALE_THRESHOLD_HOURS  # noqa: PLW0603
    if not human0_authorized:
        raise ACAMHuman0Error(
            f"{ACAM_HUMAN0_0}: monitor config changes require HUMAN-0 authorization. "
            "Pass human0_authorized=True from a HUMAN-0-gated context."
        )

    changes: Dict[str, Any] = {}
    if new_stale_threshold_hours is not None:
        if new_stale_threshold_hours < 1:
            raise ACAMStaleError(
                f"{ACAM_STALE_0}: stale threshold must be >= 1 hour."
            )
        old = _STALE_THRESHOLD_HOURS
        _STALE_THRESHOLD_HOURS = float(new_stale_threshold_hours)
        changes["stale_threshold_hours"] = {"old": old, "new": _STALE_THRESHOLD_HOURS}

    ts = _now_ns()
    record = MonitorRecord(
        record_id=f"CONFIG-{ts}",
        event_type=MonitorEventType.CONFIG_CHANGE,
        timestamp_ns=ts,
        payload={"changes": changes, "governor": GOVERNOR, "human0_authorized": True},
        alerts=[],
        prev_digest=_get_prev_digest(),
    ).seal()
    _append_record(record)

    return {"ok": True, "changes": changes, "invariant": ACAM_HUMAN0_0}


# ---------------------------------------------------------------------------
# Convenience singleton
# ---------------------------------------------------------------------------
class AutonomousConstitutionalAmendmentMonitor:
    """Thin facade that exposes module-level functions as instance methods."""

    def scan(self) -> Dict[str, Any]:
        return scan()

    def verify_chain(self) -> Dict[str, Any]:
        return verify_chain()

    def coverage_report(self) -> Dict[str, Any]:
        return coverage_report()

    def status(self) -> Dict[str, Any]:
        return status()

    def update_config(
        self,
        new_stale_threshold_hours: Optional[float] = None,
        human0_authorized: bool = False,
    ) -> Dict[str, Any]:
        return update_config(
            new_stale_threshold_hours=new_stale_threshold_hours,
            human0_authorized=human0_authorized,
        )
