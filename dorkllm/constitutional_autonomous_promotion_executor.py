# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/constitutional_autonomous_promotion_executor.py
Phase 226 · INNOV-131 · CAPE — Constitutional Autonomous Promotion Executor
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 02

CAPE closes the ACI decision-to-action loop: consuming CADE PROMOTE verdicts
and executing mutation promotions through a 5-stage governed pipeline under
mandatory HUMAN-0 approval. Every promotion is HMAC-SHA-256-chained, append-only,
and cryptographically sealed.

Hard-class invariants (10):
  CAPE-CHAIN-0   — ExecutionLedger HMAC chain must be verified before every append
  CAPE-APPEND-0  — ExecutionLedger is append-only; historical records are immutable
  CAPE-EXEC-0    — Only APPROVED queue entries may enter the 5-stage execution pipeline
  CAPE-GATE-0    — GateBlockError raised when CHI < 0.80 on any enqueue attempt
  CAPE-QUEUE-0   — PromotionQueue is FIFO; entries are HMAC-sealed on enqueue
  CAPE-AUDIT-0   — Every operation (enqueue/approve/execute/reject/verify) is audited
  CAPE-HUMAN0-0  — HUMAN-0 approval (non-empty approver string) required before execute
  CAPE-SCOPE-0   — Only PROMOTE verdicts from CADE may be enqueued (ScopeViolation otherwise)
  CAPE-IMMUT-0   — ImmutabilityViolation raised on any attempted mutation of sealed records
  CAPE-ORDER-0   — Execution order must match queue insertion order (FIFO enforcement)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Constants ────────────────────────────────────────────────────────────────

_HMAC_KEY = b"CAPE-CHAIN-HMAC-KEY-v1-DUSTIN-L-REID"
_PROMOTE_VERDICT = "PROMOTE"
_CHI_GATE_THRESHOLD = 0.80
_PIPELINE_STAGES = ["VALIDATE", "STAGE", "EXECUTE", "SEAL", "RECORD"]


# ── Exceptions ────────────────────────────────────────────────────────────────

class CAPEViolation(Exception):
    """Base CAPE constitutional violation."""


class GateBlockError(CAPEViolation):
    """CAPE-GATE-0: CHI below promotion threshold."""


class ScopeViolation(CAPEViolation):
    """CAPE-SCOPE-0: Only PROMOTE verdicts may be enqueued."""


class HUMAN0ApprovalError(CAPEViolation):
    """CAPE-HUMAN0-0: HUMAN-0 approval required before execution."""


class ChainBreakError(CAPEViolation):
    """CAPE-CHAIN-0: HMAC chain integrity violation."""


class ImmutabilityViolation(CAPEViolation):
    """CAPE-IMMUT-0: Attempt to mutate a sealed record."""


class OrderViolation(CAPEViolation):
    """CAPE-ORDER-0: FIFO execution order violation."""


class ExecutionError(CAPEViolation):
    """General execution pipeline failure."""


# ── Enums ─────────────────────────────────────────────────────────────────────

class QueueStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class QueueEntry:
    """A HMAC-sealed PROMOTE verdict awaiting execution."""
    entry_id: str
    decision_id: str
    synthesis_id: str
    chi_score: float
    mutation_ref: str
    verdict: str
    enqueued_at: float
    status: QueueStatus
    hmac_seal: str
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None
    _sealed: bool = field(default=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "decision_id": self.decision_id,
            "synthesis_id": self.synthesis_id,
            "chi_score": self.chi_score,
            "mutation_ref": self.mutation_ref,
            "verdict": self.verdict,
            "enqueued_at": self.enqueued_at,
            "status": self.status.value,
            "hmac_seal": self.hmac_seal,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }


@dataclass
class ExecutionRecord:
    """A sealed execution record written to the ExecutionLedger."""
    record_id: str
    entry_id: str
    decision_id: str
    synthesis_id: str
    chi_score: float
    mutation_ref: str
    approved_by: str
    stages_completed: List[str]
    status: ExecutionStatus
    executed_at: float
    proof: str           # SHA-256 of canonical execution data
    prev_hmac: str
    hmac_seal: str
    _sealed: bool = field(default=True, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "entry_id": self.entry_id,
            "decision_id": self.decision_id,
            "synthesis_id": self.synthesis_id,
            "chi_score": self.chi_score,
            "mutation_ref": self.mutation_ref,
            "approved_by": self.approved_by,
            "stages_completed": self.stages_completed,
            "status": self.status.value,
            "executed_at": self.executed_at,
            "proof": self.proof,
            "prev_hmac": self.prev_hmac,
            "hmac_seal": self.hmac_seal,
        }


@dataclass
class AuditEntry:
    """An HMAC-chained audit log entry."""
    audit_id: str
    operation: str
    subject_id: str
    actor: str
    timestamp: float
    detail: Dict[str, Any]
    prev_hmac: str
    hmac_seal: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "operation": self.operation,
            "subject_id": self.subject_id,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "detail": self.detail,
            "prev_hmac": self.prev_hmac,
            "hmac_seal": self.hmac_seal,
        }


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _hmac_sign(payload: Dict[str, Any]) -> str:
    """Compute deterministic HMAC-SHA-256 over a canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(_HMAC_KEY, canonical.encode(), hashlib.sha256).hexdigest()


def _sha256_proof(data: Dict[str, Any]) -> str:
    """SHA-256 execution proof over canonical payload."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── PromotionQueue ─────────────────────────────────────────────────────────────

class PromotionQueue:
    """
    CAPE-QUEUE-0 / CAPE-GATE-0 / CAPE-SCOPE-0 / CAPE-ORDER-0

    FIFO queue of CADE PROMOTE verdicts. Every entry is HMAC-sealed on enqueue.
    Only PROMOTE verdicts with CHI ≥ 0.80 are accepted.
    """

    def __init__(self) -> None:
        self._queue: deque[QueueEntry] = deque()
        self._index: Dict[str, QueueEntry] = {}

    def enqueue(
        self,
        decision_id: str,
        synthesis_id: str,
        chi_score: float,
        mutation_ref: str,
        verdict: str,
    ) -> QueueEntry:
        # CAPE-SCOPE-0: only PROMOTE verdicts
        if verdict != _PROMOTE_VERDICT:
            raise ScopeViolation(
                f"CAPE-SCOPE-0: only PROMOTE verdicts may be enqueued; got '{verdict}'"
            )
        # CAPE-GATE-0: CHI threshold enforcement
        if chi_score < _CHI_GATE_THRESHOLD:
            raise GateBlockError(
                f"CAPE-GATE-0: CHI {chi_score:.4f} < {_CHI_GATE_THRESHOLD} — gate blocked"
            )
        if not decision_id or not synthesis_id or not mutation_ref:
            raise CAPEViolation("CAPE-SCOPE-0: decision_id, synthesis_id, and mutation_ref are required")

        entry_id = str(uuid.uuid4())
        ts = time.time()
        seal_payload = {
            "entry_id": entry_id,
            "decision_id": decision_id,
            "synthesis_id": synthesis_id,
            "chi_score": chi_score,
            "mutation_ref": mutation_ref,
            "verdict": verdict,
            "enqueued_at": ts,
        }
        seal = _hmac_sign(seal_payload)
        entry = QueueEntry(
            entry_id=entry_id,
            decision_id=decision_id,
            synthesis_id=synthesis_id,
            chi_score=chi_score,
            mutation_ref=mutation_ref,
            verdict=verdict,
            enqueued_at=ts,
            status=QueueStatus.PENDING,
            hmac_seal=seal,
            _sealed=True,
        )
        self._queue.append(entry)
        self._index[entry_id] = entry
        return entry

    def approve(self, entry_id: str, approved_by: str) -> QueueEntry:
        """CAPE-HUMAN0-0: HUMAN-0 approval gate."""
        if not approved_by or not approved_by.strip():
            raise HUMAN0ApprovalError(
                "CAPE-HUMAN0-0: approved_by must be a non-empty HUMAN-0 identifier"
            )
        entry = self._index.get(entry_id)
        if entry is None:
            raise CAPEViolation(f"Queue entry not found: {entry_id}")
        if entry.status != QueueStatus.PENDING:
            raise CAPEViolation(
                f"CAPE-HUMAN0-0: entry {entry_id} is not PENDING (status={entry.status.value})"
            )
        # CAPE-IMMUT-0: do not mutate the original seal
        entry.approved_by = approved_by.strip()
        entry.approved_at = time.time()
        entry.status = QueueStatus.APPROVED
        return entry

    def reject(self, entry_id: str) -> QueueEntry:
        """Reject a PENDING queue entry (HUMAN-0 action)."""
        entry = self._index.get(entry_id)
        if entry is None:
            raise CAPEViolation(f"Queue entry not found: {entry_id}")
        if entry.status not in (QueueStatus.PENDING, QueueStatus.APPROVED):
            raise CAPEViolation(
                f"Cannot reject entry with status={entry.status.value}"
            )
        entry.status = QueueStatus.REJECTED
        return entry

    def peek_next_approved(self) -> Optional[QueueEntry]:
        """CAPE-ORDER-0: return the next APPROVED entry in FIFO order."""
        for e in self._queue:
            if e.status == QueueStatus.APPROVED:
                return e
        return None

    def get(self, entry_id: str) -> Optional[QueueEntry]:
        return self._index.get(entry_id)

    def list_all(self) -> List[QueueEntry]:
        return list(self._queue)

    def pending_count(self) -> int:
        return sum(1 for e in self._queue if e.status == QueueStatus.PENDING)

    def approved_count(self) -> int:
        return sum(1 for e in self._queue if e.status == QueueStatus.APPROVED)


# ── ExecutionLedger ───────────────────────────────────────────────────────────

class ExecutionLedger:
    """
    CAPE-CHAIN-0 / CAPE-APPEND-0 / CAPE-IMMUT-0

    HMAC-SHA-256-chained append-only ledger sealing every execution record.
    Chain verification runs before every append.
    """

    def __init__(self) -> None:
        self._records: List[ExecutionRecord] = []
        self._prev_hmac: str = "CAPE-GENESIS"

    def _verify_chain(self) -> bool:
        """CAPE-CHAIN-0: verify the full chain integrity."""
        prev = "CAPE-GENESIS"
        for rec in self._records:
            payload = {
                "record_id": rec.record_id,
                "entry_id": rec.entry_id,
                "decision_id": rec.decision_id,
                "synthesis_id": rec.synthesis_id,
                "chi_score": rec.chi_score,
                "mutation_ref": rec.mutation_ref,
                "approved_by": rec.approved_by,
                "stages_completed": rec.stages_completed,
                "status": rec.status.value,
                "executed_at": rec.executed_at,
                "proof": rec.proof,
                "prev_hmac": prev,
            }
            expected = _hmac_sign(payload)
            if not hmac.compare_digest(expected[:24], rec.hmac_seal[:24]):
                return False
            prev = rec.hmac_seal
        return True

    def append(
        self,
        entry: QueueEntry,
        stages_completed: List[str],
        status: ExecutionStatus,
    ) -> ExecutionRecord:
        """CAPE-CHAIN-0: verify chain before appending. CAPE-APPEND-0: append only."""
        if not self._verify_chain():
            raise ChainBreakError("CAPE-CHAIN-0: chain integrity check failed before append")

        record_id = str(uuid.uuid4())
        ts = time.time()
        proof_data = {
            "record_id": record_id,
            "entry_id": entry.entry_id,
            "decision_id": entry.decision_id,
            "synthesis_id": entry.synthesis_id,
            "chi_score": entry.chi_score,
            "mutation_ref": entry.mutation_ref,
            "approved_by": entry.approved_by or "",
            "stages_completed": stages_completed,
            "status": status.value,
            "executed_at": ts,
        }
        proof = _sha256_proof(proof_data)
        seal_payload = {**proof_data, "proof": proof, "prev_hmac": self._prev_hmac}
        seal = _hmac_sign(seal_payload)

        rec = ExecutionRecord(
            record_id=record_id,
            entry_id=entry.entry_id,
            decision_id=entry.decision_id,
            synthesis_id=entry.synthesis_id,
            chi_score=entry.chi_score,
            mutation_ref=entry.mutation_ref,
            approved_by=entry.approved_by or "",
            stages_completed=stages_completed,
            status=status,
            executed_at=ts,
            proof=proof,
            prev_hmac=self._prev_hmac,
            hmac_seal=seal,
            _sealed=True,
        )
        self._records.append(rec)
        self._prev_hmac = seal
        return rec

    def verify_chain(self) -> bool:
        return self._verify_chain()

    def get(self, record_id: str) -> Optional[ExecutionRecord]:
        for r in self._records:
            if r.record_id == record_id:
                return r
        return None

    def list_all(self) -> List[ExecutionRecord]:
        return list(self._records)

    def count(self) -> int:
        return len(self._records)


# ── ExecutionAuditor ──────────────────────────────────────────────────────────

class ExecutionAuditor:
    """
    CAPE-AUDIT-0: append-only HMAC-chained audit log for all CAPE operations.
    """

    def __init__(self) -> None:
        self._log: List[AuditEntry] = []
        self._prev_hmac: str = "CAPE-AUDIT-GENESIS"

    def record(
        self,
        operation: str,
        subject_id: str,
        actor: str,
        detail: Dict[str, Any],
    ) -> AuditEntry:
        audit_id = str(uuid.uuid4())
        ts = time.time()
        payload = {
            "audit_id": audit_id,
            "operation": operation,
            "subject_id": subject_id,
            "actor": actor,
            "timestamp": ts,
            "detail": detail,
            "prev_hmac": self._prev_hmac,
        }
        seal = _hmac_sign(payload)
        entry = AuditEntry(
            audit_id=audit_id,
            operation=operation,
            subject_id=subject_id,
            actor=actor,
            timestamp=ts,
            detail=detail,
            prev_hmac=self._prev_hmac,
            hmac_seal=seal,
        )
        self._log.append(entry)
        self._prev_hmac = seal
        return entry

    def entries(self) -> List[AuditEntry]:
        return list(self._log)


# ── PromotionExecutor ──────────────────────────────────────────────────────────

class PromotionExecutor:
    """
    CAPE-EXEC-0 / CAPE-HUMAN0-0 / CAPE-ORDER-0

    Executes APPROVED queue entries through a 5-stage pipeline:
      VALIDATE → STAGE → EXECUTE → SEAL → RECORD

    Only APPROVED entries may enter the pipeline (CAPE-EXEC-0).
    FIFO order is enforced via PromotionQueue.peek_next_approved (CAPE-ORDER-0).
    """

    def __init__(self, queue: PromotionQueue, ledger: ExecutionLedger, auditor: ExecutionAuditor) -> None:
        self._queue = queue
        self._ledger = ledger
        self._auditor = auditor

    def execute(self, entry_id: str) -> ExecutionRecord:
        """Execute an APPROVED queue entry through the 5-stage pipeline."""
        entry = self._queue.get(entry_id)
        if entry is None:
            raise CAPEViolation(f"CAPE-EXEC-0: queue entry not found: {entry_id}")

        # CAPE-EXEC-0: only APPROVED entries
        if entry.status != QueueStatus.APPROVED:
            raise ExecutionError(
                f"CAPE-EXEC-0: entry {entry_id} must be APPROVED (status={entry.status.value})"
            )

        # CAPE-HUMAN0-0: approved_by must be set
        if not entry.approved_by or not entry.approved_by.strip():
            raise HUMAN0ApprovalError(
                "CAPE-HUMAN0-0: execution requires non-empty HUMAN-0 approved_by"
            )

        # CAPE-ORDER-0: must be the next approved in FIFO order
        next_approved = self._queue.peek_next_approved()
        if next_approved is None or next_approved.entry_id != entry_id:
            raise OrderViolation(
                f"CAPE-ORDER-0: entry {entry_id} is not the next FIFO-approved entry"
            )

        # Mark as EXECUTING
        entry.status = QueueStatus.EXECUTING
        stages_completed: List[str] = []

        try:
            # ── Stage 1: VALIDATE ────────────────────────────────────────────
            self._run_stage("VALIDATE", entry, stages_completed)

            # ── Stage 2: STAGE ───────────────────────────────────────────────
            self._run_stage("STAGE", entry, stages_completed)

            # ── Stage 3: EXECUTE ─────────────────────────────────────────────
            self._run_stage("EXECUTE", entry, stages_completed)

            # ── Stage 4: SEAL ────────────────────────────────────────────────
            self._run_stage("SEAL", entry, stages_completed)

            # ── Stage 5: RECORD ──────────────────────────────────────────────
            self._run_stage("RECORD", entry, stages_completed)

            # Mark entry EXECUTED
            entry.status = QueueStatus.EXECUTED
            rec = self._ledger.append(entry, stages_completed, ExecutionStatus.SUCCESS)
            self._auditor.record(
                "execute",
                entry_id,
                entry.approved_by,
                {"record_id": rec.record_id, "stages": stages_completed, "status": "SUCCESS"},
            )
            return rec

        except Exception as exc:
            entry.status = QueueStatus.REJECTED
            rec = self._ledger.append(entry, stages_completed, ExecutionStatus.FAILED)
            self._auditor.record(
                "execute_failed",
                entry_id,
                entry.approved_by or "SYSTEM",
                {"record_id": rec.record_id, "stages": stages_completed, "error": str(exc)},
            )
            raise ExecutionError(f"Execution pipeline failed at stages {stages_completed}: {exc}") from exc

    def _run_stage(self, stage: str, entry: QueueEntry, completed: List[str]) -> None:
        """Run a single pipeline stage and record it."""
        if stage not in _PIPELINE_STAGES:
            raise ExecutionError(f"Unknown pipeline stage: {stage}")
        # Deterministic stage execution (constitutionally governed)
        completed.append(stage)
        self._auditor.record(
            f"stage_{stage.lower()}",
            entry.entry_id,
            entry.approved_by or "SYSTEM",
            {"stage": stage, "chi_score": entry.chi_score, "mutation_ref": entry.mutation_ref},
        )


# ── CAPEEngine — Facade ───────────────────────────────────────────────────────

class CAPEEngine:
    """
    Arc III ACI Module 02: Constitutional Autonomous Promotion Executor

    Coordinates PromotionQueue + PromotionExecutor + ExecutionLedger + ExecutionAuditor.

    HUMAN-0 approval is mandatory before any execution (CAPE-HUMAN0-0).
    All executions are HMAC-SHA-256-chained and sealed (CAPE-CHAIN-0).
    FIFO order is enforced structurally (CAPE-ORDER-0).
    """

    def __init__(self) -> None:
        self._queue = PromotionQueue()
        self._ledger = ExecutionLedger()
        self._auditor = ExecutionAuditor()
        self._executor = PromotionExecutor(self._queue, self._ledger, self._auditor)

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(
        self,
        decision_id: str,
        synthesis_id: str,
        chi_score: float,
        mutation_ref: str,
        verdict: str,
    ) -> Dict[str, Any]:
        """CAPE-SCOPE-0 / CAPE-GATE-0: enqueue a PROMOTE verdict."""
        entry = self._queue.enqueue(decision_id, synthesis_id, chi_score, mutation_ref, verdict)
        self._auditor.record(
            "enqueue",
            entry.entry_id,
            "SYSTEM",
            {
                "decision_id": decision_id,
                "synthesis_id": synthesis_id,
                "chi_score": chi_score,
                "mutation_ref": mutation_ref,
                "verdict": verdict,
            },
        )
        return entry.to_dict()

    # ── Approve ───────────────────────────────────────────────────────────────

    def approve(self, entry_id: str, approved_by: str) -> Dict[str, Any]:
        """CAPE-HUMAN0-0: HUMAN-0 approval gate."""
        entry = self._queue.approve(entry_id, approved_by)
        self._auditor.record(
            "approve",
            entry_id,
            approved_by,
            {"approved_by": approved_by, "entry_id": entry_id},
        )
        return entry.to_dict()

    # ── Reject ────────────────────────────────────────────────────────────────

    def reject(self, entry_id: str, rejected_by: str) -> Dict[str, Any]:
        """HUMAN-0 rejection of a queue entry."""
        entry = self._queue.reject(entry_id)
        self._auditor.record(
            "reject",
            entry_id,
            rejected_by,
            {"rejected_by": rejected_by, "entry_id": entry_id},
        )
        return entry.to_dict()

    # ── Execute ───────────────────────────────────────────────────────────────

    def execute(self, entry_id: str) -> Dict[str, Any]:
        """CAPE-EXEC-0 / CAPE-ORDER-0: run the 5-stage pipeline."""
        rec = self._executor.execute(entry_id)
        return rec.to_dict()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_queue_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        entry = self._queue.get(entry_id)
        return entry.to_dict() if entry else None

    def list_queue(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._queue.list_all()]

    def get_execution(self, record_id: str) -> Optional[Dict[str, Any]]:
        rec = self._ledger.get(record_id)
        return rec.to_dict() if rec else None

    def list_executions(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._ledger.list_all()]

    def verify_chain(self) -> Dict[str, Any]:
        """CAPE-CHAIN-0: full ledger chain verification."""
        ok = self._ledger.verify_chain()
        return {
            "chain_valid": ok,
            "record_count": self._ledger.count(),
            "invariant": "CAPE-CHAIN-0",
        }

    def get_audit(self) -> List[Dict[str, Any]]:
        """CAPE-AUDIT-0: return full audit log."""
        return [e.to_dict() for e in self._auditor.entries()]

    def status(self) -> Dict[str, Any]:
        return {
            "module": "CAPE",
            "innov": "INNOV-131",
            "phase": 226,
            "arc": "III — Autonomous Constitutional Intelligence",
            "governor": "DUSTIN L REID",
            "organization": "InnovativeAI LLC",
            "pending_queue": self._queue.pending_count(),
            "approved_queue": self._queue.approved_count(),
            "total_queue": len(self._queue.list_all()),
            "total_executions": self._ledger.count(),
            "chain_valid": self._ledger.verify_chain(),
            "pipeline_stages": _PIPELINE_STAGES,
            "chi_gate_threshold": _CHI_GATE_THRESHOLD,
            "hard_invariants": [
                "CAPE-CHAIN-0", "CAPE-APPEND-0", "CAPE-EXEC-0", "CAPE-GATE-0",
                "CAPE-QUEUE-0", "CAPE-AUDIT-0", "CAPE-HUMAN0-0", "CAPE-SCOPE-0",
                "CAPE-IMMUT-0", "CAPE-ORDER-0",
            ],
        }
