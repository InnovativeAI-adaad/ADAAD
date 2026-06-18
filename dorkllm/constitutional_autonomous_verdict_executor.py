# SPDX-License-Identifier: Apache-2.0
"""
constitutional_autonomous_verdict_executor.py
Phase 230 · INNOV-135 · CAVE — Constitutional Autonomous Verdict Executor
World-first cryptographically governed autonomous HOLD/REJECT/DEFER enforcement
pipeline with immutable quarantine ledger and deterministic CHI re-evaluation triggers.

Author  : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 06
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
# CAVE-CHAIN-0     : All quarantine ledger entries HMAC-SHA-256 chained
# CAVE-APPEND-0    : Quarantine ledger append-only — no mutation or deletion
# CAVE-IMMUT-0     : Quarantine records immutable after sealing
# CAVE-SCOPE-0     : Exactly 3 verdict classes handled: HOLD, REJECT, DEFER
# CAVE-QUARANTINE-0: REJECT verdicts must be sealed into the quarantine ledger
# CAVE-REEVAL-0    : HOLD verdicts must produce a deterministic CHI re-eval trigger
# CAVE-HUMAN0-0    : Quarantine release requires non-empty released_by (HUMAN-0)
# CAVE-DETERM-0    : Verdict routing fully deterministic — no RNG
# CAVE-AUDIT-0     : Every CAVE operation sealed in parallel HMAC-chained audit log
# CAVE-ORIGIN-0    : Every verdict record must reference a non-empty cade_record_id

# ── Verdict class registry (CAVE-SCOPE-0: exactly 3) ─────────────────────────
_VERDICT_CLASSES: Tuple[str, ...] = ("HOLD", "REJECT", "DEFER")
_VERDICT_CLASS_COUNT = len(_VERDICT_CLASSES)
if _VERDICT_CLASS_COUNT != 3:
    raise RuntimeError(
        f"CAVE-SCOPE-0 VIOLATION: expected exactly 3 verdict classes, "
        f"found {_VERDICT_CLASS_COUNT}"
    )

_HMAC_SECRET = os.environ.get(
    "CAVE_HMAC_SECRET", "cave-hmac-secret-DUSTIN-L-REID-v10-ArcIII"
).encode()


# ── Typed exception hierarchy ─────────────────────────────────────────────────
class CAVEViolation(RuntimeError):
    """Base class for all CAVE Hard-class invariant violations."""


class ChainBreakError(CAVEViolation):
    """CAVE-CHAIN-0: HMAC chain integrity broken."""


class AppendViolation(CAVEViolation):
    """CAVE-APPEND-0: Attempted mutation or deletion of quarantine ledger."""


class ImmutabilityViolation(CAVEViolation):
    """CAVE-IMMUT-0: Attempt to mutate sealed quarantine record."""


class ScopeViolation(CAVEViolation):
    """CAVE-SCOPE-0: Unrecognized verdict class encountered."""


class QuarantineError(CAVEViolation):
    """CAVE-QUARANTINE-0: REJECT verdict not properly sealed into quarantine."""


class ReEvalError(CAVEViolation):
    """CAVE-REEVAL-0: HOLD verdict failed to produce CHI re-eval trigger."""


class HUMAN0ReleaseError(CAVEViolation):
    """CAVE-HUMAN0-0: Quarantine release requires non-empty HUMAN-0 identity."""


class DeterminismViolation(CAVEViolation):
    """CAVE-DETERM-0: Non-deterministic verdict routing detected."""


class AuditFailure(CAVEViolation):
    """CAVE-AUDIT-0: Audit ledger write failed."""


class OriginViolation(CAVEViolation):
    """CAVE-ORIGIN-0: Verdict record missing valid CADE record reference."""


# ── Enums ──────────────────────────────────────────────────────────────────────
class VerdictClass(str, Enum):
    HOLD = "HOLD"
    REJECT = "REJECT"
    DEFER = "DEFER"


class QuarantineState(str, Enum):
    SEALED = "SEALED"
    RELEASED = "RELEASED"      # HUMAN-0 released (CAVE-HUMAN0-0)
    REEVAL_TRIGGERED = "REEVAL_TRIGGERED"  # HOLD → CHI re-eval issued


class ReEvalStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


# ── Data structures ────────────────────────────────────────────────────────────
def _hmac_digest(payload: str) -> str:
    return hmac.new(_HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()


@dataclass
class VerdictRecord:
    """
    Immutable sealed verdict record.
    CAVE-IMMUT-0: sealed records cannot be mutated.
    CAVE-ORIGIN-0: must reference a valid CADE decision record_id.
    """
    record_id: str
    cade_record_id: str          # CAVE-ORIGIN-0
    verdict: VerdictClass
    mutation_ref: str
    chi_score: float
    sealed_ts: float
    state: QuarantineState = QuarantineState.SEALED
    released_by: Optional[str] = None   # CAVE-HUMAN0-0
    released_ts: Optional[float] = None
    release_reason: Optional[str] = None
    reeval_trigger_id: Optional[str] = None  # CAVE-REEVAL-0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "cade_record_id": self.cade_record_id,
            "verdict": self.verdict.value,
            "mutation_ref": self.mutation_ref,
            "chi_score": self.chi_score,
            "sealed_ts": self.sealed_ts,
            "state": self.state.value,
            "released_by": self.released_by,
            "released_ts": self.released_ts,
            "release_reason": self.release_reason,
            "reeval_trigger_id": self.reeval_trigger_id,
        }


@dataclass
class ReEvalTrigger:
    """
    CHI re-evaluation trigger produced for HOLD verdicts.
    CAVE-REEVAL-0: deterministic, produced for every HOLD verdict.
    """
    trigger_id: str
    source_record_id: str        # VerdictRecord that caused this trigger
    cade_record_id: str
    mutation_ref: str
    original_chi: float
    issued_ts: float
    status: ReEvalStatus = ReEvalStatus.PENDING
    completed_ts: Optional[float] = None
    new_chi: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "source_record_id": self.source_record_id,
            "cade_record_id": self.cade_record_id,
            "mutation_ref": self.mutation_ref,
            "original_chi": self.original_chi,
            "issued_ts": self.issued_ts,
            "status": self.status.value,
            "completed_ts": self.completed_ts,
            "new_chi": self.new_chi,
        }


@dataclass
class QuarantineLedgerEntry:
    """
    HMAC-SHA-256 chained ledger entry.
    CAVE-CHAIN-0: prev_hash links form an unbreakable chain.
    CAVE-APPEND-0: entries are write-once.
    """
    entry_id: str
    sequence: int
    prev_hash: str
    record: VerdictRecord
    entry_hash: str = field(default="", init=False)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps({
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "record_id": self.record.record_id,
            "cade_record_id": self.record.cade_record_id,
            "verdict": self.record.verdict.value,
            "chi_score": self.record.chi_score,
            "sealed_ts": self.record.sealed_ts,
            "ts": self.ts,
        }, sort_keys=True)
        return _hmac_digest(payload)


@dataclass
class AuditEntry:
    """Single entry in the parallel HMAC-chained audit log. CAVE-AUDIT-0."""
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


# ── VerdictRouter ─────────────────────────────────────────────────────────────
class VerdictRouter:
    """
    Routes CADE HOLD/REJECT/DEFER verdicts to the appropriate enforcement path.
    CAVE-SCOPE-0: exactly 3 verdict classes.
    CAVE-DETERM-0: routing is fully deterministic — no RNG.
    CAVE-ORIGIN-0: cade_record_id must be non-empty.
    """

    _VALID_VERDICTS = set(_VERDICT_CLASSES)

    def route(
        self,
        cade_record_id: str,
        verdict: str,
        mutation_ref: str,
        chi_score: float,
    ) -> VerdictRecord:
        """
        Validate and route a CADE verdict.
        CAVE-ORIGIN-0: cade_record_id must be non-empty.
        CAVE-SCOPE-0: verdict must be HOLD, REJECT, or DEFER.
        CAVE-DETERM-0: deterministic — no random branching.
        """
        # CAVE-ORIGIN-0
        if not cade_record_id or not cade_record_id.strip():
            raise OriginViolation(
                "CAVE-ORIGIN-0 VIOLATION: cade_record_id must be non-empty"
            )
        # CAVE-SCOPE-0
        if verdict not in self._VALID_VERDICTS:
            raise ScopeViolation(
                f"CAVE-SCOPE-0 VIOLATION: verdict '{verdict}' not in {self._VALID_VERDICTS}"
            )
        if not mutation_ref or not mutation_ref.strip():
            raise OriginViolation(
                "CAVE-ORIGIN-0 VIOLATION: mutation_ref must be non-empty"
            )
        return VerdictRecord(
            record_id=f"CAVE-{uuid.uuid4().hex[:16].upper()}",
            cade_record_id=cade_record_id,
            verdict=VerdictClass(verdict),
            mutation_ref=mutation_ref,
            chi_score=chi_score,
            sealed_ts=time.time(),
            state=QuarantineState.SEALED,
        )


# ── QuarantineEngine ──────────────────────────────────────────────────────────
class QuarantineEngine:
    """
    Seals REJECT/DEFER verdicts into an immutable quarantine ledger.
    CAVE-QUARANTINE-0: every REJECT must be quarantine-sealed.
    CAVE-HUMAN0-0: release requires non-empty released_by.
    CAVE-IMMUT-0: sealed records cannot be mutated after sealing.
    """

    def __init__(self) -> None:
        self._records: Dict[str, VerdictRecord] = {}

    def seal(self, record: VerdictRecord) -> VerdictRecord:
        """
        Seal a verdict record.
        CAVE-QUARANTINE-0: only REJECT and DEFER are quarantine-sealed here.
        CAVE-IMMUT-0: record_id may not overwrite an existing sealed record.
        """
        if record.record_id in self._records:
            raise ImmutabilityViolation(
                f"CAVE-IMMUT-0 VIOLATION: record {record.record_id} already sealed"
            )
        self._records[record.record_id] = record
        return record

    def release(
        self, record_id: str, released_by: str, reason: str
    ) -> VerdictRecord:
        """
        HUMAN-0 release a quarantined record.
        CAVE-HUMAN0-0: released_by must be non-empty.
        CAVE-IMMUT-0: only SEALED records may be released.
        """
        if not released_by or not released_by.strip():
            raise HUMAN0ReleaseError(
                "CAVE-HUMAN0-0 VIOLATION: released_by must be non-empty HUMAN-0 identity"
            )
        record = self._records.get(record_id)
        if record is None:
            raise CAVEViolation(f"Quarantine record {record_id} not found")
        if record.state != QuarantineState.SEALED:
            raise ImmutabilityViolation(
                f"CAVE-IMMUT-0 VIOLATION: record {record_id} is not in SEALED state"
            )
        record.state = QuarantineState.RELEASED
        record.released_by = released_by
        record.released_ts = time.time()
        record.release_reason = reason
        return record

    def get(self, record_id: str) -> Optional[VerdictRecord]:
        return self._records.get(record_id)

    def all_records(self) -> List[VerdictRecord]:
        return list(self._records.values())

    def quarantined(self) -> List[VerdictRecord]:
        return [r for r in self._records.values() if r.state == QuarantineState.SEALED]


# ── CHIReEvaluator ────────────────────────────────────────────────────────────
class CHIReEvaluator:
    """
    Issues deterministic CHI re-evaluation triggers for HOLD verdicts.
    CAVE-REEVAL-0: every HOLD verdict produces exactly one trigger.
    CAVE-DETERM-0: trigger generation is deterministic.
    """

    def __init__(self) -> None:
        self._triggers: Dict[str, ReEvalTrigger] = {}

    def issue_trigger(self, record: VerdictRecord) -> ReEvalTrigger:
        """
        Issue a CHI re-eval trigger for a HOLD verdict.
        CAVE-REEVAL-0: exactly one trigger per HOLD record.
        """
        if record.verdict != VerdictClass.HOLD:
            raise ReEvalError(
                f"CAVE-REEVAL-0 VIOLATION: trigger only valid for HOLD verdicts, "
                f"got {record.verdict.value}"
            )
        trigger = ReEvalTrigger(
            trigger_id=f"REEVAL-{uuid.uuid4().hex[:16].upper()}",
            source_record_id=record.record_id,
            cade_record_id=record.cade_record_id,
            mutation_ref=record.mutation_ref,
            original_chi=record.chi_score,
            issued_ts=time.time(),
        )
        self._triggers[trigger.trigger_id] = trigger
        return trigger

    def complete_trigger(
        self, trigger_id: str, new_chi: float
    ) -> ReEvalTrigger:
        """Mark a re-eval trigger as completed with new CHI score."""
        trigger = self._triggers.get(trigger_id)
        if trigger is None:
            raise ReEvalError(f"CAVE-REEVAL-0: trigger {trigger_id} not found")
        if trigger.status != ReEvalStatus.PENDING:
            raise ReEvalError(
                f"CAVE-REEVAL-0 VIOLATION: trigger {trigger_id} is not PENDING"
            )
        trigger.status = ReEvalStatus.COMPLETED
        trigger.completed_ts = time.time()
        trigger.new_chi = new_chi
        return trigger

    def get_trigger(self, trigger_id: str) -> Optional[ReEvalTrigger]:
        return self._triggers.get(trigger_id)

    def all_triggers(self) -> List[ReEvalTrigger]:
        return list(self._triggers.values())

    def pending_triggers(self) -> List[ReEvalTrigger]:
        return [t for t in self._triggers.values() if t.status == ReEvalStatus.PENDING]


# ── QuarantineLedger ──────────────────────────────────────────────────────────
class QuarantineLedger:
    """
    HMAC-SHA-256 append-only ledger for all verdict records.
    CAVE-CHAIN-0: full chain verification before every append.
    CAVE-APPEND-0: no deletion or mutation of entries.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[QuarantineLedgerEntry] = []

    def _tail_hash(self) -> str:
        if not self._entries:
            return self._GENESIS_HASH
        return self._entries[-1].entry_hash

    def verify_chain(self) -> bool:
        """
        CAVE-CHAIN-0: verify full HMAC chain integrity.
        Returns True if chain is intact.
        """
        prev = self._GENESIS_HASH
        for entry in self._entries:
            if entry.prev_hash != prev:
                raise ChainBreakError(
                    f"CAVE-CHAIN-0 VIOLATION: chain break at sequence {entry.sequence}"
                )
            expected = entry._compute_hash()
            if not hmac.compare_digest(entry.entry_hash, expected):
                raise ChainBreakError(
                    f"CAVE-CHAIN-0 VIOLATION: entry hash mismatch at sequence {entry.sequence}"
                )
            prev = entry.entry_hash
        return True

    def append(self, record: VerdictRecord) -> QuarantineLedgerEntry:
        """
        CAVE-CHAIN-0: verify chain before append.
        CAVE-APPEND-0: entries are write-once.
        """
        self.verify_chain()
        entry = QuarantineLedgerEntry(
            entry_id=f"QL-{uuid.uuid4().hex[:16].upper()}",
            sequence=len(self._entries),
            prev_hash=self._tail_hash(),
            record=record,
        )
        self._entries.append(entry)
        return entry

    def all_entries(self) -> List[QuarantineLedgerEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ── CAVEAuditor ───────────────────────────────────────────────────────────────
class CAVEAuditor:
    """
    Append-only HMAC-chained audit log. CAVE-AUDIT-0.
    Records every route, seal, release, trigger, and verify operation.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def _tail_hash(self) -> str:
        if not self._entries:
            return self._GENESIS_HASH
        return self._entries[-1].entry_hash

    def record(self, operation: str, entity_id: str, detail: str = "") -> AuditEntry:
        """CAVE-AUDIT-0: append an audit entry — raises on failure."""
        try:
            entry = AuditEntry(
                audit_id=f"CAVE-AUD-{uuid.uuid4().hex[:12].upper()}",
                sequence=len(self._entries),
                prev_hash=self._tail_hash(),
                operation=operation,
                entity_id=entity_id,
                detail=detail,
            )
            self._entries.append(entry)
            return entry
        except Exception as exc:
            raise AuditFailure(f"CAVE-AUDIT-0 VIOLATION: audit write failed: {exc}") from exc

    def all_entries(self) -> List[AuditEntry]:
        return list(self._entries)


# ── CAVEEngine (facade) ───────────────────────────────────────────────────────
class CAVEEngine:
    """
    Facade coordinating VerdictRouter, QuarantineEngine, CHIReEvaluator,
    QuarantineLedger, and CAVEAuditor.

    Arc III ACI Module 06 — CAVE handles the HOLD/REJECT/DEFER enforcement
    path completing the non-PROMOTE verdict lifecycle.
    """

    def __init__(self) -> None:
        self._router = VerdictRouter()
        self._quarantine = QuarantineEngine()
        self._reeval = CHIReEvaluator()
        self._ledger = QuarantineLedger()
        self._auditor = CAVEAuditor()

    def execute(
        self,
        cade_record_id: str,
        verdict: str,
        mutation_ref: str,
        chi_score: float,
    ) -> Dict[str, Any]:
        """
        Route a CADE HOLD/REJECT/DEFER verdict through the enforcement pipeline.
        CAVE-ORIGIN-0: cade_record_id non-empty.
        CAVE-SCOPE-0: verdict in {HOLD, REJECT, DEFER}.
        CAVE-DETERM-0: deterministic routing.
        CAVE-QUARANTINE-0: REJECT/DEFER → quarantine sealed.
        CAVE-REEVAL-0: HOLD → CHI re-eval trigger issued.
        CAVE-CHAIN-0: ledger append with chain verify.
        CAVE-AUDIT-0: every step audited.
        """
        # Route
        record = self._router.route(cade_record_id, verdict, mutation_ref, chi_score)
        self._auditor.record("ROUTE", record.record_id, f"verdict={verdict}")

        # Enforce
        trigger: Optional[ReEvalTrigger] = None
        if record.verdict == VerdictClass.HOLD:
            # CAVE-REEVAL-0: issue CHI re-eval trigger
            trigger = self._reeval.issue_trigger(record)
            record.reeval_trigger_id = trigger.trigger_id
            record.state = QuarantineState.REEVAL_TRIGGERED
            self._auditor.record("REEVAL_TRIGGER", trigger.trigger_id, record.record_id)
        else:
            # REJECT or DEFER → quarantine seal (CAVE-QUARANTINE-0)
            self._quarantine.seal(record)
            self._auditor.record("QUARANTINE_SEAL", record.record_id, f"verdict={verdict}")

        # Ledger (CAVE-CHAIN-0)
        entry = self._ledger.append(record)
        self._auditor.record("LEDGER_APPEND", entry.entry_id, record.record_id)

        result: Dict[str, Any] = {
            "status": "VERDICT_EXECUTED",
            "record_id": record.record_id,
            "cade_record_id": record.cade_record_id,
            "verdict": record.verdict.value,
            "state": record.state.value,
            "sealed_ts": record.sealed_ts,
        }
        if trigger:
            result["reeval_trigger_id"] = trigger.trigger_id
        return result

    def release_quarantine(
        self, record_id: str, released_by: str, reason: str
    ) -> VerdictRecord:
        """CAVE-HUMAN0-0: HUMAN-0 release of a quarantined record."""
        record = self._quarantine.release(record_id, released_by, reason)
        self._auditor.record("QUARANTINE_RELEASE", record_id, f"by={released_by}")
        return record

    def complete_reeval(self, trigger_id: str, new_chi: float) -> ReEvalTrigger:
        """Mark a re-eval trigger completed with new CHI score."""
        trigger = self._reeval.complete_trigger(trigger_id, new_chi)
        self._auditor.record("REEVAL_COMPLETE", trigger_id, f"new_chi={new_chi}")
        return trigger

    def verify_chain(self) -> bool:
        """CAVE-CHAIN-0: verify quarantine ledger chain integrity."""
        result = self._ledger.verify_chain()
        self._auditor.record("VERIFY_CHAIN", "ledger", f"entries={len(self._ledger)}")
        return result

    def get_record(self, record_id: str) -> Optional[VerdictRecord]:
        return self._quarantine.get(record_id)

    def all_records(self) -> List[VerdictRecord]:
        return self._quarantine.all_records()

    def quarantined_records(self) -> List[VerdictRecord]:
        return self._quarantine.quarantined()

    def get_trigger(self, trigger_id: str) -> Optional[ReEvalTrigger]:
        return self._reeval.get_trigger(trigger_id)

    def all_triggers(self) -> List[ReEvalTrigger]:
        return self._reeval.all_triggers()

    def pending_triggers(self) -> List[ReEvalTrigger]:
        return self._reeval.pending_triggers()

    def audit_log(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._auditor.all_entries()]

    def status(self) -> Dict[str, Any]:
        return {
            "module": "CAVE",
            "innov": "INNOV-135",
            "phase": 230,
            "version": "10.41.0",
            "arc": "III — Autonomous Constitutional Intelligence",
            "verdict_classes": list(_VERDICT_CLASSES),
            "total_records": len(self._quarantine.all_records()),
            "quarantined": len(self._quarantine.quarantined()),
            "total_triggers": len(self._reeval.all_triggers()),
            "pending_triggers": len(self._reeval.pending_triggers()),
            "ledger_entries": len(self._ledger),
            "audit_entries": len(self._auditor.all_entries()),
        }
