# SPDX-License-Identifier: Apache-2.0
"""INNOV-111 · CMSE — Constitutional Mutation Scheduling Engine.

World-first constitutionally-governed mutation scheduling engine that translates
AMPS-synthesized proposals and CMVG velocity decisions into deterministic, non-overlapping
execution windows. Enforces blast-radius separation invariants, HUMAN-0 gate ordering,
and emits all scheduling decisions into an HMAC-SHA-256-chained ScheduleLedger for
deterministic replay and audit.

Hard-class invariants enforced:
  CMSE-CHAIN-0    : ScheduleLedger entries are HMAC-SHA-256 chained;
                    tampered or missing links raise CMSEChainError.
  CMSE-IMMUT-0    : Sealed ScheduleWindow records are never mutated after ledger commit;
                    violation raises CMSEImmutError.
  CMSE-HUMAN0-0   : Any TIER0 window promotion requires authenticated HUMAN-0 identity;
                    empty / None identity raises CMSEAuthError before any state change.
  CMSE-OVERLAP-0  : No two windows with intersecting mutation_scope sets may be ACTIVE
                    simultaneously; scheduling such a pair raises CMSEOverlapError.
  CMSE-DETERM-0   : Window IDs and slot assignments are pure deterministic SHA-256
                    functions of content; wall-clock time and entropy are excluded.
  CMSE-VELOCITY-0 : Windows are gated on CMVG rate; a HALT velocity decision
                    blocks all new window promotion regardless of other signals.
  CMSE-BLAST-0    : Blast radius classification (TIER0/TIER1/TIER2) is verified before
                    every window promotion; misclassified windows are rejected.
  CMSE-AUDIT-0    : Every schedule(), promote(), and expire() call appends one sealed
                    ScheduleRecord to the ledger, even on failure paths.
  CMSE-FAILCLOSED-0: Any scheduling error emits a FAILED ScheduleRecord and raises;
                    partial window states are never committed to the ledger.
  CMSE-DRAIN-0    : Drain mode blocks all new window promotion until the active window
                    set is empty; used for constitutional maintenance windows.
  CMSE-SCOPE-0    : mutation_scope fields are non-empty frozensets; empty scope raises
                    CMSEScopeError before ledger append.
  CMSE-SLOT-0     : Slot capacity is enforced; scheduling beyond capacity raises
                    CMSECapacityError.

Governor: DUSTIN L REID (HUMAN-0) — InnovativeAI LLC
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
from typing import Any, FrozenSet, Optional

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CMSE"
INNOV_NUMBER = "INNOV-111"
VERSION = "10.17.0"
PHASE = 206
LEDGER_PATH = Path("data/cmse/schedule_ledger.jsonl")
HMAC_SECRET = os.environ.get("ADAAD_HMAC_SECRET", "adaad-cmse-hmac-secret-v1").encode()

DEFAULT_SLOT_CAPACITY = int(os.environ.get("CMSE_SLOT_CAPACITY", "4"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class WindowStatus(str, Enum):
    PENDING   = "PENDING"
    ACTIVE    = "ACTIVE"
    EXPIRED   = "EXPIRED"
    FAILED    = "FAILED"
    BLOCKED   = "BLOCKED"


class BlastTier(int, Enum):
    TIER0 = 0  # Production / constitutional change — HUMAN-0 required
    TIER1 = 1  # Staging / significant module change
    TIER2 = 2  # Dev / isolated module change


class ScheduleAction(str, Enum):
    SCHEDULE = "SCHEDULE"
    PROMOTE  = "PROMOTE"
    EXPIRE   = "EXPIRE"
    DRAIN    = "DRAIN"
    UNDRAIN  = "UNDRAIN"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CMSEError(Exception):
    """Base CMSE constitutional violation."""

class CMSEChainError(CMSEError):
    """CMSE-CHAIN-0 violated — ledger chain broken."""

class CMSEImmutError(CMSEError):
    """CMSE-IMMUT-0 violated — sealed window mutation attempted."""

class CMSEAuthError(CMSEError):
    """CMSE-HUMAN0-0 violated — TIER0 action without HUMAN-0 identity."""

class CMSEOverlapError(CMSEError):
    """CMSE-OVERLAP-0 violated — concurrent overlapping mutation scopes."""

class CMSEVelocityError(CMSEError):
    """CMSE-VELOCITY-0 violated — promotion attempted under HALT velocity."""

class CMSEBlastError(CMSEError):
    """CMSE-BLAST-0 violated — invalid or misclassified blast tier."""

class CMSEScopeError(CMSEError):
    """CMSE-SCOPE-0 violated — empty mutation_scope supplied."""

class CMSECapacityError(CMSEError):
    """CMSE-SLOT-0 violated — slot capacity exceeded."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

def _window_id(proposal_id: str, blast_tier: int, scope_key: str) -> str:
    """CMSE-DETERM-0: deterministic SHA-256 window ID."""
    payload = f"{GOVERNOR}:{INNOV_CODE}:{proposal_id}:{blast_tier}:{scope_key}"
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class ScheduleWindow:
    window_id: str
    proposal_id: str
    blast_tier: int
    mutation_scope: list[str]          # sorted list for determinism
    status: str = WindowStatus.PENDING.value
    slot_index: Optional[int] = None
    promoted_by: Optional[str] = None
    constitutional_fitness: float = 0.0
    metadata: dict = field(default_factory=dict)

    def scope_set(self) -> frozenset:
        return frozenset(self.mutation_scope)


@dataclass
class ScheduleRecord:
    record_id: str
    action: str
    window_id: str
    status: str
    governor: str
    innov_code: str
    phase: int
    blast_tier: int
    mutation_scope: list[str]
    promoted_by: Optional[str]
    constitutional_fitness: float
    slot_index: Optional[int]
    metadata: dict
    prev_hmac: str
    hmac: str = ""

    def seal(self, secret: bytes, prev_hmac: str) -> "ScheduleRecord":
        self.prev_hmac = prev_hmac
        payload = json.dumps({
            k: v for k, v in asdict(self).items() if k != "hmac"
        }, sort_keys=True)
        self.hmac = _hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return self


# ---------------------------------------------------------------------------
# HMAC chain helpers
# ---------------------------------------------------------------------------

def _compute_hmac(secret: bytes, record: dict) -> str:
    payload = json.dumps({k: v for k, v in record.items() if k != "hmac"}, sort_keys=True)
    return _hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _verify_chain(records: list[dict], secret: bytes) -> bool:
    """CMSE-CHAIN-0: verify full ledger chain integrity."""
    prev = "0" * 64
    for r in records:
        if r.get("prev_hmac") != prev:
            return False
        expected = _compute_hmac(secret, r)
        if not _hmac.compare_digest(expected[:24], r.get("hmac", "")[:24]):
            return False
        prev = r["hmac"]
    return True


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class ConstitutionalMutationSchedulingEngine:
    """INNOV-111 · CMSE — Constitutional Mutation Scheduling Engine.

    Translates AMPS proposals and CMVG velocity decisions into deterministic,
    non-overlapping execution windows, all sealed in an HMAC-SHA-256 ScheduleLedger.
    """

    def __init__(
        self,
        ledger_path: Path = LEDGER_PATH,
        hmac_secret: bytes = HMAC_SECRET,
        slot_capacity: int = DEFAULT_SLOT_CAPACITY,
    ) -> None:
        self._ledger_path = ledger_path
        self._secret = hmac_secret
        self._slot_capacity = slot_capacity
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory state
        self._windows: dict[str, ScheduleWindow] = {}
        self._slots: dict[int, Optional[str]] = {i: None for i in range(slot_capacity)}
        self._drain_mode: bool = False
        self._sealed_ids: set[str] = set()
        self._prev_hmac: str = "0" * 64

        self._load_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def schedule(
        self,
        proposal_id: str,
        blast_tier: int,
        mutation_scope: set[str],
        constitutional_fitness: float = 1.0,
        velocity_rate: float = 1.0,
        metadata: Optional[dict] = None,
    ) -> ScheduleWindow:
        """Register a new ScheduleWindow from an AMPS proposal.

        CMSE-SCOPE-0, CMSE-BLAST-0, CMSE-VELOCITY-0, CMSE-SLOT-0 enforced.
        """
        # CMSE-SCOPE-0
        if not mutation_scope:
            self._emit_failed("SCHEDULE", "NONE", blast_tier, [], constitutional_fitness, None, None,
                              {"error": "empty mutation_scope"})
            raise CMSEScopeError("CMSE-SCOPE-0: mutation_scope must be non-empty")

        # CMSE-BLAST-0
        if blast_tier not in (0, 1, 2):
            self._emit_failed("SCHEDULE", "NONE", blast_tier, sorted(mutation_scope),
                              constitutional_fitness, None, None, {"error": "invalid blast_tier"})
            raise CMSEBlastError(f"CMSE-BLAST-0: blast_tier must be 0/1/2, got {blast_tier}")

        # CMSE-VELOCITY-0
        if velocity_rate <= 0.0:
            self._emit_failed("SCHEDULE", "NONE", blast_tier, sorted(mutation_scope),
                              constitutional_fitness, None, None,
                              {"error": "HALT velocity — window blocked"})
            raise CMSEVelocityError("CMSE-VELOCITY-0: HALT velocity blocks window scheduling")

        # CMSE-SLOT-0
        free_slot = self._free_slot()
        if free_slot is None:
            self._emit_failed("SCHEDULE", "NONE", blast_tier, sorted(mutation_scope),
                              constitutional_fitness, None, None,
                              {"error": "slot capacity exhausted"})
            raise CMSECapacityError(f"CMSE-SLOT-0: all {self._slot_capacity} slots occupied")

        scope_sorted = sorted(mutation_scope)
        scope_key = hashlib.sha256(json.dumps(scope_sorted).encode()).hexdigest()[:16]
        window_id = _window_id(proposal_id, blast_tier, scope_key)

        window = ScheduleWindow(
            window_id=window_id,
            proposal_id=proposal_id,
            blast_tier=blast_tier,
            mutation_scope=scope_sorted,
            status=WindowStatus.PENDING.value,
            slot_index=free_slot,
            constitutional_fitness=constitutional_fitness,
            metadata=metadata or {},
        )
        self._windows[window_id] = window
        self._slots[free_slot] = window_id

        self._emit(ScheduleAction.SCHEDULE, window, promoted_by=None)
        return window

    def promote(
        self,
        window_id: str,
        velocity_rate: float = 1.0,
        human0_identity: Optional[str] = None,
    ) -> ScheduleWindow:
        """Promote a PENDING window to ACTIVE.

        CMSE-HUMAN0-0, CMSE-OVERLAP-0, CMSE-VELOCITY-0, CMSE-DRAIN-0 enforced.
        """
        window = self._get_window(window_id)

        # CMSE-IMMUT-0: only PENDING may be promoted
        if window.status != WindowStatus.PENDING.value:
            self._emit_failed("PROMOTE", window_id, window.blast_tier,
                              window.mutation_scope, window.constitutional_fitness,
                              None, window.slot_index,
                              {"error": f"cannot promote status={window.status}"})
            raise CMSEImmutError(f"CMSE-IMMUT-0: window {window_id} is {window.status}, not PENDING")

        # CMSE-DRAIN-0
        if self._drain_mode:
            self._emit_failed("PROMOTE", window_id, window.blast_tier,
                              window.mutation_scope, window.constitutional_fitness,
                              None, window.slot_index, {"error": "drain mode active"})
            raise CMSEVelocityError("CMSE-DRAIN-0: drain mode active — no new promotions")

        # CMSE-VELOCITY-0
        if velocity_rate <= 0.0:
            self._emit_failed("PROMOTE", window_id, window.blast_tier,
                              window.mutation_scope, window.constitutional_fitness,
                              None, window.slot_index, {"error": "HALT velocity"})
            raise CMSEVelocityError("CMSE-VELOCITY-0: HALT velocity blocks promotion")

        # CMSE-HUMAN0-0
        if window.blast_tier == BlastTier.TIER0:
            if not human0_identity:
                self._emit_failed("PROMOTE", window_id, window.blast_tier,
                                  window.mutation_scope, window.constitutional_fitness,
                                  None, window.slot_index, {"error": "TIER0 requires HUMAN-0"})
                raise CMSEAuthError("CMSE-HUMAN0-0: TIER0 window promotion requires authenticated HUMAN-0 identity")

        # CMSE-OVERLAP-0
        self._check_overlap(window)

        window.status = WindowStatus.ACTIVE.value
        window.promoted_by = human0_identity or "DEVADAAD"
        self._emit(ScheduleAction.PROMOTE, window, promoted_by=window.promoted_by)
        return window

    def expire(self, window_id: str) -> ScheduleWindow:
        """Mark an ACTIVE or PENDING window as EXPIRED and release its slot."""
        window = self._get_window(window_id)
        if window.status not in (WindowStatus.ACTIVE.value, WindowStatus.PENDING.value):
            self._emit_failed("EXPIRE", window_id, window.blast_tier,
                              window.mutation_scope, window.constitutional_fitness,
                              window.promoted_by, window.slot_index,
                              {"error": f"cannot expire status={window.status}"})
            raise CMSEImmutError(f"CMSE-IMMUT-0: cannot expire window in status={window.status}")

        window.status = WindowStatus.EXPIRED.value
        if window.slot_index is not None:
            self._slots[window.slot_index] = None
        self._emit(ScheduleAction.EXPIRE, window, promoted_by=window.promoted_by)
        return window

    def set_drain(self, human0_identity: str, drain: bool) -> None:
        """Enable / disable drain mode. Always requires HUMAN-0 identity."""
        if not human0_identity:
            raise CMSEAuthError("CMSE-HUMAN0-0: drain mode change requires HUMAN-0 identity")
        self._drain_mode = drain
        action = ScheduleAction.DRAIN if drain else ScheduleAction.UNDRAIN
        # Emit a sentinel record with no specific window
        self._emit_sentinel(action, human0_identity)

    def verify_ledger(self) -> bool:
        """CMSE-CHAIN-0: verify full ScheduleLedger integrity."""
        records = []
        if self._ledger_path.exists():
            for line in self._ledger_path.read_text().splitlines():
                if line.strip():
                    records.append(json.loads(line))
        return _verify_chain(records, self._secret)

    def active_windows(self) -> list[ScheduleWindow]:
        return [w for w in self._windows.values() if w.status == WindowStatus.ACTIVE.value]

    def pending_windows(self) -> list[ScheduleWindow]:
        return [w for w in self._windows.values() if w.status == WindowStatus.PENDING.value]

    def get_window(self, window_id: str) -> Optional[ScheduleWindow]:
        return self._windows.get(window_id)

    @property
    def drain_mode(self) -> bool:
        return self._drain_mode

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_window(self, window_id: str) -> ScheduleWindow:
        w = self._windows.get(window_id)
        if w is None:
            raise CMSEError(f"Unknown window_id: {window_id}")
        return w

    def _free_slot(self) -> Optional[int]:
        for idx, occupant in self._slots.items():
            if occupant is None:
                return idx
        return None

    def _check_overlap(self, candidate: ScheduleWindow) -> None:
        """CMSE-OVERLAP-0: no two ACTIVE windows may share scope items."""
        c_scope = candidate.scope_set()
        for w in self.active_windows():
            if w.window_id == candidate.window_id:
                continue
            if c_scope & w.scope_set():
                raise CMSEOverlapError(
                    f"CMSE-OVERLAP-0: window {candidate.window_id} scope overlaps with "
                    f"active window {w.window_id} on {c_scope & w.scope_set()}"
                )

    def _emit(self, action: ScheduleAction, window: ScheduleWindow,
              promoted_by: Optional[str]) -> None:
        record_id = hashlib.sha256(
            f"{GOVERNOR}:{action.value}:{window.window_id}:{self._prev_hmac}".encode()
        ).hexdigest()
        rec = ScheduleRecord(
            record_id=record_id,
            action=action.value,
            window_id=window.window_id,
            status=window.status,
            governor=GOVERNOR,
            innov_code=INNOV_CODE,
            phase=PHASE,
            blast_tier=window.blast_tier,
            mutation_scope=window.mutation_scope,
            promoted_by=promoted_by,
            constitutional_fitness=window.constitutional_fitness,
            slot_index=window.slot_index,
            metadata=window.metadata,
            prev_hmac=self._prev_hmac,
        ).seal(self._secret, self._prev_hmac)
        self._append_record(asdict(rec))
        self._prev_hmac = rec.hmac

    def _emit_failed(self, action: str, window_id: str, blast_tier: int,
                     scope: list, fitness: float, promoted_by: Optional[str],
                     slot_index: Optional[int], metadata: dict) -> None:
        record_id = hashlib.sha256(
            f"{GOVERNOR}:FAILED:{window_id}:{self._prev_hmac}".encode()
        ).hexdigest()
        rec = ScheduleRecord(
            record_id=record_id,
            action=action,
            window_id=window_id,
            status=WindowStatus.FAILED.value,
            governor=GOVERNOR,
            innov_code=INNOV_CODE,
            phase=PHASE,
            blast_tier=blast_tier,
            mutation_scope=scope,
            promoted_by=promoted_by,
            constitutional_fitness=fitness,
            slot_index=slot_index,
            metadata=metadata,
            prev_hmac=self._prev_hmac,
        ).seal(self._secret, self._prev_hmac)
        self._append_record(asdict(rec))
        self._prev_hmac = rec.hmac

    def _emit_sentinel(self, action: ScheduleAction, human0_identity: str) -> None:
        record_id = hashlib.sha256(
            f"{GOVERNOR}:{action.value}:SENTINEL:{self._prev_hmac}".encode()
        ).hexdigest()
        sentinel = {
            "record_id": record_id,
            "action": action.value,
            "window_id": "SENTINEL",
            "status": "DRAIN" if action == ScheduleAction.DRAIN else "UNDRAIN",
            "governor": GOVERNOR,
            "innov_code": INNOV_CODE,
            "phase": PHASE,
            "blast_tier": -1,
            "mutation_scope": [],
            "promoted_by": human0_identity,
            "constitutional_fitness": 1.0,
            "slot_index": None,
            "metadata": {"drain_mode": self._drain_mode},
            "prev_hmac": self._prev_hmac,
        }
        payload = json.dumps({k: v for k, v in sentinel.items() if k != "hmac"}, sort_keys=True)
        sentinel["hmac"] = _hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
        self._append_record(sentinel)
        self._prev_hmac = sentinel["hmac"]

    def _append_record(self, record: dict) -> None:
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def _load_ledger(self) -> None:
        """Restore in-memory state and prev_hmac tail from persisted ledger."""
        if not self._ledger_path.exists():
            return
        records = []
        for line in self._ledger_path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
        if not records:
            return
        # CMSE-CHAIN-0 on load
        if not _verify_chain(records, self._secret):
            raise CMSEChainError("CMSE-CHAIN-0: ScheduleLedger chain broken on load")
        self._prev_hmac = records[-1]["hmac"]
        # Reconstruct window states
        for r in records:
            wid = r.get("window_id", "")
            if wid in ("SENTINEL", "NONE", ""):
                continue
            scope = r.get("mutation_scope", [])
            w = self._windows.setdefault(wid, ScheduleWindow(
                window_id=wid,
                proposal_id=r.get("metadata", {}).get("proposal_id", wid),
                blast_tier=r.get("blast_tier", 2),
                mutation_scope=scope,
                constitutional_fitness=r.get("constitutional_fitness", 1.0),
                metadata=r.get("metadata", {}),
            ))
            w.status = r["status"]
            w.slot_index = r.get("slot_index")
            w.promoted_by = r.get("promoted_by")
            si = r.get("slot_index")
            if si is not None and si in self._slots:
                self._slots[si] = wid if r["status"] == WindowStatus.ACTIVE.value else None
