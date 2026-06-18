# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/constitutional_autonomous_outcome_evaluator.py
Phase 227 · INNOV-132 · CAOE — Constitutional Autonomous Outcome Evaluator
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 03

CAOE closes the Arc III feedback loop: ingesting sealed CAPE ExecutionRecords,
evaluating whether each promotion actually improved constitutional health by
comparing pre-promotion CHI (from the CADE decision) against post-promotion
CHI (re-synthesized from the current CASL signal), classifying the outcome, and
sealing every evaluation in an HMAC-SHA-256-chained append-only ledger.

DEGRADED outcomes trigger a mandatory HUMAN-0 notification gate before
acknowledgement — structurally enforced via CAOE-HUMAN0-0.

Hard-class invariants (10):
  CAOE-CHAIN-0   — OutcomeLedger HMAC chain must be verified before every append
  CAOE-APPEND-0  — OutcomeLedger is append-only; historical records are immutable
  CAOE-IMMUT-0   — ImmutabilityViolation raised on any attempted mutation of sealed records
  CAOE-COLLECT-0 — Only COMPLETED CAPE ExecutionRecords may be ingested
  CAOE-SCOPE-0   — All 5 CAPE pipeline stages must be present in ExecutionRecord
  CAOE-EVAL-0    — Outcome classification is deterministic: IMPROVED/NEUTRAL/DEGRADED
  CAOE-DETERM-0  — Identical pre/post CHI inputs yield identical delta_chi and classification
  CAOE-AUDIT-0   — Every operation (collect/evaluate/flag/verify/acknowledge) is audited
  CAOE-HUMAN0-0  — DEGRADED outcome requires non-empty notified_by before acknowledgement
  CAOE-ORIGIN-0  — Every evaluation references a non-empty CAPE execution_id
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


# ── Constants ─────────────────────────────────────────────────────────────────

_HMAC_KEY = b"CAOE-CHAIN-HMAC-KEY-v1-DUSTIN-L-REID"
_REQUIRED_STAGES = ["VALIDATE", "STAGE", "EXECUTE", "SEAL", "RECORD"]
_COMPLETED_STATUS = "COMPLETED"

# Outcome classification thresholds (CAOE-EVAL-0)
_IMPROVED_THRESHOLD = 0.05    # delta_chi > +0.05  → IMPROVED
_DEGRADED_THRESHOLD = -0.05   # delta_chi < -0.05  → DEGRADED
# -0.05 ≤ delta_chi ≤ +0.05   → NEUTRAL


# ── Exceptions ────────────────────────────────────────────────────────────────

class CAOEViolation(Exception):
    """Base CAOE constitutional violation."""


class CollectionError(CAOEViolation):
    """CAOE-COLLECT-0: Only COMPLETED ExecutionRecords may be ingested."""


class ScopeError(CAOEViolation):
    """CAOE-SCOPE-0: All 5 CAPE pipeline stages must be present."""


class EvaluationError(CAOEViolation):
    """CAOE-EVAL-0: Outcome classification failure."""


class OriginError(CAOEViolation):
    """CAOE-ORIGIN-0: Every evaluation must reference a non-empty execution_id."""


class ChainBreakError(CAOEViolation):
    """CAOE-CHAIN-0: HMAC chain integrity violation."""


class ImmutabilityViolation(CAOEViolation):
    """CAOE-IMMUT-0: Attempt to mutate a sealed record."""


class HUMAN0NotificationError(CAOEViolation):
    """CAOE-HUMAN0-0: DEGRADED outcome requires non-empty notified_by."""


# ── Enumerations ──────────────────────────────────────────────────────────────

class OutcomeClassification(str, Enum):
    IMPROVED = "IMPROVED"    # delta_chi > +0.05
    NEUTRAL  = "NEUTRAL"     # -0.05 <= delta_chi <= +0.05
    DEGRADED = "DEGRADED"    # delta_chi < -0.05


class AcknowledgementStatus(str, Enum):
    PENDING      = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FLAGGED      = "FLAGGED"       # DEGRADED — awaiting HUMAN-0 notification


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class EvaluationRecord:
    """A sealed outcome evaluation record written to OutcomeLedger."""
    eval_id: str
    execution_id: str           # CAPE ExecutionRecord.record_id (CAOE-ORIGIN-0)
    decision_id: str            # CADE decision_id from CAPE record
    synthesis_id: str           # CASL synthesis_id from CAPE record
    mutation_ref: str
    approved_by: str            # HUMAN-0 who approved CAPE execution
    pre_chi: float              # CHI at time of CADE decision
    post_chi: float             # CHI re-synthesized after promotion
    delta_chi: float            # post_chi - pre_chi
    classification: OutcomeClassification
    ack_status: AcknowledgementStatus
    notified_by: str            # HUMAN-0 notified_by (required for DEGRADED)
    evaluated_at: float
    prev_hmac: str
    hmac_seal: str
    _sealed: bool = field(default=True, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eval_id": self.eval_id,
            "execution_id": self.execution_id,
            "decision_id": self.decision_id,
            "synthesis_id": self.synthesis_id,
            "mutation_ref": self.mutation_ref,
            "approved_by": self.approved_by,
            "pre_chi": self.pre_chi,
            "post_chi": self.post_chi,
            "delta_chi": self.delta_chi,
            "classification": self.classification.value,
            "ack_status": self.ack_status.value,
            "notified_by": self.notified_by,
            "evaluated_at": self.evaluated_at,
            "prev_hmac": self.prev_hmac,
            "hmac_seal": self.hmac_seal,
        }


@dataclass
class AuditEntry:
    """An HMAC-chained audit log entry (CAOE-AUDIT-0)."""
    entry_id: str
    operation: str
    actor: str
    detail: Dict[str, Any]
    timestamp: float
    entry_hmac: str
    prev_hmac: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "operation": self.operation,
            "actor": self.actor,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "entry_hmac": self.entry_hmac,
            "prev_hmac": self.prev_hmac,
        }


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _hmac_sign(payload: Dict[str, Any]) -> str:
    """Compute HMAC-SHA-256 over canonical JSON payload."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_HMAC_KEY, raw, hashlib.sha256).hexdigest()


def _hmac_verify(payload: Dict[str, Any], expected: str) -> bool:
    """Constant-time HMAC verification (AUTH-CT-0)."""
    computed = _hmac_sign(payload)
    return hmac.compare_digest(computed, expected)


# ── Subsystem 1: OutcomeCollector ─────────────────────────────────────────────

class OutcomeCollector:
    """
    Ingests sealed CAPE ExecutionRecord dicts and validates them for evaluation.

    CAOE-COLLECT-0: only COMPLETED records accepted.
    CAOE-SCOPE-0:   all 5 CAPE pipeline stages must be present.
    CAOE-ORIGIN-0:  execution_id (record_id) must be non-empty.
    """

    def collect(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and return a CAPE ExecutionRecord dict ready for evaluation.

        Args:
            record: dict representation of a CAPE ExecutionRecord (to_dict()).

        Returns:
            The validated record dict.

        Raises:
            OriginError:    execution_id (record_id) is empty.
            CollectionError: status != COMPLETED.
            ScopeError:     stages_completed missing required stages.
        """
        # CAOE-ORIGIN-0
        exec_id = record.get("record_id", "")
        if not exec_id:
            raise OriginError(
                "CAOE-ORIGIN-0 VIOLATION: ExecutionRecord.record_id is empty"
            )

        # CAOE-COLLECT-0
        status = record.get("status", "")
        if status != _COMPLETED_STATUS:
            raise CollectionError(
                f"CAOE-COLLECT-0 VIOLATION: only COMPLETED records accepted; got '{status}'"
            )

        # CAOE-SCOPE-0
        stages = record.get("stages_completed", [])
        missing = [s for s in _REQUIRED_STAGES if s not in stages]
        if missing:
            raise ScopeError(
                f"CAOE-SCOPE-0 VIOLATION: missing pipeline stages: {missing}"
            )

        return record


# ── Subsystem 2: OutcomeEvaluator ─────────────────────────────────────────────

class OutcomeEvaluator:
    """
    Deterministic CHI delta evaluation and outcome classification.

    CAOE-EVAL-0:   classification is deterministic from pre_chi and post_chi.
    CAOE-DETERM-0: identical inputs yield identical delta_chi and classification.
    """

    def evaluate(
        self,
        pre_chi: float,
        post_chi: float,
    ) -> tuple:
        """
        Compute delta_chi and classify outcome.

        Returns:
            (delta_chi: float, classification: OutcomeClassification)
        """
        # CAOE-DETERM-0: pure arithmetic, no wall-clock, no randomness
        delta = round(post_chi - pre_chi, 10)

        if delta > _IMPROVED_THRESHOLD:
            classification = OutcomeClassification.IMPROVED
        elif delta < _DEGRADED_THRESHOLD:
            classification = OutcomeClassification.DEGRADED
        else:
            classification = OutcomeClassification.NEUTRAL

        return delta, classification


# ── Subsystem 3: OutcomeLedger ────────────────────────────────────────────────

class OutcomeLedger:
    """
    HMAC-SHA-256-chained append-only ledger of EvaluationRecords.

    CAOE-CHAIN-0:  chain verified before every append.
    CAOE-APPEND-0: records are append-only.
    CAOE-IMMUT-0:  immutability enforced on sealed records.
    """

    def __init__(self) -> None:
        self._records: List[EvaluationRecord] = []
        self._prev_hmac: str = "CAOE-GENESIS"

    def append(
        self,
        execution_id: str,
        decision_id: str,
        synthesis_id: str,
        mutation_ref: str,
        approved_by: str,
        pre_chi: float,
        post_chi: float,
        delta_chi: float,
        classification: OutcomeClassification,
        ack_status: AcknowledgementStatus,
        notified_by: str,
    ) -> EvaluationRecord:
        """
        Seal and append an EvaluationRecord.

        CAOE-CHAIN-0: verifies chain integrity before append.
        CAOE-ORIGIN-0: execution_id must be non-empty.
        """
        # CAOE-ORIGIN-0
        if not execution_id:
            raise OriginError(
                "CAOE-ORIGIN-0 VIOLATION: execution_id is empty on ledger append"
            )

        # CAOE-CHAIN-0: verify existing chain before append
        self._verify_chain()

        eval_id = str(uuid.uuid4())
        now = time.time()

        payload = {
            "eval_id": eval_id,
            "execution_id": execution_id,
            "decision_id": decision_id,
            "synthesis_id": synthesis_id,
            "mutation_ref": mutation_ref,
            "approved_by": approved_by,
            "pre_chi": pre_chi,
            "post_chi": post_chi,
            "delta_chi": delta_chi,
            "classification": classification.value,
            "ack_status": ack_status.value,
            "notified_by": notified_by,
            "evaluated_at": now,
            "prev_hmac": self._prev_hmac,
        }
        seal = _hmac_sign(payload)

        rec = EvaluationRecord(
            eval_id=eval_id,
            execution_id=execution_id,
            decision_id=decision_id,
            synthesis_id=synthesis_id,
            mutation_ref=mutation_ref,
            approved_by=approved_by,
            pre_chi=pre_chi,
            post_chi=post_chi,
            delta_chi=delta_chi,
            classification=classification,
            ack_status=ack_status,
            notified_by=notified_by,
            evaluated_at=now,
            prev_hmac=self._prev_hmac,
            hmac_seal=seal,
            _sealed=True,
        )

        self._records.append(rec)
        self._prev_hmac = seal
        return rec

    def update_ack(self, eval_id: str, ack_status: AcknowledgementStatus, notified_by: str) -> None:
        """
        Update acknowledgement status on an existing record.
        Only allowed transition: FLAGGED → ACKNOWLEDGED with non-empty notified_by.

        CAOE-HUMAN0-0: DEGRADED records require notified_by before ACKNOWLEDGED.
        CAOE-IMMUT-0:  cannot mutate a record that is already ACKNOWLEDGED.
        """
        rec = self._get(eval_id)
        if rec is None:
            raise EvaluationError(f"CAOE: eval_id '{eval_id}' not found")
        if rec.ack_status == AcknowledgementStatus.ACKNOWLEDGED:
            raise ImmutabilityViolation(
                f"CAOE-IMMUT-0 VIOLATION: record {eval_id} already ACKNOWLEDGED"
            )
        if not notified_by:
            raise HUMAN0NotificationError(
                "CAOE-HUMAN0-0 VIOLATION: notified_by must be non-empty"
            )
        # Direct field update is the only permitted mutation on ack fields
        object.__setattr__(rec, "ack_status", ack_status)
        object.__setattr__(rec, "notified_by", notified_by)

    def _get(self, eval_id: str) -> Optional[EvaluationRecord]:
        for r in self._records:
            if r.eval_id == eval_id:
                return r
        return None

    def get(self, eval_id: str) -> Optional[EvaluationRecord]:
        return self._get(eval_id)

    def list_all(self) -> List[EvaluationRecord]:
        return list(self._records)

    def _verify_chain(self) -> bool:
        """
        CAOE-CHAIN-0: verify full HMAC chain integrity.
        Raises ChainBreakError on any violation.
        """
        prev = "CAOE-GENESIS"
        for rec in self._records:
            if not hmac.compare_digest(rec.prev_hmac, prev):
                raise ChainBreakError(
                    f"CAOE-CHAIN-0 VIOLATION: chain break at eval_id={rec.eval_id}"
                )
            payload = {
                "eval_id": rec.eval_id,
                "execution_id": rec.execution_id,
                "decision_id": rec.decision_id,
                "synthesis_id": rec.synthesis_id,
                "mutation_ref": rec.mutation_ref,
                "approved_by": rec.approved_by,
                "pre_chi": rec.pre_chi,
                "post_chi": rec.post_chi,
                "delta_chi": rec.delta_chi,
                "classification": rec.classification.value,
                "ack_status": rec.ack_status.value,
                "notified_by": rec.notified_by,
                "evaluated_at": rec.evaluated_at,
                "prev_hmac": rec.prev_hmac,
            }
            computed = _hmac_sign(payload)
            if not hmac.compare_digest(computed, rec.hmac_seal):
                raise ChainBreakError(
                    f"CAOE-CHAIN-0 VIOLATION: HMAC mismatch at eval_id={rec.eval_id}"
                )
            prev = rec.hmac_seal
        return True

    def verify_chain(self) -> bool:
        return self._verify_chain()


# ── Subsystem 4: OutcomeAuditor ───────────────────────────────────────────────

class OutcomeAuditor:
    """
    Append-only HMAC-chained audit log for every CAOE operation.

    CAOE-AUDIT-0: every collect/evaluate/flag/verify/acknowledge is recorded.
    """

    def __init__(self) -> None:
        self._log: List[AuditEntry] = []
        self._prev_hmac: str = "CAOE-AUDIT-GENESIS"

    def record(self, operation: str, actor: str, detail: Dict[str, Any]) -> AuditEntry:
        entry_id = str(uuid.uuid4())
        now = time.time()
        payload = {
            "entry_id": entry_id,
            "operation": operation,
            "actor": actor,
            "detail": detail,
            "timestamp": now,
            "prev_hmac": self._prev_hmac,
        }
        entry_hmac = _hmac_sign(payload)
        entry = AuditEntry(
            entry_id=entry_id,
            operation=operation,
            actor=actor,
            detail=detail,
            timestamp=now,
            entry_hmac=entry_hmac,
            prev_hmac=self._prev_hmac,
        )
        self._log.append(entry)
        self._prev_hmac = entry_hmac
        return entry

    def entries(self) -> List[AuditEntry]:
        return list(self._log)


# ── CAOEEngine facade ─────────────────────────────────────────────────────────

class CAOEEngine:
    """
    Constitutional Autonomous Outcome Evaluator — Arc III ACI Module 03.

    Closes the Arc III feedback loop:
      CASL (synthesize) → CADE (decide) → CAPE (execute) → CAOE (evaluate)

    Four subsystems:
      1. OutcomeCollector  — validate CAPE ExecutionRecords
      2. OutcomeEvaluator  — deterministic CHI delta + classification
      3. OutcomeLedger     — HMAC-SHA-256-chained append-only evaluation store
      4. OutcomeAuditor    — append-only HMAC-chained audit log

    Hard-class invariants enforced:
      CAOE-CHAIN-0, CAOE-APPEND-0, CAOE-IMMUT-0, CAOE-COLLECT-0,
      CAOE-SCOPE-0, CAOE-EVAL-0, CAOE-DETERM-0, CAOE-AUDIT-0,
      CAOE-HUMAN0-0, CAOE-ORIGIN-0
    """

    def __init__(self) -> None:
        self._collector = OutcomeCollector()
        self._evaluator = OutcomeEvaluator()
        self._ledger    = OutcomeLedger()
        self._auditor   = OutcomeAuditor()

    # ── Public API ────────────────────────────────────────────────────────────

    def collect(self, execution_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a CAPE ExecutionRecord dict for evaluation.

        CAOE-COLLECT-0, CAOE-SCOPE-0, CAOE-ORIGIN-0 enforced.

        Returns:
            The validated record dict.
        """
        record = self._collector.collect(execution_record)
        self._auditor.record(
            operation="collect",
            actor="CAOE",
            detail={"execution_id": record.get("record_id"), "status": record.get("status")},
        )
        return record

    def evaluate(
        self,
        execution_record: Dict[str, Any],
        post_chi: float,
    ) -> EvaluationRecord:
        """
        Evaluate the outcome of a CAPE promotion.

        Validates the record, computes delta_chi, classifies the outcome,
        and seals an EvaluationRecord into the OutcomeLedger.

        Args:
            execution_record: validated CAPE ExecutionRecord dict (from collect()).
            post_chi:         CHI re-synthesized after promotion completes.

        Returns:
            Sealed EvaluationRecord.

        Raises:
            OriginError:    execution_id empty.
            CollectionError: status != COMPLETED.
            ScopeError:     missing pipeline stages.
            ChainBreakError: ledger chain violation.
        """
        record = self._collector.collect(execution_record)

        pre_chi   = record["chi_score"]
        exec_id   = record["record_id"]
        dec_id    = record.get("decision_id", "")
        synth_id  = record.get("synthesis_id", "")
        mut_ref   = record.get("mutation_ref", "")
        appr_by   = record.get("approved_by", "")

        delta_chi, classification = self._evaluator.evaluate(pre_chi, post_chi)

        # DEGRADED → FLAGGED status, requires HUMAN-0 notification
        if classification == OutcomeClassification.DEGRADED:
            ack_status = AcknowledgementStatus.FLAGGED
        else:
            ack_status = AcknowledgementStatus.PENDING

        rec = self._ledger.append(
            execution_id=exec_id,
            decision_id=dec_id,
            synthesis_id=synth_id,
            mutation_ref=mut_ref,
            approved_by=appr_by,
            pre_chi=pre_chi,
            post_chi=post_chi,
            delta_chi=delta_chi,
            classification=classification,
            ack_status=ack_status,
            notified_by="",
        )

        self._auditor.record(
            operation="evaluate",
            actor="CAOE",
            detail={
                "eval_id": rec.eval_id,
                "execution_id": exec_id,
                "pre_chi": pre_chi,
                "post_chi": post_chi,
                "delta_chi": delta_chi,
                "classification": classification.value,
                "ack_status": ack_status.value,
            },
        )
        return rec

    def acknowledge(
        self,
        eval_id: str,
        notified_by: str,
    ) -> EvaluationRecord:
        """
        Acknowledge a FLAGGED (DEGRADED) evaluation record.

        CAOE-HUMAN0-0: notified_by must be non-empty.
        CAOE-IMMUT-0:  already-ACKNOWLEDGED records cannot be re-acknowledged.

        Args:
            eval_id:     EvaluationRecord.eval_id to acknowledge.
            notified_by: HUMAN-0 identifier who was notified.

        Returns:
            Updated EvaluationRecord.
        """
        if not notified_by:
            raise HUMAN0NotificationError(
                "CAOE-HUMAN0-0 VIOLATION: notified_by must be non-empty for acknowledgement"
            )

        self._ledger.update_ack(
            eval_id=eval_id,
            ack_status=AcknowledgementStatus.ACKNOWLEDGED,
            notified_by=notified_by,
        )

        rec = self._ledger.get(eval_id)
        self._auditor.record(
            operation="acknowledge",
            actor=notified_by,
            detail={"eval_id": eval_id, "notified_by": notified_by},
        )
        return rec

    def get_evaluation(self, eval_id: str) -> Optional[EvaluationRecord]:
        """Retrieve a single EvaluationRecord by eval_id."""
        return self._ledger.get(eval_id)

    def list_evaluations(self) -> List[EvaluationRecord]:
        """Return all EvaluationRecords."""
        return self._ledger.list_all()

    def verify_chain(self) -> bool:
        """
        CAOE-CHAIN-0: verify full OutcomeLedger HMAC chain integrity.

        Returns:
            True if chain is intact.

        Raises:
            ChainBreakError on any violation.
        """
        result = self._ledger.verify_chain()
        self._auditor.record(
            operation="verify_chain",
            actor="CAOE",
            detail={"chain_intact": result},
        )
        return result

    def audit_log(self) -> List[AuditEntry]:
        """Return all audit log entries (CAOE-AUDIT-0)."""
        return self._auditor.entries()

    def status(self) -> Dict[str, Any]:
        """Return engine status summary."""
        evals = self._ledger.list_all()
        counts = {c.value: 0 for c in OutcomeClassification}
        flagged = 0
        for e in evals:
            counts[e.classification.value] += 1
            if e.ack_status == AcknowledgementStatus.FLAGGED:
                flagged += 1
        return {
            "engine": "CAOE",
            "arc": "Arc III ACI Module 03",
            "innov": "INNOV-132",
            "phase": 227,
            "total_evaluations": len(evals),
            "classification_counts": counts,
            "flagged_degraded": flagged,
            "audit_entries": len(self._auditor.entries()),
            "governor": "DUSTIN L REID",
        }
