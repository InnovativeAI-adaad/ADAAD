# SPDX-License-Identifier: Apache-2.0
"""
constitutional_autonomous_cycle_governor.py
Phase 232 · INNOV-137 · CACG — Constitutional Autonomous Cycle Governor
World-first cryptographically governed orchestrator for the full Arc III
Autonomous Constitutional Intelligence cycle, enforcing deterministic
per-stage timeouts and routing stalled cycles to a non-delegable HUMAN-0
escalation gate.

Author  : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 08 (capstone)

CACG is the Arc III governance capstone: it does not replace CASL, CADE,
CAPE/CAVE, CAOE, CALI, CACP, or CAMS — it orchestrates them. A "cycle" is one
full pass of the ACI pipeline. CACG tracks which stage a cycle is in,
enforces a fixed deterministic timeout per stage, and — when a stage stalls
past its timeout — seals the cycle as TIMED_OUT and raises exactly one
escalation that only a non-empty HUMAN-0 identity may resolve.
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
from typing import Any, Dict, List, Optional, Tuple

# ── Hard-class invariant identifiers ─────────────────────────────────────────
# CACG-CHAIN-0    : All cycle ledger entries HMAC-SHA-256 chained
# CACG-APPEND-0   : Cycle ledger is append-only — no mutation or deletion
# CACG-STAGE-0    : Exactly 7 fixed, ordered ACI stages; advancement must
#                   follow that exact order — out-of-order or unknown stage
#                   names are rejected
# CACG-SCOPE-0    : Cycle status confined to OPEN, COMPLETED, TIMED_OUT
# CACG-DETERM-0   : Timeout enforcement fully deterministic — fixed per-stage
#                   threshold, no RNG, pure timestamp comparison
# CACG-TIMEOUT-0  : A stage exceeding its fixed timeout deterministically
#                   transitions the cycle to TIMED_OUT
# CACG-ESCALATE-0 : Every TIMED_OUT cycle produces exactly one Escalation
# CACG-HUMAN0-0   : Escalation resolution requires a non-empty HUMAN-0
#                   identity
# CACG-IMMUT-0    : Sealed cycle records and escalations are immutable after
#                   creation, except the single permitted OPEN-escalation ->
#                   RESOLVED transition
# CACG-AUDIT-0    : Every CACG operation sealed in a parallel HMAC-chained
#                   audit log

# CACG-STAGE-0: fixed ordered Arc III ACI pipeline stages
_CYCLE_STAGES: Tuple[str, ...] = (
    "CASL",     # constitutional health synthesis
    "CADE",     # PROMOTE/HOLD/REJECT/DEFER decision
    "EXECUTE",  # CAPE (promote) or CAVE (hold/reject/defer)
    "CAOE",     # outcome evaluation
    "CALI",     # learning / threshold recommendation
    "CACP",     # convergence proof
    "CAMS",     # live monitoring
)
_STAGE_COUNT = len(_CYCLE_STAGES)
if _STAGE_COUNT != 7:
    raise RuntimeError(
        f"CACG-STAGE-0 VIOLATION: expected exactly 7 ACI cycle stages, "
        f"found {_STAGE_COUNT}"
    )
_STAGE_INDEX: Dict[str, int] = {s: i for i, s in enumerate(_CYCLE_STAGES)}

_CYCLE_STATUSES = ("OPEN", "COMPLETED", "TIMED_OUT")

_HMAC_SECRET = os.environ.get(
    "CACG_HMAC_SECRET", "cacg-hmac-secret-DUSTIN-L-REID-v10-ArcIII"
).encode()

# CACG-DETERM-0: fixed deterministic per-stage timeout (seconds)
_STAGE_TIMEOUT_SECONDS = float(os.environ.get("CACG_STAGE_TIMEOUT_SECONDS", "1800"))


def _hmac_digest(payload: str) -> str:
    return hmac.new(_HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()


# ── Typed exception hierarchy ─────────────────────────────────────────────────
class CACGViolation(RuntimeError):
    """Base class for all CACG Hard-class invariant violations."""


class ChainBreakError(CACGViolation):
    """CACG-CHAIN-0: HMAC chain integrity broken."""


class AppendViolation(CACGViolation):
    """CACG-APPEND-0: Attempted mutation or deletion of cycle ledger."""


class StageError(CACGViolation):
    """CACG-STAGE-0: Unknown stage name or out-of-order advancement."""


class ScopeViolation(CACGViolation):
    """CACG-SCOPE-0: Unrecognized cycle status encountered."""


class DeterminismViolation(CACGViolation):
    """CACG-DETERM-0: Non-deterministic timeout enforcement detected."""


class TimeoutStateError(CACGViolation):
    """CACG-TIMEOUT-0: Timeout transition attempted on a non-OPEN cycle."""


class EscalationError(CACGViolation):
    """CACG-ESCALATE-0: Escalation raised for a non-TIMED_OUT cycle, or duplicate."""


class HUMAN0ResolveError(CACGViolation):
    """CACG-HUMAN0-0: Escalation resolution requires non-empty HUMAN-0 identity."""


class ImmutabilityViolation(CACGViolation):
    """CACG-IMMUT-0: Attempt to mutate a sealed cycle record or escalation."""


class AuditFailure(CACGViolation):
    """CACG-AUDIT-0: Audit ledger write failed."""


# ── Enums ──────────────────────────────────────────────────────────────────────
class CycleStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"


class EscalationState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


# ── Data structures ────────────────────────────────────────────────────────────
@dataclass
class CycleRecord:
    """
    A single ACI cycle traversal.
    CACG-STAGE-0: stage_index tracks position in the fixed 7-stage order.
    CACG-SCOPE-0: status confined to OPEN / COMPLETED / TIMED_OUT.
    """
    cycle_id: str
    cycle_ref: str
    status: CycleStatus
    stage_index: int
    current_stage: str
    stage_started_ts: float
    opened_ts: float
    completed_ts: Optional[float] = None
    timed_out_ts: Optional[float] = None
    stage_history: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "cycle_ref": self.cycle_ref,
            "status": self.status.value,
            "stage_index": self.stage_index,
            "current_stage": self.current_stage,
            "stage_started_ts": self.stage_started_ts,
            "opened_ts": self.opened_ts,
            "completed_ts": self.completed_ts,
            "timed_out_ts": self.timed_out_ts,
            "stage_history": list(self.stage_history),
        }


@dataclass
class Escalation:
    """
    Raised for a TIMED_OUT cycle. CACG-ESCALATE-0: exactly one per cycle.
    CACG-HUMAN0-0: resolution requires non-empty HUMAN-0 identity.
    CACG-IMMUT-0: only OPEN -> RESOLVED transition is permitted.
    """
    escalation_id: str
    cycle_id: str
    stalled_stage: str
    raised_ts: float
    state: EscalationState = EscalationState.OPEN
    resolved_by: Optional[str] = None
    resolved_ts: Optional[float] = None
    resolution_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "cycle_id": self.cycle_id,
            "stalled_stage": self.stalled_stage,
            "raised_ts": self.raised_ts,
            "state": self.state.value,
            "resolved_by": self.resolved_by,
            "resolved_ts": self.resolved_ts,
            "resolution_note": self.resolution_note,
        }


@dataclass
class CycleLedgerEntry:
    """
    HMAC-SHA-256 chained ledger entry wrapping a snapshot of a cycle state
    transition. CACG-CHAIN-0: prev_hash links form an unbreakable chain.
    CACG-APPEND-0: entries are write-once.

    NOTE: cycle state is captured as an immutable snapshot at append time
    (cycle_id / status_snapshot / stage_index_snapshot), never as a live
    reference to the mutable CycleRecord — CycleRecord continues to mutate
    after later stage advances, and re-deriving the hash from a live
    reference would silently invalidate earlier entries' hashes.
    """
    entry_id: str
    sequence: int
    prev_hash: str
    operation: str
    cycle_id: str
    status_snapshot: str
    stage_index_snapshot: int
    entry_hash: str = field(default="", init=False)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps({
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "operation": self.operation,
            "cycle_id": self.cycle_id,
            "status": self.status_snapshot,
            "stage_index": self.stage_index_snapshot,
            "ts": self.ts,
        }, sort_keys=True)
        return _hmac_digest(payload)


@dataclass
class AuditEntry:
    """Single entry in the parallel HMAC-chained audit log. CACG-AUDIT-0."""
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


# ── CycleOrchestrator ─────────────────────────────────────────────────────────
class CycleOrchestrator:
    """
    Opens cycles and advances them through the fixed 7-stage ACI order.
    CACG-STAGE-0: exactly 7 stages, strict order.
    CACG-SCOPE-0: status confined to OPEN / COMPLETED / TIMED_OUT.
    CACG-IMMUT-0: only OPEN cycles may be advanced.
    """

    def __init__(self) -> None:
        self._cycles: Dict[str, CycleRecord] = {}

    def open_cycle(self, cycle_ref: str) -> CycleRecord:
        if not cycle_ref or not cycle_ref.strip():
            raise StageError("CACG-STAGE-0 VIOLATION: cycle_ref must be non-empty")
        now = time.time()
        record = CycleRecord(
            cycle_id=f"CACG-{uuid.uuid4().hex[:16].upper()}",
            cycle_ref=cycle_ref,
            status=CycleStatus.OPEN,
            stage_index=0,
            current_stage=_CYCLE_STAGES[0],
            stage_started_ts=now,
            opened_ts=now,
            stage_history=[_CYCLE_STAGES[0]],
        )
        self._cycles[record.cycle_id] = record
        return record

    def advance(self, cycle_id: str, stage: str) -> CycleRecord:
        """
        CACG-STAGE-0: `stage` must be the next stage in fixed order.
        CACG-IMMUT-0: only OPEN cycles may advance.
        """
        record = self._cycles.get(cycle_id)
        if record is None:
            raise CACGViolation(f"Cycle {cycle_id} not found")
        if record.status != CycleStatus.OPEN:
            raise ImmutabilityViolation(
                f"CACG-IMMUT-0 VIOLATION: cycle {cycle_id} is not OPEN"
            )
        if stage not in _STAGE_INDEX:
            raise StageError(
                f"CACG-STAGE-0 VIOLATION: unknown stage '{stage}'"
            )
        expected_index = record.stage_index + 1
        if _STAGE_INDEX[stage] != expected_index:
            raise StageError(
                f"CACG-STAGE-0 VIOLATION: expected stage "
                f"'{_CYCLE_STAGES[expected_index] if expected_index < _STAGE_COUNT else '<none>'}' "
                f"(index {expected_index}), got '{stage}' (index {_STAGE_INDEX[stage]})"
            )
        record.stage_index = expected_index
        record.current_stage = stage
        record.stage_started_ts = time.time()
        record.stage_history.append(stage)
        if expected_index == _STAGE_COUNT - 1 and stage == _CYCLE_STAGES[-1]:
            # last stage entered — caller completes explicitly via complete()
            pass
        return record

    def complete(self, cycle_id: str) -> CycleRecord:
        """Seal a cycle as COMPLETED once it has reached the final stage."""
        record = self._cycles.get(cycle_id)
        if record is None:
            raise CACGViolation(f"Cycle {cycle_id} not found")
        if record.status != CycleStatus.OPEN:
            raise ImmutabilityViolation(
                f"CACG-IMMUT-0 VIOLATION: cycle {cycle_id} is not OPEN"
            )
        if record.current_stage != _CYCLE_STAGES[-1]:
            raise StageError(
                f"CACG-STAGE-0 VIOLATION: cycle {cycle_id} has not reached the "
                f"final stage '{_CYCLE_STAGES[-1]}' (currently '{record.current_stage}')"
            )
        record.status = CycleStatus.COMPLETED
        record.completed_ts = time.time()
        return record

    def get(self, cycle_id: str) -> Optional[CycleRecord]:
        return self._cycles.get(cycle_id)

    def all_cycles(self) -> List[CycleRecord]:
        return list(self._cycles.values())

    def open_cycles(self) -> List[CycleRecord]:
        return [c for c in self._cycles.values() if c.status == CycleStatus.OPEN]


# ── TimeoutEnforcer ───────────────────────────────────────────────────────────
class TimeoutEnforcer:
    """
    Deterministically transitions stalled OPEN cycles to TIMED_OUT.
    CACG-DETERM-0: fixed per-stage threshold, pure timestamp comparison.
    CACG-TIMEOUT-0: only OPEN cycles may time out.
    """

    def __init__(self, timeout_seconds: float = _STAGE_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def check(self, record: CycleRecord, now: Optional[float] = None) -> bool:
        """
        Returns True and mutates record to TIMED_OUT if the current stage
        has exceeded the fixed timeout threshold. `now` may be injected for
        deterministic testing; defaults to time.time().
        """
        if record.status != CycleStatus.OPEN:
            raise TimeoutStateError(
                f"CACG-TIMEOUT-0 VIOLATION: cycle {record.cycle_id} is not OPEN"
            )
        check_ts = now if now is not None else time.time()
        elapsed = check_ts - record.stage_started_ts
        if elapsed > self._timeout_seconds:
            record.status = CycleStatus.TIMED_OUT
            record.timed_out_ts = check_ts
            return True
        return False


# ── EscalationEngine ──────────────────────────────────────────────────────────
class EscalationEngine:
    """
    Raises and resolves escalations for TIMED_OUT cycles.
    CACG-ESCALATE-0: exactly one escalation per TIMED_OUT cycle.
    CACG-HUMAN0-0: resolution requires non-empty HUMAN-0 identity.
    CACG-IMMUT-0: only OPEN -> RESOLVED transition permitted.
    """

    def __init__(self) -> None:
        self._escalations: Dict[str, Escalation] = {}
        self._by_cycle: Dict[str, str] = {}

    def raise_escalation(self, record: CycleRecord) -> Escalation:
        if record.status != CycleStatus.TIMED_OUT:
            raise EscalationError(
                "CACG-ESCALATE-0 VIOLATION: escalations may only be raised for "
                f"TIMED_OUT cycles, got {record.status.value}"
            )
        if record.cycle_id in self._by_cycle:
            raise ImmutabilityViolation(
                f"CACG-ESCALATE-0 VIOLATION: escalation already raised for cycle "
                f"{record.cycle_id}"
            )
        escalation = Escalation(
            escalation_id=f"CACG-ESC-{uuid.uuid4().hex[:16].upper()}",
            cycle_id=record.cycle_id,
            stalled_stage=record.current_stage,
            raised_ts=time.time(),
        )
        self._escalations[escalation.escalation_id] = escalation
        self._by_cycle[record.cycle_id] = escalation.escalation_id
        return escalation

    def resolve(self, escalation_id: str, resolved_by: str, note: str = "") -> Escalation:
        if not resolved_by or not resolved_by.strip():
            raise HUMAN0ResolveError(
                "CACG-HUMAN0-0 VIOLATION: resolved_by must be non-empty HUMAN-0 identity"
            )
        escalation = self._escalations.get(escalation_id)
        if escalation is None:
            raise CACGViolation(f"Escalation {escalation_id} not found")
        if escalation.state != EscalationState.OPEN:
            raise ImmutabilityViolation(
                f"CACG-IMMUT-0 VIOLATION: escalation {escalation_id} is not OPEN"
            )
        escalation.state = EscalationState.RESOLVED
        escalation.resolved_by = resolved_by
        escalation.resolved_ts = time.time()
        escalation.resolution_note = note
        return escalation

    def get(self, escalation_id: str) -> Optional[Escalation]:
        return self._escalations.get(escalation_id)

    def all_escalations(self) -> List[Escalation]:
        return list(self._escalations.values())

    def open_escalations(self) -> List[Escalation]:
        return [e for e in self._escalations.values() if e.state == EscalationState.OPEN]


# ── CycleLedger ───────────────────────────────────────────────────────────────
class CycleLedger:
    """
    HMAC-SHA-256 append-only ledger of cycle state transitions.
    CACG-CHAIN-0: full chain verification before every append.
    CACG-APPEND-0: no deletion or mutation of entries.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[CycleLedgerEntry] = []

    def _tail_hash(self) -> str:
        if not self._entries:
            return self._GENESIS_HASH
        return self._entries[-1].entry_hash

    def verify_chain(self) -> bool:
        """CACG-CHAIN-0: verify full HMAC chain integrity."""
        prev = self._GENESIS_HASH
        for entry in self._entries:
            if entry.prev_hash != prev:
                raise ChainBreakError(
                    f"CACG-CHAIN-0 VIOLATION: chain break at sequence {entry.sequence}"
                )
            expected = entry._compute_hash()
            if not hmac.compare_digest(entry.entry_hash, expected):
                raise ChainBreakError(
                    f"CACG-CHAIN-0 VIOLATION: entry hash mismatch at sequence {entry.sequence}"
                )
            prev = entry.entry_hash
        return True

    def append(self, operation: str, cycle: CycleRecord) -> CycleLedgerEntry:
        """CACG-CHAIN-0: verify chain before append. CACG-APPEND-0: write-once.
        Captures an immutable snapshot of cycle.status/stage_index at this
        instant — see CycleLedgerEntry docstring."""
        self.verify_chain()
        entry = CycleLedgerEntry(
            entry_id=f"CL-{uuid.uuid4().hex[:16].upper()}",
            sequence=len(self._entries),
            prev_hash=self._tail_hash(),
            operation=operation,
            cycle_id=cycle.cycle_id,
            status_snapshot=cycle.status.value,
            stage_index_snapshot=cycle.stage_index,
        )
        self._entries.append(entry)
        return entry

    def all_entries(self) -> List[CycleLedgerEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ── CACGAuditor ───────────────────────────────────────────────────────────────
class CACGAuditor:
    """
    Append-only HMAC-chained audit log. CACG-AUDIT-0.
    Records every open, advance, complete, timeout, escalate, and resolve
    operation.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def _tail_hash(self) -> str:
        if not self._entries:
            return self._GENESIS_HASH
        return self._entries[-1].entry_hash

    def record(self, operation: str, entity_id: str, detail: str = "") -> AuditEntry:
        """CACG-AUDIT-0: append an audit entry — raises on failure."""
        try:
            entry = AuditEntry(
                audit_id=f"CACG-AUD-{uuid.uuid4().hex[:12].upper()}",
                sequence=len(self._entries),
                prev_hash=self._tail_hash(),
                operation=operation,
                entity_id=entity_id,
                detail=detail,
            )
            self._entries.append(entry)
            return entry
        except Exception as exc:
            raise AuditFailure(f"CACG-AUDIT-0 VIOLATION: audit write failed: {exc}") from exc

    def all_entries(self) -> List[AuditEntry]:
        return list(self._entries)


# ── CACGEngine (facade) ───────────────────────────────────────────────────────
class CACGEngine:
    """
    Facade coordinating CycleOrchestrator, TimeoutEnforcer, EscalationEngine,
    CycleLedger, and CACGAuditor.

    Arc III ACI Module 08 (capstone) — CACG orchestrates the full 7-stage
    cycle that every other Arc III module participates in.
    """

    def __init__(self, timeout_seconds: float = _STAGE_TIMEOUT_SECONDS) -> None:
        self._orchestrator = CycleOrchestrator()
        self._timeout = TimeoutEnforcer(timeout_seconds=timeout_seconds)
        self._escalation = EscalationEngine()
        self._ledger = CycleLedger()
        self._auditor = CACGAuditor()

    def open_cycle(self, cycle_ref: str) -> Dict[str, Any]:
        record = self._orchestrator.open_cycle(cycle_ref)
        self._auditor.record("OPEN_CYCLE", record.cycle_id, f"ref={cycle_ref}")
        entry = self._ledger.append("OPEN_CYCLE", record)
        self._auditor.record("LEDGER_APPEND", entry.entry_id, record.cycle_id)
        return record.to_dict()

    def advance(self, cycle_id: str, stage: str) -> Dict[str, Any]:
        record = self._orchestrator.advance(cycle_id, stage)
        self._auditor.record("ADVANCE", cycle_id, f"stage={stage}")
        entry = self._ledger.append("ADVANCE", record)
        self._auditor.record("LEDGER_APPEND", entry.entry_id, cycle_id)
        return record.to_dict()

    def complete(self, cycle_id: str) -> Dict[str, Any]:
        record = self._orchestrator.complete(cycle_id)
        self._auditor.record("COMPLETE", cycle_id, "")
        entry = self._ledger.append("COMPLETE", record)
        self._auditor.record("LEDGER_APPEND", entry.entry_id, cycle_id)
        return record.to_dict()

    def check_timeout(self, cycle_id: str, now: Optional[float] = None) -> Dict[str, Any]:
        """
        CACG-TIMEOUT-0 / CACG-DETERM-0: check a single OPEN cycle for stall.
        CACG-ESCALATE-0: TIMED_OUT triggers exactly one escalation.
        """
        record = self._orchestrator.get(cycle_id)
        if record is None:
            raise CACGViolation(f"Cycle {cycle_id} not found")
        timed_out = self._timeout.check(record, now=now)
        self._auditor.record(
            "TIMEOUT_CHECK", cycle_id, f"timed_out={timed_out} stage={record.current_stage}"
        )
        result = record.to_dict()
        if timed_out:
            entry = self._ledger.append("TIMEOUT", record)
            self._auditor.record("LEDGER_APPEND", entry.entry_id, cycle_id)
            escalation = self._escalation.raise_escalation(record)
            self._auditor.record("ESCALATE", escalation.escalation_id, cycle_id)
            result["escalation_id"] = escalation.escalation_id
        return result

    def resolve_escalation(self, escalation_id: str, resolved_by: str, note: str = "") -> Escalation:
        """CACG-HUMAN0-0: HUMAN-0 resolution of an open escalation."""
        escalation = self._escalation.resolve(escalation_id, resolved_by, note)
        self._auditor.record("RESOLVE", escalation_id, f"by={resolved_by}")
        return escalation

    def verify_chain(self) -> bool:
        """CACG-CHAIN-0: verify cycle ledger chain integrity."""
        result = self._ledger.verify_chain()
        self._auditor.record("VERIFY_CHAIN", "ledger", f"entries={len(self._ledger)}")
        return result

    def get_cycle(self, cycle_id: str) -> Optional[CycleRecord]:
        return self._orchestrator.get(cycle_id)

    def all_cycles(self) -> List[CycleRecord]:
        return self._orchestrator.all_cycles()

    def open_cycles(self) -> List[CycleRecord]:
        return self._orchestrator.open_cycles()

    def get_escalation(self, escalation_id: str) -> Optional[Escalation]:
        return self._escalation.get(escalation_id)

    def all_escalations(self) -> List[Escalation]:
        return self._escalation.all_escalations()

    def open_escalations(self) -> List[Escalation]:
        return self._escalation.open_escalations()

    def audit_log(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._auditor.all_entries()]

    def status(self) -> Dict[str, Any]:
        return {
            "module": "CACG",
            "innov": "INNOV-137",
            "phase": 232,
            "version": "10.43.0",
            "arc": "III — Autonomous Constitutional Intelligence (capstone)",
            "stages": list(_CYCLE_STAGES),
            "stage_timeout_seconds": self._timeout._timeout_seconds,
            "total_cycles": len(self._orchestrator.all_cycles()),
            "open_cycles": len(self._orchestrator.open_cycles()),
            "total_escalations": len(self._escalation.all_escalations()),
            "open_escalations": len(self._escalation.open_escalations()),
            "ledger_entries": len(self._ledger),
            "audit_entries": len(self._auditor.all_entries()),
        }
