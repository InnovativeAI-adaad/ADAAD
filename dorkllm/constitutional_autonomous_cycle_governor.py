# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/constitutional_autonomous_cycle_governor.py
Phase 232 · INNOV-137 · CACG — Constitutional Autonomous Cycle Governor
World-first Arc III ACI governance capstone: orchestrates the full ACI
pipeline lifecycle — CASL → CADE → CAPE/CAVE → CAOE → CALI → CACP →
CAMS — enforcing timeout contracts, detecting stalls, escalating to
HUMAN-0 on constitutional violations, and sealing every cycle into an
HMAC-chained immutable governance ledger.

Author  : DEVADAAD · InnovativeAI LLC
Governor: DUSTIN L REID

Arc III — Autonomous Constitutional Intelligence (ACI) · Module 08
Governance Capstone

CACG closes the Arc III outer loop: while CACP proves per-cycle
convergence and CAMS monitors live CHI health, CACG governs the
*cycle lifecycle itself* — starting cycles, enforcing stage-level
timeouts, detecting stalls, issuing HUMAN-0 escalations for any
constitutional breach, and publishing a sealed governance proof at
cycle close that binds every stage receipt into a single
HMAC-SHA-256 attestation.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ── Hard-class invariant identifiers (10) ─────────────────────────────────────
# CACG-CHAIN-0   : CycleGovernanceLedger HMAC-SHA-256 chained; chain verified
#                  before every append
# CACG-APPEND-0  : CycleGovernanceLedger is append-only; sealed records cannot
#                  be removed or mutated
# CACG-STAGES-0  : Exactly 8 ACI pipeline stages governed (CASL/CADE/CAPE/
#                  CAVE/CAOE/CALI/CACP/CAMS); unrecognised stage raises StageError
# CACG-TIMEOUT-0 : Every stage carries a positive timeout; stage completion after
#                  deadline raises TimeoutViolation; zero/negative timeout raises
#                  ConfigError at registration
# CACG-STALL-0   : A cycle with any stage not completed within its timeout is
#                  classified STALLED; a STALLED cycle blocks promotion
# CACG-HUMAN0-0  : Every STALLED or VIOLATED cycle issues a mandatory HUMAN-0
#                  escalation; escalation requires a non-empty HUMAN-0 identity
# CACG-IMMUT-0   : Sealed CycleGovernanceRecords raise ImmutabilityViolation on
#                  any write attempt after sealing
# CACG-DETERM-0  : Cycle outcome classification is deterministic given stage
#                  receipts and timeout thresholds; no RNG
# CACG-AUDIT-0   : Every CACG operation sealed into a parallel HMAC-chained
#                  audit log
# CACG-PROOF-0   : Every sealed CycleGovernanceRecord carries an HMAC-SHA-256
#                  proof binding all stage receipts

_HMAC_SECRET = os.environ.get(
    "CACG_HMAC_SECRET",
    "cacg-hmac-secret-DUSTIN-L-REID-v10-ArcIII-govcapstone",
).encode()

# CACG-STAGES-0: canonical ACI pipeline stage order
ACI_STAGES: Tuple[str, ...] = (
    "CASL", "CADE", "CAPE", "CAVE", "CAOE", "CALI", "CACP", "CAMS",
)
_STAGE_SET = frozenset(ACI_STAGES)
_STAGE_COUNT = len(ACI_STAGES)
if _STAGE_COUNT != 8:
    raise RuntimeError(
        f"CACG-STAGES-0 VIOLATION: expected exactly 8 ACI pipeline stages, "
        f"found {_STAGE_COUNT}"
    )

# CACG-TIMEOUT-0: default stage timeout seconds (can be overridden per instance)
DEFAULT_STAGE_TIMEOUTS: Dict[str, float] = {
    "CASL": 30.0,
    "CADE": 15.0,
    "CAPE": 60.0,
    "CAVE": 60.0,
    "CAOE": 30.0,
    "CALI": 20.0,
    "CACP": 20.0,
    "CAMS": 10.0,
}


def _hmac_digest(payload: str, prev: str = "") -> str:
    return hmac.new(
        _HMAC_SECRET,
        f"{prev}|{payload}".encode(),
        hashlib.sha256,
    ).hexdigest()


# ── Exceptions ────────────────────────────────────────────────────────────────

class CACGViolation(RuntimeError):
    """Base Hard-class invariant violation for CACG."""


class ChainBreakError(CACGViolation):
    """CACG-CHAIN-0: CycleGovernanceLedger HMAC chain broken."""


class AppendViolation(CACGViolation):
    """CACG-APPEND-0: Attempted mutation/deletion of immutable ledger."""


class StageError(CACGViolation):
    """CACG-STAGES-0: Unrecognised ACI pipeline stage."""


class TimeoutViolation(CACGViolation):
    """CACG-TIMEOUT-0: Stage completed after its constitutional deadline."""


class ConfigError(CACGViolation):
    """CACG-TIMEOUT-0: Invalid timeout configuration (zero or negative)."""


class StallError(CACGViolation):
    """CACG-STALL-0: Cycle stall detected — HUMAN-0 escalation required."""


class HUMAN0EscalationError(CACGViolation):
    """CACG-HUMAN0-0: Escalation requires non-empty HUMAN-0 identity."""


class ImmutabilityViolation(CACGViolation):
    """CACG-IMMUT-0: Write attempt on sealed CycleGovernanceRecord."""


class ProofError(CACGViolation):
    """CACG-PROOF-0: CycleGovernanceRecord HMAC proof binding invalid."""


# ── Enumerations ──────────────────────────────────────────────────────────────

class CycleState(str, Enum):
    ACTIVE    = "ACTIVE"
    COMPLETED = "COMPLETED"
    STALLED   = "STALLED"
    VIOLATED  = "VIOLATED"
    ESCALATED = "ESCALATED"


class StageOutcome(str, Enum):
    PENDING   = "PENDING"
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"


# ── Data records ──────────────────────────────────────────────────────────────

@dataclass
class StageReceipt:
    """Immutable record of a single pipeline stage completion."""
    stage: str
    outcome: StageOutcome
    started_at: float
    completed_at: float
    elapsed_seconds: float
    timed_out: bool
    payload: Dict[str, Any] = field(default_factory=dict)
    receipt_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "stage": self.stage,
            "outcome": self.outcome.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": self.elapsed_seconds,
            "timed_out": self.timed_out,
            "payload": self.payload,
        }


@dataclass
class CycleGovernanceRecord:
    """Sealed governance record for one ACI pipeline cycle."""
    cycle_id: str
    state: CycleState
    started_at: float
    closed_at: float
    stage_receipts: List[StageReceipt]
    stalled: bool
    violated: bool
    escalation_id: Optional[str]
    escalated_by: Optional[str]
    proof_hmac: str
    ledger_index: int
    chain_digest: str

    _sealed: bool = field(default=False, repr=False)

    def seal(self) -> None:
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False) and name != "_sealed":
            raise ImmutabilityViolation(
                f"CACG-IMMUT-0: CycleGovernanceRecord {self.cycle_id} is sealed."
            )
        super().__setattr__(name, value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "state": self.state.value,
            "started_at": self.started_at,
            "closed_at": self.closed_at,
            "stage_receipts": [r.to_dict() for r in self.stage_receipts],
            "stalled": self.stalled,
            "violated": self.violated,
            "escalation_id": self.escalation_id,
            "escalated_by": self.escalated_by,
            "proof_hmac": self.proof_hmac,
            "ledger_index": self.ledger_index,
            "chain_digest": self.chain_digest,
        }


@dataclass
class EscalationRecord:
    """HUMAN-0 escalation for a STALLED or VIOLATED cycle."""
    escalation_id: str
    cycle_id: str
    reason: str
    escalated_by: str
    issued_at: float
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "cycle_id": self.cycle_id,
            "reason": self.reason,
            "escalated_by": self.escalated_by,
            "issued_at": self.issued_at,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
        }


@dataclass
class AuditEvent:
    """CACG-AUDIT-0: one audit log entry."""
    event_id: str
    operation: str
    cycle_id: Optional[str]
    detail: Dict[str, Any]
    timestamp: float
    chain_digest: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "operation": self.operation,
            "cycle_id": self.cycle_id,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "chain_digest": self.chain_digest,
        }


# ── Subsystem: CycleGovernanceLedger ─────────────────────────────────────────

class CycleGovernanceLedger:
    """
    CACG-CHAIN-0 / CACG-APPEND-0 / CACG-PROOF-0
    Append-only HMAC-SHA-256-chained ledger of sealed CycleGovernanceRecords.
    """

    def __init__(self) -> None:
        self._records: List[CycleGovernanceRecord] = []
        self._chain_tip: str = _hmac_digest("GENESIS")

    def _verify_chain(self) -> None:
        """CACG-CHAIN-0: Re-derive chain; raise ChainBreakError on mismatch."""
        tip = _hmac_digest("GENESIS")
        for rec in self._records:
            expected = _hmac_digest(rec.proof_hmac, tip)
            if rec.chain_digest != expected:
                raise ChainBreakError(
                    f"CACG-CHAIN-0: chain break at ledger index {rec.ledger_index}"
                )
            tip = expected
        if tip != self._chain_tip:
            raise ChainBreakError("CACG-CHAIN-0: chain tip mismatch.")

    def append(self, record: CycleGovernanceRecord) -> None:
        """Verify chain integrity then append; CACG-APPEND-0 enforced."""
        self._verify_chain()
        new_digest = _hmac_digest(record.proof_hmac, self._chain_tip)
        object.__setattr__(record, "chain_digest", new_digest)
        record.seal()
        self._records.append(record)
        self._chain_tip = new_digest

    def verify(self) -> bool:
        """Return True iff full chain valid; raise ChainBreakError otherwise."""
        self._verify_chain()
        return True

    @property
    def records(self) -> List[CycleGovernanceRecord]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)


# ── Subsystem: TimeoutEnforcer ────────────────────────────────────────────────

class TimeoutEnforcer:
    """
    CACG-TIMEOUT-0 / CACG-STALL-0 / CACG-DETERM-0
    Validates timeout config, stamps stage start times, and classifies
    completions as on-time or timed-out deterministically.
    """

    def __init__(self, timeouts: Optional[Dict[str, float]] = None) -> None:
        resolved = timeouts or DEFAULT_STAGE_TIMEOUTS
        for stage, t in resolved.items():
            if stage not in _STAGE_SET:
                raise StageError(
                    f"CACG-STAGES-0: unknown stage in timeout config: {stage!r}"
                )
            if t <= 0:
                raise ConfigError(
                    f"CACG-TIMEOUT-0: timeout for stage {stage!r} must be positive; got {t}"
                )
        self._timeouts: Dict[str, float] = dict(resolved)

    def get_timeout(self, stage: str) -> float:
        if stage not in _STAGE_SET:
            raise StageError(f"CACG-STAGES-0: unknown stage {stage!r}")
        return self._timeouts.get(stage, DEFAULT_STAGE_TIMEOUTS[stage])

    def evaluate(self, stage: str, started_at: float, completed_at: float) -> StageReceipt:
        """CACG-DETERM-0: deterministically classify stage completion."""
        if stage not in _STAGE_SET:
            raise StageError(f"CACG-STAGES-0: unknown stage {stage!r}")
        timeout = self.get_timeout(stage)
        elapsed = completed_at - started_at
        timed_out = elapsed > timeout
        outcome = StageOutcome.TIMED_OUT if timed_out else StageOutcome.COMPLETED
        return StageReceipt(
            stage=stage,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            elapsed_seconds=elapsed,
            timed_out=timed_out,
        )


# ── Subsystem: EscalationEngine ───────────────────────────────────────────────

class EscalationEngine:
    """
    CACG-HUMAN0-0
    Issues and acknowledges HUMAN-0 escalations for STALLED/VIOLATED cycles.
    """

    def __init__(self) -> None:
        self._escalations: Dict[str, EscalationRecord] = {}

    def escalate(self, cycle_id: str, reason: str, escalated_by: str) -> EscalationRecord:
        """CACG-HUMAN0-0: raise escalation; escalated_by must be non-empty."""
        if not escalated_by or not escalated_by.strip():
            raise HUMAN0EscalationError(
                "CACG-HUMAN0-0: escalated_by (HUMAN-0 identity) must be non-empty."
            )
        esc = EscalationRecord(
            escalation_id=str(uuid.uuid4()),
            cycle_id=cycle_id,
            reason=reason,
            escalated_by=escalated_by,
            issued_at=time.time(),
        )
        self._escalations[esc.escalation_id] = esc
        return esc

    def acknowledge(self, escalation_id: str, acknowledged_by: str) -> EscalationRecord:
        """CACG-HUMAN0-0: acknowledge escalation; acknowledged_by must be non-empty."""
        if escalation_id not in self._escalations:
            raise KeyError(f"Escalation {escalation_id!r} not found.")
        if not acknowledged_by or not acknowledged_by.strip():
            raise HUMAN0EscalationError(
                "CACG-HUMAN0-0: acknowledged_by must be non-empty HUMAN-0 identity."
            )
        esc = self._escalations[escalation_id]
        if esc.acknowledged:
            raise ImmutabilityViolation(
                f"CACG-IMMUT-0: Escalation {escalation_id} already acknowledged."
            )
        esc.acknowledged = True
        esc.acknowledged_by = acknowledged_by
        esc.acknowledged_at = time.time()
        return esc

    def get(self, escalation_id: str) -> Optional[EscalationRecord]:
        return self._escalations.get(escalation_id)

    def all_escalations(self) -> List[EscalationRecord]:
        return list(self._escalations.values())

    def open_escalations(self) -> List[EscalationRecord]:
        return [e for e in self._escalations.values() if not e.acknowledged]


# ── Subsystem: CACGAuditor ────────────────────────────────────────────────────

class CACGAuditor:
    """
    CACG-AUDIT-0
    Parallel HMAC-chained audit log for every CACG operation.
    """

    def __init__(self) -> None:
        self._log: List[AuditEvent] = []
        self._tip: str = _hmac_digest("AUDIT-GENESIS")

    def record(
        self,
        operation: str,
        cycle_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        payload = f"{operation}|{cycle_id}|{time.time()}"
        new_digest = _hmac_digest(payload, self._tip)
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            operation=operation,
            cycle_id=cycle_id,
            detail=detail or {},
            timestamp=time.time(),
            chain_digest=new_digest,
        )
        self._log.append(event)
        self._tip = new_digest
        return event

    @property
    def events(self) -> List[AuditEvent]:
        return list(self._log)


# ── Facade: CACGEngine ────────────────────────────────────────────────────────

class CACGEngine:
    """
    Constitutional Autonomous Cycle Governor — Arc III governance capstone.

    Orchestrates the ACI pipeline lifecycle:
      start_cycle → register_stage_completion (x N) → close_cycle
    Enforces timeout contracts, stall detection, HUMAN-0 escalation,
    and sealed HMAC-chained governance proofs.
    """

    def __init__(self, timeouts: Optional[Dict[str, float]] = None) -> None:
        self._enforcer = TimeoutEnforcer(timeouts)
        self._ledger = CycleGovernanceLedger()
        self._escalation = EscalationEngine()
        self._auditor = CACGAuditor()
        # Active cycles: cycle_id → {started_at, receipts, state}
        self._active: Dict[str, Dict[str, Any]] = {}

    # ── Cycle lifecycle ───────────────────────────────────────────────────────

    def start_cycle(self) -> str:
        """Open a new ACI governance cycle; return cycle_id."""
        cycle_id = str(uuid.uuid4())
        self._active[cycle_id] = {
            "started_at": time.time(),
            "receipts": [],
            "state": CycleState.ACTIVE,
        }
        self._auditor.record("start_cycle", cycle_id, {"cycle_id": cycle_id})
        return cycle_id

    def register_stage_completion(
        self,
        cycle_id: str,
        stage: str,
        started_at: float,
        completed_at: float,
        payload: Optional[Dict[str, Any]] = None,
    ) -> StageReceipt:
        """
        CACG-TIMEOUT-0 / CACG-STAGES-0
        Register a stage receipt; raises TimeoutViolation if timed out.
        """
        if stage not in _STAGE_SET:
            raise StageError(f"CACG-STAGES-0: unrecognised stage {stage!r}")
        if cycle_id not in self._active:
            raise KeyError(f"No active cycle {cycle_id!r}")
        receipt = self._enforcer.evaluate(stage, started_at, completed_at)
        if payload:
            receipt.payload = payload
        if receipt.timed_out:
            self._active[cycle_id]["state"] = CycleState.VIOLATED
            self._auditor.record(
                "stage_timeout", cycle_id,
                {"stage": stage, "elapsed": receipt.elapsed_seconds}
            )
            raise TimeoutViolation(
                f"CACG-TIMEOUT-0: stage {stage!r} exceeded timeout "
                f"({receipt.elapsed_seconds:.2f}s > "
                f"{self._enforcer.get_timeout(stage)}s) in cycle {cycle_id}"
            )
        self._active[cycle_id]["receipts"].append(receipt)
        self._auditor.record(
            "stage_completed", cycle_id,
            {"stage": stage, "elapsed": receipt.elapsed_seconds}
        )
        return receipt

    def close_cycle(
        self,
        cycle_id: str,
        human0_identity: Optional[str] = None,
    ) -> CycleGovernanceRecord:
        """
        CACG-STALL-0 / CACG-HUMAN0-0 / CACG-CHAIN-0 / CACG-PROOF-0
        Close active cycle, classify outcome, issue escalation if needed,
        seal into ledger.
        """
        if cycle_id not in self._active:
            raise KeyError(f"No active cycle {cycle_id!r}")

        ctx = self._active.pop(cycle_id)
        receipts: List[StageReceipt] = ctx["receipts"]
        current_state: CycleState = ctx["state"]
        now = time.time()

        # CACG-STALL-0: check if any required stage is missing
        completed_stages = {r.stage for r in receipts}
        missing = _STAGE_SET - completed_stages
        stalled = bool(missing)
        violated = current_state in (CycleState.VIOLATED,)

        # CACG-DETERM-0: final state classification
        if violated:
            final_state = CycleState.VIOLATED
        elif stalled:
            final_state = CycleState.STALLED
        else:
            final_state = CycleState.COMPLETED

        # CACG-HUMAN0-0: escalate on STALLED or VIOLATED
        escalation_id: Optional[str] = None
        escalated_by: Optional[str] = None
        if final_state in (CycleState.STALLED, CycleState.VIOLATED):
            identity = human0_identity or "HUMAN-0-REQUIRED"
            if not human0_identity or not human0_identity.strip():
                raise HUMAN0EscalationError(
                    "CACG-HUMAN0-0: human0_identity required to escalate "
                    f"a {final_state.value} cycle."
                )
            reason = (
                f"Cycle {cycle_id} {final_state.value}: "
                + (f"missing stages {sorted(missing)}" if stalled else "stage timeout")
            )
            esc = self._escalation.escalate(cycle_id, reason, identity)
            escalation_id = esc.escalation_id
            escalated_by = identity
            final_state = CycleState.ESCALATED

        # CACG-PROOF-0: HMAC proof binding all stage receipts
        receipt_blob = "|".join(
            f"{r.stage}:{r.elapsed_seconds:.4f}:{r.timed_out}"
            for r in sorted(receipts, key=lambda r: r.stage)
        )
        proof_hmac = _hmac_digest(f"{cycle_id}|{receipt_blob}")

        record = CycleGovernanceRecord(
            cycle_id=cycle_id,
            state=final_state,
            started_at=ctx["started_at"],
            closed_at=now,
            stage_receipts=receipts,
            stalled=stalled,
            violated=violated,
            escalation_id=escalation_id,
            escalated_by=escalated_by,
            proof_hmac=proof_hmac,
            ledger_index=len(self._ledger),
            chain_digest="",  # set by ledger.append
        )

        self._ledger.append(record)
        self._auditor.record(
            "close_cycle", cycle_id,
            {"state": final_state.value, "stalled": stalled, "violated": violated}
        )
        return record

    # ── Escalation passthrough ────────────────────────────────────────────────

    def acknowledge_escalation(
        self, escalation_id: str, acknowledged_by: str
    ) -> EscalationRecord:
        """CACG-HUMAN0-0: acknowledge a HUMAN-0 escalation."""
        result = self._escalation.acknowledge(escalation_id, acknowledged_by)
        self._auditor.record(
            "acknowledge_escalation", None,
            {"escalation_id": escalation_id, "by": acknowledged_by}
        )
        return result

    def get_escalation(self, escalation_id: str) -> Optional[EscalationRecord]:
        return self._escalation.get(escalation_id)

    # ── Ledger / audit passthrough ────────────────────────────────────────────

    def verify_chain(self) -> bool:
        """CACG-CHAIN-0: full ledger chain verification."""
        result = self._ledger.verify()
        self._auditor.record("verify_chain", None, {"valid": result})
        return result

    def get_ledger(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._ledger.records]

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._auditor.events]

    def get_active_cycles(self) -> List[str]:
        return list(self._active.keys())

    def get_record(self, cycle_id: str) -> Optional[Dict[str, Any]]:
        for rec in self._ledger.records:
            if rec.cycle_id == cycle_id:
                return rec.to_dict()
        return None

    def status(self) -> Dict[str, Any]:
        return {
            "module": "CACG",
            "innov": "INNOV-137",
            "phase": 232,
            "arc": "III",
            "description": "Constitutional Autonomous Cycle Governor",
            "active_cycles": len(self._active),
            "sealed_cycles": len(self._ledger),
            "open_escalations": len(self._escalation.open_escalations()),
            "audit_events": len(self._auditor.events),
            "invariants": [
                "CACG-CHAIN-0", "CACG-APPEND-0", "CACG-STAGES-0",
                "CACG-TIMEOUT-0", "CACG-STALL-0", "CACG-HUMAN0-0",
                "CACG-IMMUT-0", "CACG-DETERM-0", "CACG-AUDIT-0",
                "CACG-PROOF-0",
            ],
        }
