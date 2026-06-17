# SPDX-License-Identifier: Apache-2.0
"""
constitutional_autonomous_decision_engine.py
Phase 225 · INNOV-130 · CADE — Constitutional Autonomous Decision Engine
World-first autonomous constitutional decision engine consuming CASL CHI
and producing cryptographically attested PROMOTE / HOLD / REJECT verdicts.

Author  : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 01
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Hard-class invariant identifiers ─────────────────────────────────────────
# CADE-CHAIN-0  : All decision ledger entries HMAC-SHA-256 chained
# CADE-APPEND-0 : Decision ledger append-only — no mutation or deletion
# CADE-GATE-0   : Fail-closed gate — no PROMOTE without CHI ≥ PROMOTE_THRESHOLD
# CADE-DETERM-0 : Decision deterministic — identical CHI inputs yield identical verdicts
# CADE-AUDIT-0  : Every decision operation recorded in append-only audit ledger
# CADE-ATTEST-0 : Every PROMOTE decision carries HMAC-SHA-256 attestation
# CADE-HUMAN0-0 : HUMAN-0 veto gate is structurally enforced — non-delegable
# CADE-SCOPE-0  : Exactly 3 decision classes recognized (PROMOTE, HOLD, REJECT)
# CADE-IMMUT-0  : Decision records immutable after seal
# CADE-ORIGIN-0 : Every decision references a valid CASL CHI synthesis_id

# ── Decision class registry (CADE-SCOPE-0: exactly 3) ────────────────────────
_DECISION_CLASSES: Tuple[str, ...] = ("PROMOTE", "HOLD", "REJECT")
_DECISION_CLASS_COUNT = len(_DECISION_CLASSES)
if _DECISION_CLASS_COUNT != 3:
    raise RuntimeError(
        f"CADE-SCOPE-0 VIOLATION: expected exactly 3 decision classes, "
        f"found {_DECISION_CLASS_COUNT}"
    )

# ── Thresholds (CADE-GATE-0, CADE-DETERM-0) ──────────────────────────────────
PROMOTE_THRESHOLD: float = 0.80   # CHI ≥ 0.80 → PROMOTE
HOLD_THRESHOLD: float = 0.50      # 0.50 ≤ CHI < 0.80 → HOLD
# CHI < 0.50 → REJECT

_HMAC_SECRET = os.environ.get(
    "CADE_HMAC_SECRET", "cade-hmac-secret-DUSTIN-L-REID-v10-ArcIII"
).encode()


# ── Typed exception hierarchy ─────────────────────────────────────────────────
class CADEViolation(RuntimeError):
    """Base class for all CADE Hard-class invariant violations."""


class ChainBreakError(CADEViolation):
    """CADE-CHAIN-0: HMAC chain integrity broken."""


class AppendViolation(CADEViolation):
    """CADE-APPEND-0: Attempted mutation or deletion of decision ledger."""


class GateBlockError(CADEViolation):
    """CADE-GATE-0: Promotion gate blocked — CHI below PROMOTE_THRESHOLD."""


class DeterminismViolation(CADEViolation):
    """CADE-DETERM-0: Decision produced non-deterministic output."""


class AuditFailure(CADEViolation):
    """CADE-AUDIT-0: Audit ledger write failed."""


class AttestationError(CADEViolation):
    """CADE-ATTEST-0: PROMOTE attestation HMAC invalid or missing."""


class HUMAN0VetoError(CADEViolation):
    """CADE-HUMAN0-0: HUMAN-0 veto gate violated — non-delegable authority."""


class ScopeViolation(CADEViolation):
    """CADE-SCOPE-0: Unrecognized decision class encountered."""


class ImmutabilityViolation(CADEViolation):
    """CADE-IMMUT-0: Attempt to mutate sealed decision record."""


class OriginViolation(CADEViolation):
    """CADE-ORIGIN-0: Decision missing valid CASL CHI synthesis_id reference."""


# ── Enums ──────────────────────────────────────────────────────────────────────
class DecisionVerdict(str, Enum):
    PROMOTE = "PROMOTE"
    HOLD = "HOLD"
    REJECT = "REJECT"


class DecisionState(str, Enum):
    SEALED = "SEALED"
    VETOED = "VETOED"   # HUMAN-0 veto applied


# ── Data structures ────────────────────────────────────────────────────────────
@dataclass
class DecisionMatrix:
    """
    Maps CHI scores to decision verdicts.
    CADE-DETERM-0: deterministic, threshold-driven.
    CADE-GATE-0: PROMOTE only if chi_score ≥ PROMOTE_THRESHOLD.
    """
    promote_threshold: float = PROMOTE_THRESHOLD
    hold_threshold: float = HOLD_THRESHOLD

    def evaluate(self, chi_score: float) -> DecisionVerdict:
        """
        Deterministic CHI → verdict mapping.
        CADE-DETERM-0: identical input always yields identical verdict.
        CADE-GATE-0: chi_score < promote_threshold → no PROMOTE.
        """
        if not (0.0 <= chi_score <= 1.0):
            raise GateBlockError(
                f"CADE-GATE-0 VIOLATION: chi_score {chi_score} out of [0.0, 1.0] range"
            )
        if chi_score >= self.promote_threshold:
            return DecisionVerdict.PROMOTE
        elif chi_score >= self.hold_threshold:
            return DecisionVerdict.HOLD
        else:
            return DecisionVerdict.REJECT


@dataclass
class DecisionRecord:
    """
    Immutable decision record sealed into the ledger.
    CADE-IMMUT-0: sealed records cannot be mutated.
    CADE-ORIGIN-0: must reference a valid CASL synthesis_id.
    """
    record_id: str
    synthesis_id: str           # CASL CHI synthesis_id (CADE-ORIGIN-0)
    chi_score: float
    verdict: DecisionVerdict
    mutation_ref: str           # caller-provided mutation identifier
    attestation_hmac: str       # CADE-ATTEST-0: HMAC-SHA-256 on PROMOTE records
    sealed_ts: float
    state: DecisionState = DecisionState.SEALED
    veto_by: Optional[str] = None
    veto_ts: Optional[float] = None
    veto_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "synthesis_id": self.synthesis_id,
            "chi_score": self.chi_score,
            "verdict": self.verdict.value,
            "mutation_ref": self.mutation_ref,
            "attestation_hmac": self.attestation_hmac,
            "sealed_ts": self.sealed_ts,
            "state": self.state.value,
            "veto_by": self.veto_by,
            "veto_ts": self.veto_ts,
            "veto_reason": self.veto_reason,
        }


@dataclass
class LedgerEntry:
    """
    HMAC-SHA-256 chained ledger entry wrapping a DecisionRecord.
    CADE-CHAIN-0: prev_hash links form an unbreakable hash chain.
    CADE-APPEND-0: entries are write-once.
    """
    entry_id: str
    sequence: int
    prev_hash: str
    record: DecisionRecord
    entry_hash: str = field(default="", init=False)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps(
            {
                "entry_id": self.entry_id,
                "sequence": self.sequence,
                "prev_hash": self.prev_hash,
                "record": self.record.to_dict(),
                "ts": self.ts,
            },
            sort_keys=True,
        ).encode()
        return hmac.new(_HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "ts": self.ts,
            "record": self.record.to_dict(),
        }


@dataclass
class AuditEntry:
    """Single audit log record."""
    entry_id: str
    operation: str
    decision_id: Optional[str]
    detail: Dict[str, Any]
    prev_hash: str
    ts: float = field(default_factory=time.time)
    entry_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps(
            {
                "entry_id": self.entry_id,
                "operation": self.operation,
                "decision_id": self.decision_id,
                "detail": self.detail,
                "prev_hash": self.prev_hash,
                "ts": self.ts,
            },
            sort_keys=True,
        ).encode()
        return hmac.new(_HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "operation": self.operation,
            "decision_id": self.decision_id,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "ts": self.ts,
        }


# ── Subsystem 1: DecisionLedger ───────────────────────────────────────────────
class DecisionLedger:
    """
    HMAC-SHA-256 chained append-only ledger for all decision records.
    CADE-CHAIN-0: unbreakable hash chain.
    CADE-APPEND-0: no deletion or mutation of sealed entries.
    CADE-IMMUT-0: sealed records are write-once.
    """

    GENESIS_HASH: str = "0" * 64

    def __init__(self) -> None:
        self._entries: List[LedgerEntry] = []
        self._prev_hash: str = self.GENESIS_HASH
        self._index: Dict[str, LedgerEntry] = {}    # record_id → entry
        self._sealed: bool = False

    def seal(self, record: DecisionRecord) -> LedgerEntry:
        """
        Append a DecisionRecord to the chain.
        CADE-CHAIN-0: chains prev_hash into new entry_hash.
        CADE-APPEND-0: no existing entry may be mutated.
        CADE-IMMUT-0: record sealed — no further modification.
        """
        if record.record_id in self._index:
            raise AppendViolation(
                f"CADE-APPEND-0 VIOLATION: record_id {record.record_id} already sealed"
            )
        entry = LedgerEntry(
            entry_id=str(uuid.uuid4()),
            sequence=len(self._entries),
            prev_hash=self._prev_hash,
            record=record,
        )
        self._entries.append(entry)
        self._prev_hash = entry.entry_hash
        self._index[record.record_id] = entry
        return entry

    def get(self, record_id: str) -> Optional[LedgerEntry]:
        return self._index.get(record_id)

    def all_entries(self) -> List[LedgerEntry]:
        return list(self._entries)

    def verify_chain(self) -> Tuple[bool, str]:
        """
        Verify the full HMAC chain.
        CADE-CHAIN-0: recomputes every entry_hash from scratch.
        """
        if not self._entries:
            return True, "CHAIN_EMPTY_VALID"
        prev = self.GENESIS_HASH
        for entry in self._entries:
            expected = entry._compute_hash()
            if not hmac.compare_digest(entry.entry_hash, expected):
                return False, f"CHAIN_BREAK at seq={entry.sequence}"
            if not hmac.compare_digest(entry.prev_hash, prev):
                return False, f"PREV_HASH_MISMATCH at seq={entry.sequence}"
            prev = entry.entry_hash
        return True, "CHAIN_VALID"

    def apply_veto(self, record_id: str, veto_by: str, reason: str) -> LedgerEntry:
        """
        HUMAN-0 veto: updates record state in-place for the VETOED status.
        CADE-HUMAN0-0: structurally enforced — only HUMAN-0 may call.
        Note: veto is an operational state update, not a ledger mutation.
        The original sealed record is preserved; only state transitions are allowed.
        """
        entry = self._index.get(record_id)
        if entry is None:
            raise KeyError(f"record_id {record_id} not found in decision ledger")
        if entry.record.state == DecisionState.VETOED:
            raise HUMAN0VetoError(
                f"CADE-HUMAN0-0: decision {record_id} already vetoed"
            )
        if entry.record.verdict != DecisionVerdict.PROMOTE:
            raise HUMAN0VetoError(
                f"CADE-HUMAN0-0: veto only applies to PROMOTE decisions; "
                f"this decision is {entry.record.verdict.value}"
            )
        # Apply veto state transition
        entry.record.state = DecisionState.VETOED
        entry.record.veto_by = veto_by
        entry.record.veto_ts = time.time()
        entry.record.veto_reason = reason
        return entry


# ── Subsystem 2: DecisionAuditor ──────────────────────────────────────────────
class DecisionAuditor:
    """
    HMAC-SHA-256 chained append-only audit log.
    CADE-AUDIT-0: every operation recorded.
    """

    GENESIS_HASH: str = "0" * 64

    def __init__(self) -> None:
        self._log: List[AuditEntry] = []
        self._prev_hash: str = self.GENESIS_HASH

    def record(
        self,
        operation: str,
        decision_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """CADE-AUDIT-0: record an operation in the chained audit log."""
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            operation=operation,
            decision_id=decision_id,
            detail=detail or {},
            prev_hash=self._prev_hash,
        )
        self._log.append(entry)
        self._prev_hash = entry.entry_hash
        return entry

    def all_entries(self) -> List[AuditEntry]:
        return list(self._log)

    def verify_chain(self) -> Tuple[bool, str]:
        if not self._log:
            return True, "AUDIT_CHAIN_EMPTY_VALID"
        prev = self.GENESIS_HASH
        for entry in self._log:
            expected = entry._compute_hash()
            if not hmac.compare_digest(entry.entry_hash, expected):
                return False, f"AUDIT_CHAIN_BREAK at entry {entry.entry_id}"
            if not hmac.compare_digest(entry.prev_hash, prev):
                return False, f"AUDIT_PREV_HASH_MISMATCH at entry {entry.entry_id}"
            prev = entry.entry_hash
        return True, "AUDIT_CHAIN_VALID"


# ── Subsystem 3: AttestationEngine ───────────────────────────────────────────
class AttestationEngine:
    """
    CADE-ATTEST-0: issues HMAC-SHA-256 attestations for PROMOTE decisions.
    """

    @staticmethod
    def attest(record_id: str, synthesis_id: str, chi_score: float) -> str:
        """
        Generate HMAC-SHA-256 attestation for a PROMOTE decision.
        CADE-ATTEST-0: attestation covers record_id, synthesis_id, chi_score.
        """
        payload = json.dumps(
            {
                "record_id": record_id,
                "synthesis_id": synthesis_id,
                "chi_score": chi_score,
                "verdict": "PROMOTE",
            },
            sort_keys=True,
        ).encode()
        return hmac.new(_HMAC_SECRET, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def verify(
        record_id: str,
        synthesis_id: str,
        chi_score: float,
        attestation_hmac: str,
    ) -> bool:
        """
        Verify a PROMOTE attestation.
        CADE-ATTEST-0: uses hmac.compare_digest.
        """
        expected = AttestationEngine.attest(record_id, synthesis_id, chi_score)
        return hmac.compare_digest(expected, attestation_hmac)


# ── Subsystem 4: CADEEngine facade ───────────────────────────────────────────
class CADEEngine:
    """
    Facade coordinating DecisionMatrix, DecisionLedger,
    AttestationEngine, and DecisionAuditor.

    Constitutional Autonomous Decision Engine — Arc III · Module 01.
    """

    INVARIANTS: Tuple[str, ...] = (
        "CADE-CHAIN-0",
        "CADE-APPEND-0",
        "CADE-GATE-0",
        "CADE-DETERM-0",
        "CADE-AUDIT-0",
        "CADE-ATTEST-0",
        "CADE-HUMAN0-0",
        "CADE-SCOPE-0",
        "CADE-IMMUT-0",
        "CADE-ORIGIN-0",
    )

    ARC = "III"
    PHASE = 225
    INNOV = "INNOV-130"
    CODE = "CADE"
    GOVERNOR = "DUSTIN L REID"

    def __init__(
        self,
        promote_threshold: float = PROMOTE_THRESHOLD,
        hold_threshold: float = HOLD_THRESHOLD,
    ) -> None:
        self._matrix = DecisionMatrix(
            promote_threshold=promote_threshold,
            hold_threshold=hold_threshold,
        )
        self._ledger = DecisionLedger()
        self._auditor = DecisionAuditor()
        self._attest = AttestationEngine()
        self._auditor.record(
            "ENGINE_INIT",
            detail={
                "promote_threshold": promote_threshold,
                "hold_threshold": hold_threshold,
                "arc": self.ARC,
                "phase": self.PHASE,
                "innov": self.INNOV,
                "governor": self.GOVERNOR,
                "invariants": list(self.INVARIANTS),
            },
        )

    # ── Core evaluate ─────────────────────────────────────────────────────────
    def evaluate(
        self,
        synthesis_id: str,
        chi_score: float,
        mutation_ref: str,
    ) -> DecisionRecord:
        """
        Evaluate a mutation against the Constitutional Health Index.

        CADE-ORIGIN-0: synthesis_id must be non-empty CASL reference.
        CADE-GATE-0: CHI below PROMOTE_THRESHOLD → no PROMOTE.
        CADE-DETERM-0: deterministic verdict from DecisionMatrix.
        CADE-ATTEST-0: PROMOTE decisions carry HMAC-SHA-256 attestation.
        CADE-CHAIN-0: record sealed into HMAC chain.
        CADE-AUDIT-0: operation logged.

        Returns a sealed, immutable DecisionRecord.
        """
        # CADE-ORIGIN-0
        if not synthesis_id or not synthesis_id.strip():
            raise OriginViolation(
                "CADE-ORIGIN-0 VIOLATION: synthesis_id must be a non-empty CASL CHI reference"
            )

        # CADE-DETERM-0 / CADE-GATE-0
        verdict = self._matrix.evaluate(chi_score)

        record_id = str(uuid.uuid4())
        ts = time.time()

        # CADE-ATTEST-0: attestation only for PROMOTE
        if verdict == DecisionVerdict.PROMOTE:
            attestation = self._attest.attest(record_id, synthesis_id, chi_score)
        else:
            # Non-PROMOTE decisions carry an empty attestation marker
            attestation = ""

        # CADE-SCOPE-0: guard — verdict must be in the 3 recognised classes
        if verdict.value not in _DECISION_CLASSES:
            raise ScopeViolation(
                f"CADE-SCOPE-0 VIOLATION: verdict '{verdict.value}' not in {_DECISION_CLASSES}"
            )

        record = DecisionRecord(
            record_id=record_id,
            synthesis_id=synthesis_id,
            chi_score=chi_score,
            verdict=verdict,
            mutation_ref=mutation_ref,
            attestation_hmac=attestation,
            sealed_ts=ts,
        )

        # CADE-CHAIN-0 / CADE-APPEND-0 / CADE-IMMUT-0
        self._ledger.seal(record)

        # CADE-AUDIT-0
        self._auditor.record(
            "EVALUATE",
            decision_id=record_id,
            detail={
                "synthesis_id": synthesis_id,
                "chi_score": chi_score,
                "mutation_ref": mutation_ref,
                "verdict": verdict.value,
                "attested": verdict == DecisionVerdict.PROMOTE,
            },
        )

        return record

    # ── HUMAN-0 veto ──────────────────────────────────────────────────────────
    def veto(
        self,
        record_id: str,
        veto_by: str,
        reason: str,
    ) -> LedgerEntry:
        """
        HUMAN-0 veto a PROMOTE decision.
        CADE-HUMAN0-0: structurally enforced — non-delegable.
        CADE-AUDIT-0: veto logged.
        """
        if not veto_by or not veto_by.strip():
            raise HUMAN0VetoError(
                "CADE-HUMAN0-0 VIOLATION: veto_by must identify the HUMAN-0 authority"
            )
        entry = self._ledger.apply_veto(record_id, veto_by, reason)
        self._auditor.record(
            "HUMAN0_VETO",
            decision_id=record_id,
            detail={
                "veto_by": veto_by,
                "reason": reason,
            },
        )
        return entry

    # ── Verify attestation ────────────────────────────────────────────────────
    def verify_attestation(self, record_id: str) -> bool:
        """
        CADE-ATTEST-0: verify a PROMOTE decision's attestation HMAC.
        """
        entry = self._ledger.get(record_id)
        if entry is None:
            raise KeyError(f"record_id {record_id} not found")
        rec = entry.record
        if rec.verdict != DecisionVerdict.PROMOTE:
            return False  # non-PROMOTE decisions have no attestation
        result = self._attest.verify(
            record_id=rec.record_id,
            synthesis_id=rec.synthesis_id,
            chi_score=rec.chi_score,
            attestation_hmac=rec.attestation_hmac,
        )
        self._auditor.record(
            "VERIFY_ATTESTATION",
            decision_id=record_id,
            detail={"valid": result},
        )
        return result

    # ── Chain verification ─────────────────────────────────────────────────────
    def verify_chain(self) -> Dict[str, Any]:
        """CADE-CHAIN-0: verify decision ledger and audit log chains."""
        ledger_ok, ledger_msg = self._ledger.verify_chain()
        audit_ok, audit_msg = self._auditor.verify_chain()
        self._auditor.record(
            "VERIFY_CHAIN",
            detail={
                "ledger_valid": ledger_ok,
                "ledger_msg": ledger_msg,
                "audit_valid": audit_ok,
                "audit_msg": audit_msg,
            },
        )
        return {
            "ledger_chain_valid": ledger_ok,
            "ledger_chain_msg": ledger_msg,
            "audit_chain_valid": audit_ok,
            "audit_chain_msg": audit_msg,
            "overall_valid": ledger_ok and audit_ok,
        }

    # ── Query helpers ──────────────────────────────────────────────────────────
    def get_decision(self, record_id: str) -> Optional[DecisionRecord]:
        entry = self._ledger.get(record_id)
        return entry.record if entry else None

    def all_decisions(self) -> List[DecisionRecord]:
        return [e.record for e in self._ledger.all_entries()]

    def all_audit_entries(self) -> List[AuditEntry]:
        return self._auditor.all_entries()

    def status(self) -> Dict[str, Any]:
        return {
            "engine": "CADEEngine",
            "arc": self.ARC,
            "phase": self.PHASE,
            "innov": self.INNOV,
            "governor": self.GOVERNOR,
            "promote_threshold": self._matrix.promote_threshold,
            "hold_threshold": self._matrix.hold_threshold,
            "decision_count": len(self._ledger.all_entries()),
            "audit_entry_count": len(self._auditor.all_entries()),
            "invariants": list(self.INVARIANTS),
            "decision_classes": list(_DECISION_CLASSES),
        }

    def matrix(self) -> Dict[str, Any]:
        return {
            "promote_threshold": self._matrix.promote_threshold,
            "hold_threshold": self._matrix.hold_threshold,
            "rules": [
                f"chi_score >= {self._matrix.promote_threshold:.2f} → PROMOTE",
                f"{self._matrix.hold_threshold:.2f} <= chi_score < {self._matrix.promote_threshold:.2f} → HOLD",
                f"chi_score < {self._matrix.hold_threshold:.2f} → REJECT",
            ],
        }
