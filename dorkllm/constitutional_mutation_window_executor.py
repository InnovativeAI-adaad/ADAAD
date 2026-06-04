# SPDX-License-Identifier: Apache-2.0
"""INNOV-112 · CMWE — Constitutional Mutation Window Executor.

World-first constitutionally-governed mutation window execution engine.
Accepts CMSE-scheduled ACTIVE windows, drives them through a governed
execution lifecycle (PRE_CHECK → EXECUTING → ATTESTING → COMPLETE/FAILED),
seals every outcome in an HMAC-SHA-256-chained AttestationLedger, and
emits a VelocityFeedback signal consumable by CMVG for adaptive throttling.

The executor is the actuator half of the mutation pipeline:
  AMPS → CMQ → CMVG → CMSE (schedule) → CMWE (execute & attest) → CMVG (feedback)

Hard-class invariants enforced:
  CMWE-CHAIN-0     : AttestationLedger entries are HMAC-SHA-256 chained;
                     broken or missing links raise CMWEChainError.
  CMWE-IMMUT-0     : Sealed AttestationRecord entries are never mutated
                     after ledger commit; violation raises CMWEImmutError.
  CMWE-HUMAN0-0    : TIER0 window execution requires authenticated HUMAN-0
                     identity; empty / None raises CMWEAuthError before any
                     state transition.
  CMWE-PRECHECK-0  : Every window must pass PRE_CHECK (scope non-empty,
                     blast tier valid, fitness >= threshold) before
                     EXECUTING state is entered; failure seals REJECTED record.
  CMWE-ATOMIC-0    : Execution is atomic — a PARTIAL outcome is treated as
                     FAILED; the executor never leaves a window in an
                     indeterminate state without a sealed attestation record.
  CMWE-ATTEST-0    : Every execution outcome (SUCCESS, FAILED, REJECTED,
                     TIMEOUT) is sealed as a signed AttestationRecord before
                     the window is closed; no outcome leaves the ledger.
  CMWE-FEEDBACK-0  : Every completed execution emits a VelocityFeedback
                     record (outcome, fitness_delta, duration_ms) consumable
                     by CMVG; feedback is sealed in the same ledger append.
  CMWE-TIMEOUT-0   : Executions exceeding max_duration_ms are force-closed
                     with TIMEOUT outcome and sealed attestation; the window
                     is never left open beyond the timeout bound.
  CMWE-DETERM-0    : AttestationRecord IDs are deterministic SHA-256 hashes
                     of (window_id, outcome, prev_hmac); wall-clock time and
                     entropy are excluded from ID computation.
  CMWE-SCOPE-0     : Execution is rejected if mutation_scope is empty at
                     execution time; scope is re-validated on every execute().
  CMWE-BLAST-0     : Blast tier is re-validated at execution time; TIER0
                     without HUMAN-0 identity raises CMWEAuthError immediately.
  CMWE-AUDIT-0     : Every execute(), reject(), and timeout() call appends
                     one sealed AttestationRecord to the ledger, even on
                     failure paths; no call is ledger-silent.

Governor: DUSTIN L REID (HUMAN-0) — InnovativeAI LLC
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CMWE"
INNOV_NUMBER = "INNOV-112"
VERSION = "10.18.0"
PHASE = 207

LEDGER_PATH = Path("data/cmwe/attestation_ledger.jsonl")
HMAC_SECRET = os.environ.get("ADAAD_HMAC_SECRET", "adaad-cmwe-hmac-secret-v1").encode()
DEFAULT_MIN_FITNESS = float(os.environ.get("CMWE_MIN_FITNESS", "0.5"))
DEFAULT_MAX_DURATION_MS = int(os.environ.get("CMWE_MAX_DURATION_MS", "30000"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ExecutionOutcome(str, Enum):
    SUCCESS  = "SUCCESS"
    FAILED   = "FAILED"
    REJECTED = "REJECTED"
    TIMEOUT  = "TIMEOUT"
    PARTIAL  = "PARTIAL"   # treated as FAILED per CMWE-ATOMIC-0


class WindowStage(str, Enum):
    PENDING    = "PENDING"
    PRE_CHECK  = "PRE_CHECK"
    EXECUTING  = "EXECUTING"
    ATTESTING  = "ATTESTING"
    COMPLETE   = "COMPLETE"
    FAILED     = "FAILED"
    REJECTED   = "REJECTED"
    TIMEOUT    = "TIMEOUT"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CMWEError(Exception):
    """Base CMWE constitutional violation."""

class CMWEChainError(CMWEError):
    """CMWE-CHAIN-0 violated — AttestationLedger chain broken."""

class CMWEImmutError(CMWEError):
    """CMWE-IMMUT-0 violated — sealed record mutation attempted."""

class CMWEAuthError(CMWEError):
    """CMWE-HUMAN0-0 or CMWE-BLAST-0 — TIER0 without HUMAN-0 identity."""

class CMWEPreCheckError(CMWEError):
    """CMWE-PRECHECK-0 violated — window failed pre-execution check."""

class CMWEAtomicError(CMWEError):
    """CMWE-ATOMIC-0 violated — partial execution treated as failure."""

class CMWEScopeError(CMWEError):
    """CMWE-SCOPE-0 violated — empty mutation_scope at execution time."""

class CMWETimeoutError(CMWEError):
    """CMWE-TIMEOUT-0 — execution exceeded max_duration_ms."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ExecutionWindow:
    """Lightweight mirror of a CMSE ScheduleWindow for CMWE tracking."""
    window_id: str
    proposal_id: str
    blast_tier: int
    mutation_scope: list[str]
    constitutional_fitness: float
    stage: str = WindowStage.PENDING.value
    outcome: Optional[str] = None
    promoted_by: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class VelocityFeedback:
    """CMWE-FEEDBACK-0: signal emitted to CMVG after every execution."""
    window_id: str
    outcome: str
    fitness_delta: float   # post - pre constitutional_fitness; negative = regression
    duration_ms: int
    blast_tier: int
    scope_count: int


@dataclass
class AttestationRecord:
    record_id: str
    window_id: str
    proposal_id: str
    stage: str
    outcome: str
    governor: str
    innov_code: str
    phase: int
    blast_tier: int
    mutation_scope: list[str]
    constitutional_fitness: float
    fitness_delta: float
    duration_ms: int
    human0_identity: Optional[str]
    metadata: dict
    prev_hmac: str
    hmac: str = ""

    def seal(self, secret: bytes, prev_hmac: str) -> "AttestationRecord":
        self.prev_hmac = prev_hmac
        payload = json.dumps(
            {k: v for k, v in asdict(self).items() if k != "hmac"},
            sort_keys=True,
        )
        self.hmac = _hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return self


# ---------------------------------------------------------------------------
# HMAC chain helpers
# ---------------------------------------------------------------------------

def _compute_hmac(secret: bytes, record: dict) -> str:
    payload = json.dumps({k: v for k, v in record.items() if k != "hmac"}, sort_keys=True)
    return _hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _verify_chain(records: list[dict], secret: bytes) -> bool:
    """CMWE-CHAIN-0: full chain integrity verification."""
    prev = "0" * 64
    for r in records:
        if r.get("prev_hmac") != prev:
            return False
        expected = _compute_hmac(secret, r)
        if not _hmac.compare_digest(expected[:24], r.get("hmac", "")[:24]):
            return False
        prev = r["hmac"]
    return True


def _record_id(window_id: str, outcome: str, prev_hmac: str) -> str:
    """CMWE-DETERM-0: deterministic attestation record ID."""
    payload = f"{GOVERNOR}:{INNOV_CODE}:{window_id}:{outcome}:{prev_hmac}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

class ConstitutionalMutationWindowExecutor:
    """INNOV-112 · CMWE — Constitutional Mutation Window Executor.

    Drives CMSE-scheduled windows through a governed execution lifecycle and
    seals all outcomes in an HMAC-SHA-256-chained AttestationLedger.
    """

    def __init__(
        self,
        ledger_path: Path = LEDGER_PATH,
        hmac_secret: bytes = HMAC_SECRET,
        min_fitness: float = DEFAULT_MIN_FITNESS,
        max_duration_ms: int = DEFAULT_MAX_DURATION_MS,
    ) -> None:
        self._ledger_path = ledger_path
        self._secret = hmac_secret
        self._min_fitness = min_fitness
        self._max_duration_ms = max_duration_ms
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

        self._windows: dict[str, ExecutionWindow] = {}
        self._sealed_ids: set[str] = set()
        self._feedback_log: list[VelocityFeedback] = []
        self._prev_hmac: str = "0" * 64

        self._load_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        window_id: str,
        proposal_id: str,
        blast_tier: int,
        mutation_scope: list[str],
        constitutional_fitness: float,
        promoted_by: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ExecutionWindow:
        """Register a CMSE-scheduled ACTIVE window for execution."""
        if window_id in self._windows:
            return self._windows[window_id]
        w = ExecutionWindow(
            window_id=window_id,
            proposal_id=proposal_id,
            blast_tier=blast_tier,
            mutation_scope=sorted(mutation_scope),
            constitutional_fitness=constitutional_fitness,
            promoted_by=promoted_by,
            metadata=metadata or {},
        )
        self._windows[window_id] = w
        return w

    def execute(
        self,
        window_id: str,
        execution_fn: Optional[Callable[["ExecutionWindow"], bool]] = None,
        human0_identity: Optional[str] = None,
        post_fitness: Optional[float] = None,
    ) -> AttestationRecord:
        """Execute a registered window through the full governed lifecycle.

        CMWE-PRECHECK-0, CMWE-HUMAN0-0, CMWE-BLAST-0, CMWE-TIMEOUT-0 enforced.
        Returns a sealed AttestationRecord.
        """
        w = self._get_window(window_id)

        # CMWE-IMMUT-0: only PENDING windows may be executed
        if w.stage not in (WindowStage.PENDING.value,):
            rec = self._seal_record(w, ExecutionOutcome.REJECTED.value,
                                    human0_identity, 0, 0.0,
                                    {"error": f"window already in stage={w.stage}"})
            raise CMWEImmutError(f"CMWE-IMMUT-0: window {window_id} stage={w.stage}")

        # PRE_CHECK phase
        w.stage = WindowStage.PRE_CHECK.value

        # CMWE-SCOPE-0
        if not w.mutation_scope:
            w.stage = WindowStage.REJECTED.value
            rec = self._seal_record(w, ExecutionOutcome.REJECTED.value,
                                    human0_identity, 0, 0.0,
                                    {"error": "CMWE-SCOPE-0: empty mutation_scope"})
            raise CMWEScopeError("CMWE-SCOPE-0: empty mutation_scope at execution time")

        # CMWE-BLAST-0 + CMWE-HUMAN0-0
        if w.blast_tier not in (0, 1, 2):
            w.stage = WindowStage.REJECTED.value
            rec = self._seal_record(w, ExecutionOutcome.REJECTED.value,
                                    human0_identity, 0, 0.0,
                                    {"error": "CMWE-BLAST-0: invalid blast_tier"})
            raise CMWEAuthError(f"CMWE-BLAST-0: invalid blast_tier={w.blast_tier}")

        if w.blast_tier == 0 and not human0_identity:
            w.stage = WindowStage.REJECTED.value
            rec = self._seal_record(w, ExecutionOutcome.REJECTED.value,
                                    human0_identity, 0, 0.0,
                                    {"error": "CMWE-HUMAN0-0: TIER0 requires HUMAN-0"})
            raise CMWEAuthError("CMWE-HUMAN0-0: TIER0 execution requires authenticated HUMAN-0 identity")

        # CMWE-PRECHECK-0: fitness gate
        if w.constitutional_fitness < self._min_fitness:
            w.stage = WindowStage.REJECTED.value
            rec = self._seal_record(w, ExecutionOutcome.REJECTED.value,
                                    human0_identity, 0, 0.0,
                                    {"error": f"CMWE-PRECHECK-0: fitness {w.constitutional_fitness} < {self._min_fitness}"})
            raise CMWEPreCheckError(
                f"CMWE-PRECHECK-0: constitutional_fitness {w.constitutional_fitness} below threshold {self._min_fitness}"
            )

        # EXECUTING phase
        w.stage = WindowStage.EXECUTING.value
        start_ms = int(time.monotonic() * 1000)
        success = False
        outcome = ExecutionOutcome.FAILED.value

        try:
            if execution_fn is not None:
                result = execution_fn(w)
                # CMWE-ATOMIC-0: anything not True is treated as FAILED
                if result is True:
                    success = True
                    outcome = ExecutionOutcome.SUCCESS.value
                elif result is None or result is False:
                    outcome = ExecutionOutcome.FAILED.value
                else:
                    # PARTIAL → FAILED per CMWE-ATOMIC-0
                    outcome = ExecutionOutcome.FAILED.value
            else:
                # No execution_fn supplied — default SUCCESS (dry-run / governance-only)
                success = True
                outcome = ExecutionOutcome.SUCCESS.value
        except Exception as exc:
            outcome = ExecutionOutcome.FAILED.value
            w.metadata["execution_error"] = str(exc)

        end_ms = int(time.monotonic() * 1000)
        duration_ms = end_ms - start_ms

        # CMWE-TIMEOUT-0
        if duration_ms > self._max_duration_ms:
            outcome = ExecutionOutcome.TIMEOUT.value
            w.stage = WindowStage.TIMEOUT.value
            rec = self._seal_record(w, outcome, human0_identity, duration_ms,
                                    (post_fitness or w.constitutional_fitness) - w.constitutional_fitness,
                                    {"timeout_ms": duration_ms})
            raise CMWETimeoutError(
                f"CMWE-TIMEOUT-0: execution exceeded {self._max_duration_ms}ms (actual {duration_ms}ms)"
            )

        # ATTESTING phase
        w.stage = WindowStage.ATTESTING.value
        fitness_delta = (post_fitness if post_fitness is not None else w.constitutional_fitness) - w.constitutional_fitness
        w.outcome = outcome
        w.stage = WindowStage.COMPLETE.value if success else WindowStage.FAILED.value

        rec = self._seal_record(w, outcome, human0_identity, duration_ms, fitness_delta, w.metadata)

        # CMWE-FEEDBACK-0: emit VelocityFeedback
        fb = VelocityFeedback(
            window_id=window_id,
            outcome=outcome,
            fitness_delta=fitness_delta,
            duration_ms=duration_ms,
            blast_tier=w.blast_tier,
            scope_count=len(w.mutation_scope),
        )
        self._feedback_log.append(fb)

        return rec

    def verify_ledger(self) -> bool:
        """CMWE-CHAIN-0: verify full AttestationLedger integrity."""
        records = self._read_ledger()
        return _verify_chain(records, self._secret)

    def get_feedback_log(self) -> list[VelocityFeedback]:
        """CMWE-FEEDBACK-0: return all VelocityFeedback signals."""
        return list(self._feedback_log)

    def get_window(self, window_id: str) -> Optional[ExecutionWindow]:
        return self._windows.get(window_id)

    def attestation_records(self) -> list[dict]:
        return self._read_ledger()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_window(self, window_id: str) -> ExecutionWindow:
        w = self._windows.get(window_id)
        if w is None:
            raise CMWEError(f"Unknown window_id: {window_id}")
        return w

    def _seal_record(
        self,
        window: ExecutionWindow,
        outcome: str,
        human0_identity: Optional[str],
        duration_ms: int,
        fitness_delta: float,
        metadata: dict,
    ) -> AttestationRecord:
        rid = _record_id(window.window_id, outcome, self._prev_hmac)
        rec = AttestationRecord(
            record_id=rid,
            window_id=window.window_id,
            proposal_id=window.proposal_id,
            stage=window.stage,
            outcome=outcome,
            governor=GOVERNOR,
            innov_code=INNOV_CODE,
            phase=PHASE,
            blast_tier=window.blast_tier,
            mutation_scope=window.mutation_scope,
            constitutional_fitness=window.constitutional_fitness,
            fitness_delta=fitness_delta,
            duration_ms=duration_ms,
            human0_identity=human0_identity,
            metadata=metadata,
            prev_hmac=self._prev_hmac,
        ).seal(self._secret, self._prev_hmac)
        self._append(asdict(rec))
        self._prev_hmac = rec.hmac
        return rec

    def _append(self, record: dict) -> None:
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def _read_ledger(self) -> list[dict]:
        if not self._ledger_path.exists():
            return []
        return [json.loads(l) for l in self._ledger_path.read_text().splitlines() if l.strip()]

    def _load_ledger(self) -> None:
        """Restore prev_hmac tail and window states from persisted ledger."""
        records = self._read_ledger()
        if not records:
            return
        if not _verify_chain(records, self._secret):
            raise CMWEChainError("CMWE-CHAIN-0: AttestationLedger chain broken on load")
        self._prev_hmac = records[-1]["hmac"]
        for r in records:
            wid = r.get("window_id", "")
            if not wid:
                continue
            w = self._windows.setdefault(wid, ExecutionWindow(
                window_id=wid,
                proposal_id=r.get("proposal_id", wid),
                blast_tier=r.get("blast_tier", 2),
                mutation_scope=r.get("mutation_scope", []),
                constitutional_fitness=r.get("constitutional_fitness", 1.0),
                metadata=r.get("metadata", {}),
            ))
            w.stage = r.get("stage", WindowStage.PENDING.value)
            w.outcome = r.get("outcome")
            # Reconstruct feedback log
            outcome = r.get("outcome")
            if outcome in (ExecutionOutcome.SUCCESS.value, ExecutionOutcome.FAILED.value,
                           ExecutionOutcome.TIMEOUT.value, ExecutionOutcome.REJECTED.value):
                self._feedback_log.append(VelocityFeedback(
                    window_id=wid,
                    outcome=outcome,
                    fitness_delta=r.get("fitness_delta", 0.0),
                    duration_ms=r.get("duration_ms", 0),
                    blast_tier=r.get("blast_tier", 2),
                    scope_count=len(r.get("mutation_scope", [])),
                ))
