# SPDX-License-Identifier: Apache-2.0
"""Phase 155 — INNOV-61 · CGTH — Constitutional Governance Telemetry Hub

A unified, hash-chained runtime telemetry aggregator for all ADAAD governance
components.  Every governance event — gate verdicts, pressure snapshots, throttle
decisions, invariant fires, mutation proposals, and DORK-PERM instrument snapshots
— is captured as a structured, cryptographically linked record and written to the
CGTH telemetry ledger.

The CGTH advances V10 Convergence Criterion 5 (Constitutional Archaeology Complete):
every governance event that ever occurred is structured, queryable, and tamper-evident.

Constitutional Invariants
==========================
CGTH-CHAIN-0   : Every telemetry event carries the HMAC-SHA256 of the previous
                 event record.  A chain break (missing or mismatched prev_hmac)
                 is a Hard-class violation.  An empty ledger is the one valid
                 chain root; its prev_hmac is ALL_ZEROS_64.
CGTH-DETERM-0  : Given identical (event_type, payload_canonical, prev_hmac),
                 emit_event() always produces the same event_id (SHA-256 digest).
                 The implementation MUST NOT embed wall-clock time in the hash.
CGTH-GATE-0    : Only registered governance components may emit telemetry events.
                 An unregistered emitter raises CGTHUnregisteredEmitterError.
                 Registration requires a component_id string scoped to a known
                 ADAAD governance module.
CGTH-PERSIST-0 : emit_event() writes the fully formed event record to the CGTH
                 ledger file before returning the event_id to the caller.
                 A failed write raises CGTHLedgerWriteError; the event is not
                 returned to the caller.
CGTH-HUMAN0-0  : The telemetry ledger is append-only.  Pruning, truncation, or
                 overwrite requires a signed HUMAN-0 authorisation record
                 (authority: "DUSTIN L REID") written as the final record of the
                 pruned segment.  Absent that record, any modification to the
                 ledger is a Hard-class violation.

Patent note (InnovativeAI LLC): The combination of (a) a unified cross-subsystem
governance event taxonomy, (b) hash-chained telemetry ledger, and (c) structured
queryability against that chain constitutes a novel Cryptographically Chained
Governance Telemetry Aggregation architecture for autonomous constitutional AI
systems — filed as IP under InnovativeAI LLC.

Author: DEVADAAD · Innovative AI LLC
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CGTH_CHAIN_ROOT_HMAC: str = "0" * 64  # sentinel prev_hmac for the first record
CGTH_HMAC_SECRET: bytes = b"ADAAD-CGTH-HMAC-2026"  # deterministic; not a secret key
HUMAN0_AUTHORITY: str = "DUSTIN L REID"

# Governance component registry — all known emitters
_KNOWN_COMPONENTS: frozenset[str] = frozenset(
    [
        "cpi",           # Constitutional Pressure Index
        "amt",           # Adaptive Mutation Throttle
        "cpag",          # Constitutional Pre-Admission Gate
        "cel_feed",      # Constitutional Evolution Loop Feed
        "circuit_breaker",
        "governed_rollback",
        "perm_engine",   # any DORK-PERM instrument
        "mutation_engine",
        "invariant_monitor",
        "cgth",          # self-telemetry
        "test_harness",  # permitted for testing
        "cgai",          # Constitutional Governance Anomaly Inspector (Phase 156)
        "ghi",           # Governance Health Index (Phase 157)
    ]
)


# ---------------------------------------------------------------------------
# Event taxonomy
# ---------------------------------------------------------------------------

class CGTHEventType(str, Enum):
    GATE_VERDICT          = "GATE_VERDICT"
    PRESSURE_SNAPSHOT     = "PRESSURE_SNAPSHOT"
    THROTTLE_DECISION     = "THROTTLE_DECISION"
    INVARIANT_FIRE        = "INVARIANT_FIRE"
    MUTATION_PROPOSED     = "MUTATION_PROPOSED"
    MUTATION_OUTCOME      = "MUTATION_OUTCOME"
    PERM_SNAPSHOT         = "PERM_SNAPSHOT"
    CIRCUIT_BREAK         = "CIRCUIT_BREAK"
    ROLLBACK_EXECUTED     = "ROLLBACK_EXECUTED"
    LEDGER_AUDIT          = "LEDGER_AUDIT"
    HUMAN0_AUTHORISATION  = "HUMAN0_AUTHORISATION"
    CGTH_INIT             = "CGTH_INIT"


# ---------------------------------------------------------------------------
# Exceptions (CGTH-CHAIN-0, CGTH-GATE-0, CGTH-PERSIST-0)
# ---------------------------------------------------------------------------

class CGTHChainError(Exception):
    """CGTH-CHAIN-0: HMAC chain integrity violation."""


class CGTHUnregisteredEmitterError(Exception):
    """CGTH-GATE-0: emitter component_id is not in the registered set."""


class CGTHLedgerWriteError(Exception):
    """CGTH-PERSIST-0: telemetry ledger write failed."""


class CGTHHuman0Required(Exception):
    """CGTH-HUMAN0-0: operation requires HUMAN-0 authorisation."""


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _canonical(obj: Any) -> str:
    """Stable JSON serialisation — sorted keys, no whitespace (CGTH-DETERM-0)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_event_id(event_type: str, payload_canonical: str, prev_hmac: str) -> str:
    """SHA-256 digest of (event_type‖payload_canonical‖prev_hmac).

    CGTH-DETERM-0: identical inputs → identical output; no wall-clock time.
    """
    raw = f"{event_type}|{payload_canonical}|{prev_hmac}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _compute_hmac(event_id: str) -> str:
    """HMAC-SHA256 of event_id using the fixed CGTH key.

    This links each record into the chain (CGTH-CHAIN-0).
    """
    return hmac.new(CGTH_HMAC_SECRET, event_id.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Telemetry record
# ---------------------------------------------------------------------------

class TelemetryRecord:
    """Immutable governance telemetry record."""

    __slots__ = (
        "event_id", "event_type", "component_id", "payload",
        "prev_hmac", "this_hmac", "seq",
    )

    def __init__(
        self,
        event_id: str,
        event_type: CGTHEventType,
        component_id: str,
        payload: Dict[str, Any],
        prev_hmac: str,
        this_hmac: str,
        seq: int,
    ) -> None:
        self.event_id    = event_id
        self.event_type  = event_type
        self.component_id = component_id
        self.payload     = payload
        self.prev_hmac   = prev_hmac
        self.this_hmac   = this_hmac
        self.seq         = seq

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id":     self.event_id,
            "event_type":   self.event_type.value,
            "component_id": self.component_id,
            "payload":      self.payload,
            "prev_hmac":    self.prev_hmac,
            "this_hmac":    self.this_hmac,
            "seq":          self.seq,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TelemetryRecord":
        return cls(
            event_id    = d["event_id"],
            event_type  = CGTHEventType(d["event_type"]),
            component_id = d["component_id"],
            payload     = d["payload"],
            prev_hmac   = d["prev_hmac"],
            this_hmac   = d["this_hmac"],
            seq         = d["seq"],
        )


# ---------------------------------------------------------------------------
# Ledger writer / reader
# ---------------------------------------------------------------------------

class _CGTHLedger:
    """Append-only JSONL ledger for CGTH events (CGTH-PERSIST-0, CGTH-HUMAN0-0)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: TelemetryRecord) -> None:
        """Write a single record to the ledger.  Raises CGTHLedgerWriteError on failure."""
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
                fh.flush()
        except OSError as exc:
            raise CGTHLedgerWriteError(f"CGTH-PERSIST-0: write failed: {exc}") from exc

    def read_all(self) -> List[TelemetryRecord]:
        """Return all records from the ledger in insertion order."""
        if not self._path.exists():
            return []
        records: List[TelemetryRecord] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(TelemetryRecord.from_dict(json.loads(line)))
        return records

    def tail(self, n: int = 100) -> List[TelemetryRecord]:
        """Return the last n records."""
        return self.read_all()[-n:]

    def last_hmac(self) -> str:
        """Return this_hmac of the last record, or CGTH_CHAIN_ROOT_HMAC if empty."""
        records = self.read_all()
        if not records:
            return CGTH_CHAIN_ROOT_HMAC
        return records[-1].this_hmac

    def last_seq(self) -> int:
        """Return seq of the last record, or -1 if empty."""
        records = self.read_all()
        if not records:
            return -1
        return records[-1].seq


# ---------------------------------------------------------------------------
# Chain validator
# ---------------------------------------------------------------------------

def verify_chain(records: Sequence[TelemetryRecord]) -> bool:
    """Verify HMAC chain integrity across a sequence of records.

    CGTH-CHAIN-0: raises CGTHChainError on first broken link.
    Returns True if chain is intact.
    """
    expected_prev = CGTH_CHAIN_ROOT_HMAC
    for idx, rec in enumerate(records):
        if rec.prev_hmac != expected_prev:
            raise CGTHChainError(
                f"CGTH-CHAIN-0: chain broken at seq={rec.seq} idx={idx}; "
                f"expected prev_hmac={expected_prev!r}, got {rec.prev_hmac!r}"
            )
        expected_this = _compute_hmac(rec.event_id)
        if rec.this_hmac != expected_this:
            raise CGTHChainError(
                f"CGTH-CHAIN-0: HMAC mismatch at seq={rec.seq}; "
                f"expected {expected_this!r}, got {rec.this_hmac!r}"
            )
        expected_prev = rec.this_hmac
    return True


# ---------------------------------------------------------------------------
# Main hub
# ---------------------------------------------------------------------------

class ConstitutionalGovernanceTelemetryHub:
    """CGTH — unified governance event aggregator.

    Usage::

        hub = ConstitutionalGovernanceTelemetryHub()
        event_id = hub.emit_event(
            component_id="cpi",
            event_type=CGTHEventType.PRESSURE_SNAPSHOT,
            payload={"domain": "MUTATION", "score": 0.73},
        )
        records = hub.query(event_type=CGTHEventType.PRESSURE_SNAPSHOT)
    """

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        _lp = ledger_path or Path(
            os.getenv("ADAAD_CGTH_LEDGER_PATH", "data/dork/cgth_telemetry.jsonl")
        )
        self._ledger = _CGTHLedger(_lp)

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    def emit_event(
        self,
        component_id: str,
        event_type: CGTHEventType,
        payload: Dict[str, Any],
    ) -> str:
        """Emit a governance telemetry event.

        CGTH-GATE-0   : component_id must be registered.
        CGTH-DETERM-0 : event_id is deterministic from (type, payload, prev_hmac).
        CGTH-PERSIST-0: record written before event_id returned.

        Returns the event_id string.
        """
        # CGTH-GATE-0
        if component_id not in _KNOWN_COMPONENTS:
            raise CGTHUnregisteredEmitterError(
                f"CGTH-GATE-0: component '{component_id}' is not a registered emitter."
            )

        prev_hmac        = self._ledger.last_hmac()
        seq              = self._ledger.last_seq() + 1
        payload_canonical = _canonical(payload)
        event_id         = _compute_event_id(
            event_type.value, payload_canonical, prev_hmac
        )
        this_hmac        = _compute_hmac(event_id)

        record = TelemetryRecord(
            event_id    = event_id,
            event_type  = event_type,
            component_id = component_id,
            payload     = payload,
            prev_hmac   = prev_hmac,
            this_hmac   = this_hmac,
            seq         = seq,
        )
        # CGTH-PERSIST-0
        self._ledger.append(record)
        return event_id

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        event_type: Optional[CGTHEventType] = None,
        component_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[TelemetryRecord]:
        """Return filtered records from the telemetry ledger."""
        records = self._ledger.read_all()
        if event_type is not None:
            records = [r for r in records if r.event_type == event_type]
        if component_id is not None:
            records = [r for r in records if r.component_id == component_id]
        return records[-limit:]

    def tail(self, n: int = 50) -> List[TelemetryRecord]:
        """Return the last n telemetry records."""
        return self._ledger.tail(n)

    # ------------------------------------------------------------------
    # Chain audit
    # ------------------------------------------------------------------

    def audit_chain(self) -> Dict[str, Any]:
        """Verify entire chain and return an audit summary.

        Emits a LEDGER_AUDIT event on successful verification.
        """
        records = self._ledger.read_all()
        intact  = verify_chain(records)
        summary = {
            "record_count": len(records),
            "chain_intact": intact,
            "last_seq":     records[-1].seq if records else -1,
            "last_hmac":    records[-1].this_hmac if records else CGTH_CHAIN_ROOT_HMAC,
        }
        self.emit_event(
            component_id="cgth",
            event_type=CGTHEventType.LEDGER_AUDIT,
            payload=summary,
        )
        return summary

    # ------------------------------------------------------------------
    # Snapshot (DORK-PERM aggregation)
    # ------------------------------------------------------------------

    def snapshot_perm_engines(self, engine_id: str, data: Dict[str, Any]) -> str:
        """Record a DORK-PERM instrument snapshot as a telemetry event."""
        return self.emit_event(
            component_id="perm_engine",
            event_type=CGTHEventType.PERM_SNAPSHOT,
            payload={"engine_id": engine_id, "data": data},
        )

    # ------------------------------------------------------------------
    # HUMAN-0 authorised prune (CGTH-HUMAN0-0)
    # ------------------------------------------------------------------

    def human0_authorised_prune(
        self,
        authority: str,
        reason: str,
        records_to_prune: int,
    ) -> str:
        """Record a HUMAN-0 prune authorisation event.

        CGTH-HUMAN0-0: only HUMAN-0 authority may authorise a prune.
        The actual ledger file mutation must be performed externally after
        this event is written — this method writes the authorisation record.
        """
        if authority != HUMAN0_AUTHORITY:
            raise CGTHHuman0Required(
                f"CGTH-HUMAN0-0: prune requires authority='{HUMAN0_AUTHORITY}'; "
                f"got '{authority}'."
            )
        return self.emit_event(
            component_id="cgth",
            event_type=CGTHEventType.HUMAN0_AUTHORISATION,
            payload={
                "authority":        authority,
                "reason":           reason,
                "records_to_prune": records_to_prune,
            },
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def get_default(cls) -> "ConstitutionalGovernanceTelemetryHub":
        """Return a hub backed by the default environment-configured ledger."""
        return cls()


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_hub: Optional[ConstitutionalGovernanceTelemetryHub] = None


def get_hub() -> ConstitutionalGovernanceTelemetryHub:
    """Return the process-singleton CGTH hub."""
    global _default_hub
    if _default_hub is None:
        _default_hub = ConstitutionalGovernanceTelemetryHub.get_default()
    return _default_hub


def emit(
    component_id: str,
    event_type: CGTHEventType,
    payload: Dict[str, Any],
) -> str:
    """Module-level emit — delegates to the singleton hub."""
    return get_hub().emit_event(component_id, event_type, payload)
