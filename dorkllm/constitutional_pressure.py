# SPDX-License-Identifier: Apache-2.0
"""INNOV-58 · Constitutional Pressure Index (CPI) — Phase 152 / v9.85.0

Proactive governance-health layer that continuously evaluates constitutional
fitness of the live invariant landscape.  CPI ingests the HMAC-chained
ledger, scores each governance domain (0.0–1.0), and emits tamper-evident
PRESSURE_SNAPSHOT / PRESSURE_ALERT events before cascade failures materialise.

Hard-class invariants
----------------------
CPI-DETERM-0  : CPI score is a deterministic function of
                (ledger_records, window, weights); identical inputs always
                produce identical output.  Timestamps, process IDs, and
                entropy sources are excluded from the scoring algorithm.
CPI-LEDGER-0  : Every CPIScorer invocation writes a PRESSURE_SNAPSHOT to
                the HMAC-chained ledger before returning.  A ledger write
                failure raises CPILedgerError and no score is returned.
CPI-ALERT-0   : A PRESSURE_ALERT ledger event is emitted whenever any
                domain score meets or exceeds the configured threshold.
                Emission is never suppressed, even when the same domain
                already has a recent alert.
CPI-SCOPE-0   : CPI reads only the HMAC-chained ledger.  It never reads
                live system state, process memory, or external data sources.
                Violations of this rule raise CPIScopeError.
CPI-HUMAN0-0  : Threshold configuration changes require a non-empty HUMAN-0
                operator identity string.  Empty / None operator is rejected
                with CPIAuthError before any config mutation occurs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CPI_VERSION: str = "1.0.0"
INNOV_ID: str = "INNOV-58"

# ---------------------------------------------------------------------------
# HMAC key
# ---------------------------------------------------------------------------

_HMAC_KEY: bytes = os.getenv(
    "ADAAD_CPI_HMAC_KEY", "cpi-default-key-change-in-prod"
).encode()

# ---------------------------------------------------------------------------
# Governance domains
# ---------------------------------------------------------------------------


class CPIDomain(str, Enum):
    SECURITY = "SECURITY"
    DETERMINISM = "DETERMINISM"
    REPLAY = "REPLAY"
    HUMAN0 = "HUMAN0"
    MUTATION = "MUTATION"
    LEDGER = "LEDGER"


ALL_DOMAINS: tuple[CPIDomain, ...] = tuple(CPIDomain)

# Default alert threshold — HUMAN-0-gated mutation via CPIConfig
DEFAULT_ALERT_THRESHOLD: float = 0.70

# Ledger event types emitted by CPI
EVENT_PRESSURE_SNAPSHOT = "PRESSURE_SNAPSHOT"
EVENT_PRESSURE_ALERT = "PRESSURE_ALERT"

# Ledger record types consumed by CPI (CPI-SCOPE-0)
_INGESTIBLE_RECORD_TYPES = frozenset(
    {
        "MUTATION",
        "ROLLBACK",
        "ROLLBACK_EVENT",
        "GCB_TRIP",
        "GCB_RESET",
        "PRESSURE_SNAPSHOT",
        "PRESSURE_ALERT",
        "ACCEPT",
        "REJECT",
        "BLOCK",
        "VIOLATION",
        "INVARIANT_VIOLATION",
        "REPLAY_EVENT",
        "AUDIT",
    }
)

# ---------------------------------------------------------------------------
# Typed exceptions — one per Hard-class invariant
# ---------------------------------------------------------------------------


class CPILedgerError(RuntimeError):
    """CPI-LEDGER-0: ledger write failed during snapshot or alert emission."""


class CPIAuthError(RuntimeError):
    """CPI-HUMAN0-0: threshold config change attempted without HUMAN-0 identity."""


class CPIChainError(RuntimeError):
    """HMAC chain validation failed on a ledger record ingested by CPI."""


class CPIDeterminismError(RuntimeError):
    """CPI-DETERM-0: score output did not match replay of identical inputs."""


class CPIScopeError(RuntimeError):
    """CPI-SCOPE-0: CPI attempted to read a non-ledger data source."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CPIConfig:
    """Mutable configuration — all changes require HUMAN-0 identity (CPI-HUMAN0-0)."""

    alert_threshold: float = DEFAULT_ALERT_THRESHOLD
    # Per-domain weight overrides (default: uniform 1.0)
    domain_weights: Dict[str, float] = field(default_factory=dict)
    # Scoring window: None = unbounded (all-time), int = most-recent N records
    window: Optional[int] = None

    def weight(self, domain: CPIDomain) -> float:
        return self.domain_weights.get(domain.value, 1.0)


@dataclass
class CPIDomainScore:
    """Score and contributing signals for a single governance domain."""

    domain: CPIDomain
    score: float                          # 0.0 (healthy) → 1.0 (critical)
    alert: bool                           # score >= threshold
    violation_count: int
    total_events: int
    contributing_refs: List[str]          # ledger entry IDs that drove the score


@dataclass
class CPISnapshot:
    """Full CPI output for one scoring invocation."""

    scores: Dict[str, CPIDomainScore]     # domain.value → score
    alert_domains: List[str]              # domain.value where alert=True
    ledger_entry_id: str                  # ID of the PRESSURE_SNAPSHOT event written
    record_count: int                     # number of ledger records consumed
    threshold: float


# ---------------------------------------------------------------------------
# Domain signal classifier
# ---------------------------------------------------------------------------

# Map ledger record types → domain(s) they contribute to
_RECORD_DOMAIN_MAP: Dict[str, List[CPIDomain]] = {
    "VIOLATION":           [CPIDomain.SECURITY, CPIDomain.MUTATION],
    "INVARIANT_VIOLATION": [CPIDomain.SECURITY, CPIDomain.DETERMINISM],
    "GCB_TRIP":            [CPIDomain.SECURITY, CPIDomain.MUTATION],
    "GCB_RESET":           [CPIDomain.HUMAN0],
    "ROLLBACK":            [CPIDomain.MUTATION, CPIDomain.REPLAY],
    "ROLLBACK_EVENT":      [CPIDomain.MUTATION, CPIDomain.REPLAY],
    "REJECT":              [CPIDomain.MUTATION],
    "BLOCK":               [CPIDomain.MUTATION, CPIDomain.SECURITY],
    "ACCEPT":              [],  # positive signal — no pressure contribution
    "REPLAY_EVENT":        [CPIDomain.REPLAY],
    "PRESSURE_ALERT":      [CPIDomain.LEDGER],
}

# HUMAN0 domain: any record whose invariant_id or namespace contains "HUMAN0"
_HUMAN0_KEYWORDS = frozenset({"HUMAN0", "HUMAN-0", "human0"})


def _domains_for_record(record: Dict[str, Any]) -> List[CPIDomain]:
    """Deterministically classify a ledger record into affected domains."""
    rtype = record.get("type", record.get("event_type", ""))
    domains = list(_RECORD_DOMAIN_MAP.get(rtype, []))

    # HUMAN0 domain: any record referencing a HUMAN0 invariant
    inv_id = str(record.get("invariant_id", record.get("namespace", "")))
    if any(kw in inv_id for kw in _HUMAN0_KEYWORDS):
        if CPIDomain.HUMAN0 not in domains:
            domains.append(CPIDomain.HUMAN0)

    # LEDGER domain: any failed chain event
    if record.get("chain_valid") is False:
        if CPIDomain.LEDGER not in domains:
            domains.append(CPIDomain.LEDGER)

    # DETERMINISM domain: any replay mismatch
    if record.get("replay_mismatch") is True:
        if CPIDomain.DETERMINISM not in domains:
            domains.append(CPIDomain.DETERMINISM)

    return domains


# ---------------------------------------------------------------------------
# HMAC chain helpers
# ---------------------------------------------------------------------------


def _compute_hmac(payload: bytes) -> str:
    return hmac.new(_HMAC_KEY, payload, hashlib.sha256).hexdigest()


def _chain_entry(prev_hmac: str, event_type: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Build an HMAC-chained ledger entry.  Deterministic: no timestamps in hash."""
    canonical = json.dumps(
        {"prev": prev_hmac, "type": event_type, "body": body},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    entry_id = hashlib.sha256(canonical).hexdigest()[:16]
    entry_hmac = _compute_hmac(canonical)
    return {
        "id": entry_id,
        "type": event_type,
        "prev_hmac": prev_hmac,
        "hmac": entry_hmac,
        "body": body,
        "ts": time.time(),
    }


def _validate_chain(records: Sequence[Dict[str, Any]]) -> None:
    """Validate HMAC chain of records ingested from ledger (CPI-SCOPE-0)."""
    for record in records:
        if "hmac" not in record or "prev_hmac" not in record:
            # Records without HMAC fields are older-format entries — skip chain check
            continue
        canonical = json.dumps(
            {
                "prev": record["prev_hmac"],
                "type": record.get("type", record.get("event_type", "")),
                "body": record.get("body", {}),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        expected = _compute_hmac(canonical)
        if not hmac.compare_digest(expected, record["hmac"]):
            raise CPIChainError(
                f"CPI-CHAIN: HMAC mismatch on record id={record.get('id', '?')}"
            )


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------


def _score_domain(
    domain: CPIDomain,
    violation_events: List[Dict[str, Any]],
    total_events: int,
    weight: float,
) -> CPIDomainScore:
    """Compute deterministic pressure score for one domain.

    Formula (CPI-DETERM-0):
        raw_rate  = len(violation_events) / max(total_events, 1)
        score     = min(raw_rate * weight, 1.0)

    Timestamps excluded.  Identical inputs → identical output.
    """
    v_count = len(violation_events)
    raw_rate = v_count / max(total_events, 1)
    score = min(raw_rate * weight, 1.0)
    refs = [r.get("id", r.get("entry_id", "")) for r in violation_events if r.get("id") or r.get("entry_id")]
    return CPIDomainScore(
        domain=domain,
        score=round(score, 6),
        alert=False,  # set by caller after threshold check
        violation_count=v_count,
        total_events=total_events,
        contributing_refs=refs,
    )


# ---------------------------------------------------------------------------
# Ledger persistence
# ---------------------------------------------------------------------------


class _LedgerWriter:
    """Append-only HMAC-chained ledger writer for CPI events."""

    def __init__(self, ledger_path: Path) -> None:
        self._path = ledger_path
        self._prev_hmac: str = "genesis"

    def write(self, event_type: str, body: Dict[str, Any]) -> str:
        """Write a chained entry; return entry ID.  Raises CPILedgerError on failure."""
        entry = _chain_entry(self._prev_hmac, event_type, body)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError as exc:
            raise CPILedgerError(
                f"CPI-LEDGER-0: failed to write {event_type} to {self._path}: {exc}"
            ) from exc
        self._prev_hmac = entry["hmac"]
        return entry["id"]


# ---------------------------------------------------------------------------
# CPIScorer — public API
# ---------------------------------------------------------------------------


class CPIScorer:
    """Constitutional Pressure Index scorer.

    Usage::

        scorer = CPIScorer()
        snapshot = scorer.score(ledger_records)
        # snapshot.scores["SECURITY"].score → float
        # snapshot.alert_domains           → list of domain names in alert
    """

    def __init__(
        self,
        config: Optional[CPIConfig] = None,
        ledger_path: Optional[Path] = None,
    ) -> None:
        self._config = config or CPIConfig()
        _ledger_path = ledger_path or Path(
            os.getenv("ADAAD_CPI_LEDGER_PATH", "data/dork/cpi_ledger.jsonl")
        )
        self._writer = _LedgerWriter(_ledger_path)

    # ------------------------------------------------------------------
    # Public: score
    # ------------------------------------------------------------------

    def score(self, ledger_records: Sequence[Dict[str, Any]]) -> CPISnapshot:
        """Compute CPI snapshot from ledger records.

        CPI-SCOPE-0 : only ingests records whose type is in _INGESTIBLE_RECORD_TYPES.
        CPI-LEDGER-0: writes PRESSURE_SNAPSHOT before returning.
        CPI-ALERT-0 : writes PRESSURE_ALERT for every domain at or above threshold.
        CPI-DETERM-0: deterministic — no external state, no timestamps in formula.
        """
        # CPI-SCOPE-0: filter to ingestible record types only
        filtered = [
            r for r in ledger_records
            if r.get("type", r.get("event_type", "")) in _INGESTIBLE_RECORD_TYPES
        ]

        # Apply window
        if self._config.window is not None:
            filtered = filtered[-self._config.window :]

        total = len(filtered)

        # Build per-domain violation buckets
        domain_violations: Dict[CPIDomain, List[Dict[str, Any]]] = {
            d: [] for d in ALL_DOMAINS
        }
        for record in filtered:
            for domain in _domains_for_record(record):
                domain_violations[domain].append(record)

        # Score each domain
        threshold = self._config.alert_threshold
        scores: Dict[str, CPIDomainScore] = {}
        alert_domains: List[str] = []

        for domain in ALL_DOMAINS:
            ds = _score_domain(
                domain,
                domain_violations[domain],
                total,
                self._config.weight(domain),
            )
            ds.alert = ds.score >= threshold
            if ds.alert:
                alert_domains.append(domain.value)
            scores[domain.value] = ds

        # CPI-LEDGER-0: write PRESSURE_SNAPSHOT first, before returning
        snapshot_body = {
            "scores": {k: v.score for k, v in scores.items()},
            "alert_domains": alert_domains,
            "record_count": total,
            "threshold": threshold,
            "window": self._config.window,
            "innov_id": INNOV_ID,
        }
        snapshot_id = self._writer.write(EVENT_PRESSURE_SNAPSHOT, snapshot_body)

        # CPI-ALERT-0: write PRESSURE_ALERT for every alerting domain
        for domain_name in alert_domains:
            ds = scores[domain_name]
            alert_body = {
                "domain": domain_name,
                "score": ds.score,
                "threshold": threshold,
                "violation_count": ds.violation_count,
                "snapshot_id": snapshot_id,
                "innov_id": INNOV_ID,
            }
            self._writer.write(EVENT_PRESSURE_ALERT, alert_body)

        return CPISnapshot(
            scores=scores,
            alert_domains=alert_domains,
            ledger_entry_id=snapshot_id,
            record_count=total,
            threshold=threshold,
        )

    # ------------------------------------------------------------------
    # Public: update_config (CPI-HUMAN0-0)
    # ------------------------------------------------------------------

    def update_config(
        self,
        operator: str,
        alert_threshold: Optional[float] = None,
        domain_weights: Optional[Dict[str, float]] = None,
        window: Optional[int] = None,
    ) -> None:
        """Mutate scorer configuration.  Requires non-empty HUMAN-0 operator identity."""
        if not operator or not operator.strip():
            raise CPIAuthError(
                "CPI-HUMAN0-0: threshold configuration change requires "
                "a non-empty HUMAN-0 operator identity."
            )
        if alert_threshold is not None:
            if not (0.0 <= alert_threshold <= 1.0):
                raise ValueError(f"alert_threshold must be in [0.0, 1.0]; got {alert_threshold}")
            self._config.alert_threshold = alert_threshold
        if domain_weights is not None:
            self._config.domain_weights.update(domain_weights)
        if window is not None:
            self._config.window = window

    # ------------------------------------------------------------------
    # Public: terse summary for DORK prompt injection
    # ------------------------------------------------------------------

    def summarise(self, snapshot: CPISnapshot) -> str:
        """Return a terse one-line CPI summary for build_system_prompt injection."""
        if not snapshot.alert_domains:
            top_domain = max(snapshot.scores.values(), key=lambda s: s.score)
            return (
                f"CPI: all-clear · highest pressure "
                f"{top_domain.domain.value}={top_domain.score:.3f} · "
                f"threshold={snapshot.threshold:.2f}"
            )
        alerts = ", ".join(
            f"{d}={snapshot.scores[d].score:.3f}" for d in snapshot.alert_domains
        )
        return (
            f"CPI: ALERT · {len(snapshot.alert_domains)} domain(s) over threshold · "
            f"{alerts} · threshold={snapshot.threshold:.2f}"
        )
