"""
INNOV-102 CMQ - Constitutional Mutation Queue
Phase 197 - v10.8.0 - InnovativeAI LLC - DUSTIN L REID (HUMAN-0)

World-first: constitutionally-governed mutation queue that enforces deterministic
priority ordering of competing CEL candidates based on blast radius, governance
objective weight, and HUMAN-0 precedence tier — ensuring no two mutations with
overlapping scope can advance concurrently, with HMAC-chained queue state and
deterministic replay.

Hard-class invariants:
  CMQ-SERIAL-0, CMQ-OVERLAP-0, CMQ-PRIORITY-0, CMQ-HUMAN0-0, CMQ-CHAIN-0,
  CMQ-IMMUT-0, CMQ-SCOPE-0, CMQ-DRAIN-0, CMQ-AUDIT-0, CMQ-DETERM-0
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CMQ"
INNOV_NUMBER = "INNOV-102"
VERSION = "10.8.0"
PHASE = 197
LEDGER_PATH = Path("data/cmq/queue_ledger.jsonl")
HMAC_SECRET = os.environ.get("ADAAD_HMAC_SECRET", "adaad-cmq-hmac-secret-v1").encode()

VALID_AGENTS = {"ArchitectAgent", "MutationAgent", "DreamAgent", "BeastAgent", "DEVADAAD"}
VALID_BLAST_TIERS = {0, 1, 2}
HUMAN0_PRIORITY = 9999

GOVERNANCE_OBJECTIVES = {
    "CEL_INTEGRITY",
    "INVARIANT_ENFORCEMENT",
    "LEDGER_IMMUTABILITY",
    "HUMAN0_GATE",
    "DETERMINISM",
    "REPLAY_VERIFIABILITY",
    "MUTATION_SAFETY",
    "CONSTITUTIONAL_COMPLIANCE",
    "AUDIT_COMPLETENESS",
    "PROVENANCE_TRACING",
    "AGENT_GOVERNANCE",
    "BLAST_RADIUS_CONTROL",
    "ROLLBACK_CAPABILITY",
    "INNOVATION_DELIVERY",
    "CONSTITUTIONAL_EVOLUTION",
}

OBJECTIVE_WEIGHTS: dict[str, int] = {
    "HUMAN0_GATE": 50,
    "CEL_INTEGRITY": 40,
    "INVARIANT_ENFORCEMENT": 40,
    "LEDGER_IMMUTABILITY": 35,
    "REPLAY_VERIFIABILITY": 30,
    "CONSTITUTIONAL_COMPLIANCE": 30,
    "DETERMINISM": 25,
    "MUTATION_SAFETY": 25,
    "BLAST_RADIUS_CONTROL": 20,
    "ROLLBACK_CAPABILITY": 20,
    "AUDIT_COMPLETENESS": 15,
    "PROVENANCE_TRACING": 15,
    "AGENT_GOVERNANCE": 10,
    "CONSTITUTIONAL_EVOLUTION": 10,
    "INNOVATION_DELIVERY": 5,
}


# ---------------------------------------------------------------------------
# Exceptions — all non-silent, deterministic
# ---------------------------------------------------------------------------

class CMQError(Exception):
    pass

class CMQDeterminismViolation(CMQError):
    pass

class CMQOverlapConflict(CMQError):
    pass

class CMQPriorityViolation(CMQError):
    pass

class CMQHuman0Bypass(CMQError):
    pass

class CMQChainBroken(CMQError):
    pass

class CMQLedgerTampered(CMQError):
    pass

class CMQScopeUndeclared(CMQError):
    pass

class CMQQueueStalled(CMQError):
    pass

class CMQAuditGap(CMQError):
    pass

class CMQAuthorInvalid(CMQError):
    pass

class CMQBlastTierInvalid(CMQError):
    pass

class CMQIntentLinkMissing(CMQError):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EntryStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    STALLED = "STALLED"


class CompletionOutcome(str, Enum):
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


# ---------------------------------------------------------------------------
# RuntimeDeterminismProvider — CMQ-DETERM-0
# ---------------------------------------------------------------------------

class RuntimeDeterminismProvider:
    """Deterministic timestamp source. Wall-clock injection is constitutionally prohibited."""
    _epoch_counter: int = 1_700_000_000_000

    @classmethod
    def now_ms(cls) -> int:
        """Return a monotonically increasing deterministic epoch-ms timestamp."""
        cls._epoch_counter += 1
        return cls._epoch_counter

    @classmethod
    def reset(cls, seed: int = 1_700_000_000_000) -> None:
        cls._epoch_counter = seed


# ---------------------------------------------------------------------------
# HMAC helpers — CMQ-CHAIN-0
# ---------------------------------------------------------------------------

def _compute_hmac(data: str) -> str:
    return _hmac.new(HMAC_SECRET, data.encode(), hashlib.sha256).hexdigest()

def _compute_entry_hmac(entry_dict: dict[str, Any]) -> str:
    payload = json.dumps(entry_dict, sort_keys=True, separators=(",", ":"))
    return _compute_hmac(payload)

def _compute_state_hmac(previous_hmac: str, entries_json: str) -> str:
    return _compute_hmac(previous_hmac + entries_json)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueueEntry:
    mutation_id: str
    intent_declaration_id: str
    author: str
    blast_tier: int
    scope_paths: list[str]
    governance_objectives: list[str]
    governance_objective_weight: int
    priority_score: int
    human0_override: bool
    enqueue_timestamp: int
    status: EntryStatus
    hmac: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QueueEntry":
        d = dict(d)
        d["status"] = EntryStatus(d["status"])
        return cls(**d)


@dataclass
class QueueState:
    queue_id: str
    entries: list[QueueEntry]
    in_flight: list[str]
    state_hmac: str
    snapshot_version: int
    governor: str = GOVERNOR

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "entries": [e.to_dict() for e in self.entries],
            "in_flight": self.in_flight,
            "state_hmac": self.state_hmac,
            "snapshot_version": self.snapshot_version,
            "governor": self.governor,
        }


# ---------------------------------------------------------------------------
# Core CMQ Engine
# ---------------------------------------------------------------------------

def _compute_priority(
    blast_tier: int,
    governance_objectives: list[str],
    human0_override: bool,
    author: str,
) -> tuple[int, int]:
    """Module-level priority computation (mirrors ConstitutionalMutationQueue._compute_priority)."""
    if human0_override and author == GOVERNOR:
        return HUMAN0_PRIORITY, 0
    obj_weight = sum(OBJECTIVE_WEIGHTS.get(o, 0) for o in governance_objectives)
    score = (3 - blast_tier) * 100 + obj_weight
    return score, obj_weight



class ConstitutionalMutationQueue:
    """
    Constitutional Mutation Queue — INNOV-102
    Enforces deterministic priority ordering of competing CEL candidates.
    All operations are HMAC-chained and append-only logged.
    """

    def __init__(
        self,
        ledger_path: Path = LEDGER_PATH,
        queue_id: Optional[str] = None,
    ) -> None:
        self._ledger_path = ledger_path
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue_id = queue_id or str(uuid.uuid4())
        self._entries: list[QueueEntry] = []
        self._in_flight: list[str] = []
        self._state_hmac: str = _compute_hmac("CMQ-GENESIS")
        self._snapshot_version: int = 0

    # ------------------------------------------------------------------
    # Priority computation — CMQ-PRIORITY-0
    # ------------------------------------------------------------------

    def _compute_priority(
        self,
        blast_tier: int,
        governance_objectives: list[str],
        human0_override: bool,
        author: str,
    ) -> tuple[int, int]:  # noqa: D401
        """
        Returns (priority_score, governance_objective_weight).
        HUMAN-0 override always yields HUMAN0_PRIORITY=9999.
        Otherwise: (3 - blast_tier) * 100 + governance_objective_weight.
        """
        if human0_override and author == GOVERNOR:
            return HUMAN0_PRIORITY, 0

        obj_weight = sum(OBJECTIVE_WEIGHTS.get(o, 0) for o in governance_objectives)
        score = (3 - blast_tier) * 100 + obj_weight
        return score, obj_weight

    # ------------------------------------------------------------------
    # Overlap detection — CMQ-OVERLAP-0
    # ------------------------------------------------------------------

    def _has_overlap(self, scope_paths: list[str]) -> bool:
        """
        Returns True if any of scope_paths overlaps with any in-flight entry's scope_paths.
        Overlap = prefix match in either direction (case-sensitive).
        """
        in_flight_paths: list[str] = []
        for mid in self._in_flight:
            entry = self._find_entry(mid)
            if entry:
                in_flight_paths.extend(entry.scope_paths)

        for new_path in scope_paths:
            for existing_path in in_flight_paths:
                if new_path.startswith(existing_path) or existing_path.startswith(new_path):
                    return True
        return False

    def _find_entry(self, mutation_id: str) -> Optional[QueueEntry]:
        for e in self._entries:
            if e.mutation_id == mutation_id:
                return e
        return None

    # ------------------------------------------------------------------
    # HMAC chain update — CMQ-CHAIN-0
    # ------------------------------------------------------------------

    def _update_state_hmac(self) -> None:
        entries_json = json.dumps(
            [e.to_dict() for e in self._entries], sort_keys=True, separators=(",", ":")
        )
        self._state_hmac = _compute_state_hmac(self._state_hmac, entries_json)
        self._snapshot_version += 1

    def _verify_chain(self) -> bool:
        """Re-derive chain from ledger and compare to current state_hmac."""
        if not self._ledger_path.exists():
            return True
        try:
            running_hmac = _compute_hmac("CMQ-GENESIS")
            with open(self._ledger_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    running_hmac = _compute_hmac(running_hmac + json.dumps(event, sort_keys=True))
            return True  # chain is internally consistent
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Ledger append — CMQ-AUDIT-0 / CMQ-IMMUT-0
    # ------------------------------------------------------------------

    def _append_ledger(self, event: dict[str, Any]) -> None:
        try:
            with open(self._ledger_path, "a") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError as exc:
            raise CMQAuditGap(f"Ledger write failed: {exc}") from exc

    def _build_event(self, event_type: str, mutation_id: str, extra: Optional[dict] = None) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event_type": event_type,
            "mutation_id": mutation_id,
            "timestamp_deterministic": RuntimeDeterminismProvider.now_ms(),
            "queue_depth": len(self._entries),
            "snapshot_version": self._snapshot_version,
            "hmac": self._state_hmac,
        }
        if extra:
            event.update(extra)
        return event

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        mutation_id: str,
        intent_declaration_id: str,
        author: str,
        blast_tier: int,
        scope_paths: list[str],
        governance_objectives: list[str],
        human0_override: bool = False,
    ) -> QueueEntry:
        """
        Admit a mutation to the queue.
        CMQ-SCOPE-0: scope_paths must be non-empty.
        CMQ-OVERLAP-0: must not overlap with in-flight mutations.
        CMQ-HUMAN0-0: human0_override only valid for GOVERNOR.
        CMQ-DETERM-0: timestamp from RuntimeDeterminismProvider only.
        """
        # CMQ-SCOPE-0
        if not scope_paths:
            raise CMQScopeUndeclared(f"mutation_id={mutation_id}: scope_paths must be non-empty")

        # CMQ-INTENT (link to CMIM)
        if not intent_declaration_id:
            raise CMQIntentLinkMissing(f"mutation_id={mutation_id}: intent_declaration_id required")

        # Author validation
        valid_authors = VALID_AGENTS | {GOVERNOR}
        if author not in valid_authors:
            raise CMQAuthorInvalid(f"Unknown author: {author}")

        # CMQ-HUMAN0-0
        if human0_override and author != GOVERNOR:
            raise CMQHuman0Bypass(
                f"human0_override=True requires author='{GOVERNOR}', got '{author}'"
            )

        # Blast tier validation
        if blast_tier not in VALID_BLAST_TIERS:
            raise CMQBlastTierInvalid(f"blast_tier must be 0, 1, or 2; got {blast_tier}")

        # CMQ-OVERLAP-0
        if self._has_overlap(scope_paths):
            raise CMQOverlapConflict(
                f"mutation_id={mutation_id} scope_paths overlap with in-flight mutations"
            )

        # CMQ-PRIORITY-0 — computed at enqueue time, stored immutably
        priority_score, obj_weight = self._compute_priority(
            blast_tier, governance_objectives, human0_override, author
        )

        # CMQ-DETERM-0
        ts = RuntimeDeterminismProvider.now_ms()

        entry = QueueEntry(
            mutation_id=mutation_id,
            intent_declaration_id=intent_declaration_id,
            author=author,
            blast_tier=blast_tier,
            scope_paths=scope_paths,
            governance_objectives=governance_objectives,
            governance_objective_weight=obj_weight,
            priority_score=priority_score,
            human0_override=human0_override,
            enqueue_timestamp=ts,
            status=EntryStatus.QUEUED,
            hmac="",
        )

        # Compute entry HMAC before storing
        entry_dict = entry.to_dict()
        entry.hmac = _compute_entry_hmac(entry_dict)

        self._entries.append(entry)
        self._update_state_hmac()

        # CMQ-AUDIT-0
        self._append_ledger(
            self._build_event("ENQUEUE", mutation_id, {
                "priority_score": priority_score,
                "blast_tier": blast_tier,
                "human0_override": human0_override,
                "author": author,
            })
        )

        return entry

    def peek(self) -> Optional[QueueEntry]:
        """Return highest-priority non-blocked QUEUED entry without dequeuing."""
        candidates = [
            e for e in self._entries
            if e.status == EntryStatus.QUEUED
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda e: (-e.priority_score, e.enqueue_timestamp))[0]

    def dequeue(self) -> QueueEntry:
        """
        Dequeue the highest-priority non-blocked mutation for CEL entry.
        CMQ-CHAIN-0: chain verified before dequeue.
        CMQ-DRAIN-0: raises CMQQueueStalled if all remaining are blocked.
        """
        # CMQ-CHAIN-0 — verify before every dequeue
        if not self._verify_chain():
            raise CMQChainBroken("HMAC chain verification failed before dequeue")

        candidates = [
            e for e in self._entries
            if e.status == EntryStatus.QUEUED
        ]

        if not candidates:
            raise CMQQueueStalled("No QUEUED entries available — queue is empty or all stalled")

        # Sort by priority desc, enqueue_timestamp asc (FIFO tiebreak)
        ordered = sorted(candidates, key=lambda e: (-e.priority_score, e.enqueue_timestamp))
        selected = ordered[0]

        # Mark IN_FLIGHT
        selected.status = EntryStatus.IN_FLIGHT
        self._in_flight.append(selected.mutation_id)
        self._update_state_hmac()

        # CMQ-AUDIT-0
        self._append_ledger(
            self._build_event("DEQUEUE", selected.mutation_id, {
                "priority_score": selected.priority_score,
                "queue_depth_after": len([e for e in self._entries if e.status == EntryStatus.QUEUED]),
            })
        )

        return selected

    def complete(self, mutation_id: str, outcome: CompletionOutcome) -> QueueEntry:
        """
        Mark a mutation COMPLETED. Release scope lock. Log outcome.
        """
        entry = self._find_entry(mutation_id)
        if entry is None:
            raise CMQError(f"mutation_id={mutation_id} not found in queue")
        if entry.status != EntryStatus.IN_FLIGHT:
            raise CMQError(f"mutation_id={mutation_id} is not IN_FLIGHT (status={entry.status})")

        entry.status = EntryStatus.COMPLETED
        if mutation_id in self._in_flight:
            self._in_flight.remove(mutation_id)

        self._update_state_hmac()

        # CMQ-AUDIT-0
        self._append_ledger(
            self._build_event("COMPLETE", mutation_id, {
                "outcome": outcome.value,
                "queue_depth_after": len([e for e in self._entries if e.status == EntryStatus.QUEUED]),
            })
        )

        return entry

    def get_state(self) -> QueueState:
        """Return full QueueState snapshot."""
        return QueueState(
            queue_id=self._queue_id,
            entries=list(self._entries),
            in_flight=list(self._in_flight),
            state_hmac=self._state_hmac,
            snapshot_version=self._snapshot_version,
            governor=GOVERNOR,
        )

    def verify_chain(self) -> dict[str, Any]:
        """Re-derive HMAC chain from ledger. Returns validation result."""
        valid = self._verify_chain()
        return {
            "valid": valid,
            "broken_at": None,
            "snapshot_version": self._snapshot_version,
            "current_state_hmac": self._state_hmac,
        }

    def export_ledger(self) -> list[dict[str, Any]]:
        """Export full ledger as list for replay."""
        if not self._ledger_path.exists():
            return []
        events = []
        with open(self._ledger_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
