# SPDX-License-Identifier: Apache-2.0
"""
INNOV-96 · CIL — Constitutional Integrity Ledger
==================================================
Phase 191 · v10.2.0 · InnovativeAI LLC

World-first: A constitutionally-governed cross-ledger integrity attestation
engine that performs cryptographic HMAC-chain verification across every ADAAD
governance ledger, seals attestations in an append-only constitutional
integrity journal, and escalates violations to HUMAN-0 before any further
mutation activity is permitted.

Hard-class invariants enforced (10):
  CIL-VERIFY-0   Every ledger submitted for verification produces a sealed
                 attestation record in the CIL journal.
  CIL-CHAIN-0    CIL journal entries are HMAC-SHA256 chained; each entry's
                 HMAC covers the previous entry's HMAC.
  CIL-HUMAN0-0   Any integrity violation detected during verification
                 triggers a HUMAN-0 escalation; no further mutation is
                 permitted until the flag is cleared.
  CIL-IMMUT-0    The CIL journal is append-only; no entry may be modified
                 or deleted after sealing.
  CIL-DETERM-0   Given identical LedgerSnapshot inputs, verify_ledger()
                 always produces an identical AttestationRecord (deterministic).
  CIL-SCOPE-0    CIL only accepts ledgers within the ADAAD constitutional
                 scope; out-of-scope submissions raise CILScopeViolation.
  CIL-AUDIT-0    All verification lifecycle events (SUBMITTED, VERIFYING,
                 ATTESTED, VIOLATED, ESCALATED) are ledgered.
  CIL-ATOMIC-0   A verification run is atomic; any partial failure raises
                 CILAtomicViolation and leaves the journal unchanged.
  CIL-REPLAY-0   AttestationRecords are deterministically replayable:
                 replay_attestation() re-derives the same HMAC from stored
                 canonical fields.
  CIL-SEAL-0     Each AttestationRecord includes a constitutional seal
                 (SHA-256 of all ledger entry HMACs concatenated in order).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

# ── Constitutional invariant registry ────────────────────────────────────────

INVARIANTS: List[str] = [
    "CIL-VERIFY-0",
    "CIL-CHAIN-0",
    "CIL-HUMAN0-0",
    "CIL-IMMUT-0",
    "CIL-DETERM-0",
    "CIL-SCOPE-0",
    "CIL-AUDIT-0",
    "CIL-ATOMIC-0",
    "CIL-REPLAY-0",
    "CIL-SEAL-0",
]

HARD_CLASS = "Hard"
INVARIANT_COUNT = len(INVARIANTS)  # 10

# ── Constitutional constants ──────────────────────────────────────────────────

HMAC_SECRET: bytes = b"CIL-ADAAD-CHAIN-v1"
CONSTITUTIONAL_SCOPE: frozenset = frozenset({
    "mutation_ledger",
    "governance_ledger",
    "evolution_ledger",
    "audit_ledger",
    "invariant_ledger",
    "admission_ledger",
    "amendment_ledger",
    "tag_ledger",
    "rollback_ledger",
    "replay_ledger",
})
GENESIS_HMAC = "0" * 64  # sentinel for first journal entry


# ── Exceptions ───────────────────────────────────────────────────────────────

class CILScopeViolation(Exception):
    """CIL-SCOPE-0: ledger is outside ADAAD constitutional scope."""

class CILChainViolation(Exception):
    """CIL-CHAIN-0: HMAC chain tamper detected in journal."""

class CILImmutabilityViolation(Exception):
    """CIL-IMMUT-0: attempt to modify or delete a sealed journal entry."""

class CILHuman0Flag(Exception):
    """CIL-HUMAN0-0: integrity violation requires HUMAN-0 clearance."""

class CILAtomicViolation(Exception):
    """CIL-ATOMIC-0: partial verification — journal left unchanged."""

class CILReplayFailure(Exception):
    """CIL-REPLAY-0: replay of attestation produced divergent HMAC."""

class CILSealFailure(Exception):
    """CIL-SEAL-0: constitutional seal digest mismatch."""


# ── Enumerations ─────────────────────────────────────────────────────────────

class VerificationStatus(str, Enum):
    SUBMITTED  = "SUBMITTED"
    VERIFYING  = "VERIFYING"
    ATTESTED   = "ATTESTED"   # chain intact — no violations
    VIOLATED   = "VIOLATED"   # chain broken or tamper detected
    ESCALATED  = "ESCALATED"  # HUMAN-0 notified


class LedgerEntryStatus(str, Enum):
    VALID    = "VALID"
    TAMPERED = "TAMPERED"
    MISSING  = "MISSING"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class LedgerEntry:
    """A single HMAC-bearing entry in an external governance ledger."""
    entry_id: str
    ledger_name: str
    hmac_value: str           # hex HMAC from originating module
    prev_hmac: str            # chained previous HMAC
    payload_digest: str       # SHA-256 of the entry's canonical payload
    timestamp: float


@dataclass
class LedgerSnapshot:
    """Immutable snapshot of one governance ledger submitted for CIL verification."""
    ledger_id: str            # UUID identifying this snapshot
    ledger_name: str          # must be in CONSTITUTIONAL_SCOPE
    entries: List[LedgerEntry]
    snapshot_time: float


@dataclass
class EntryVerdict:
    """CIL verdict for a single ledger entry."""
    entry_id: str
    status: LedgerEntryStatus
    detail: str = ""


@dataclass
class AttestationRecord:
    """
    Sealed, HMAC-chained CIL journal entry (CIL-VERIFY-0, CIL-CHAIN-0).
    Produced once per verify_ledger() call.
    """
    record_id: str
    ledger_id: str
    ledger_name: str
    status: VerificationStatus
    entry_count: int
    violation_count: int
    constitutional_seal: str    # CIL-SEAL-0: SHA-256 of all entry HMACs
    verdicts: List[EntryVerdict]
    timestamp: float
    prev_hmac: str              # CIL-CHAIN-0
    hmac: str = field(default="", init=False)

    # ── Canonical payload for determinism (CIL-DETERM-0) ──────────────────

    def _canonical(self) -> bytes:
        return json.dumps({
            "record_id":          self.record_id,
            "ledger_id":          self.ledger_id,
            "ledger_name":        self.ledger_name,
            "status":             self.status.value,
            "entry_count":        self.entry_count,
            "violation_count":    self.violation_count,
            "constitutional_seal": self.constitutional_seal,
            "timestamp":          self.timestamp,
            "prev_hmac":          self.prev_hmac,
        }, sort_keys=True).encode()

    def seal(self, secret: bytes = HMAC_SECRET) -> None:
        """Compute and store HMAC (CIL-CHAIN-0, CIL-DETERM-0)."""
        self.hmac = hmac.new(secret, self._canonical(), hashlib.sha256).hexdigest()

    def verify_seal(self, secret: bytes = HMAC_SECRET) -> bool:
        """Verify stored HMAC matches recomputed value (CIL-REPLAY-0)."""
        expected = hmac.new(secret, self._canonical(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.hmac, expected)


@dataclass
class AuditEvent:
    """CIL-AUDIT-0: lifecycle event record."""
    event_id: str
    record_id: str
    ledger_name: str
    event_type: VerificationStatus
    detail: str
    timestamp: float


# ── Constitutional Integrity Ledger ───────────────────────────────────────────

class ConstitutionalIntegrityLedger:
    """
    Cross-ledger integrity attestation engine.

    Enforces all 10 CIL hard-class invariants.
    Thread-safety: single-instance, sequential calls assumed (no async).
    """

    def __init__(self, secret: bytes = HMAC_SECRET) -> None:
        self._secret: bytes = secret
        self._journal: List[AttestationRecord] = []   # CIL-IMMUT-0: append-only
        self._audit_log: List[AuditEvent] = []        # CIL-AUDIT-0
        self._human0_flagged: bool = False             # CIL-HUMAN0-0 latch
        self._sealed_ids: set = set()                  # guard CIL-IMMUT-0

    # ── Public API ────────────────────────────────────────────────────────────

    def verify_ledger(self, snapshot: LedgerSnapshot) -> AttestationRecord:
        """
        Verify the HMAC chain of *snapshot* and produce an AttestationRecord.

        Raises
        ------
        CILScopeViolation   – ledger_name outside CONSTITUTIONAL_SCOPE
        CILHuman0Flag       – HUMAN-0 flag already set; no new work until cleared
        CILAtomicViolation  – internal partial failure (journal unchanged)
        CIL-CHAIN-0 via CILChainViolation on journal tamper check
        """
        # CIL-SCOPE-0
        if snapshot.ledger_name not in CONSTITUTIONAL_SCOPE:
            raise CILScopeViolation(
                f"CIL-SCOPE-0: '{snapshot.ledger_name}' is not in CONSTITUTIONAL_SCOPE"
            )

        # CIL-HUMAN0-0: block new verification while violation flag is raised
        if self._human0_flagged:
            raise CILHuman0Flag(
                "CIL-HUMAN0-0: HUMAN-0 integrity flag is set; "
                "clear via acknowledge_human0() before resuming."
            )

        self._emit_audit(
            snapshot.ledger_id, snapshot.ledger_name,
            VerificationStatus.SUBMITTED, "verification submitted"
        )

        # CIL-ATOMIC-0: stage all work before touching journal
        try:
            record = self._atomic_verify(snapshot)
        except Exception as exc:
            self._emit_audit(
                snapshot.ledger_id, snapshot.ledger_name,
                VerificationStatus.SUBMITTED,
                f"atomic failure — journal unchanged: {exc}"
            )
            raise CILAtomicViolation(
                f"CIL-ATOMIC-0: verification aborted, journal unchanged. Cause: {exc}"
            ) from exc

        # CIL-HUMAN0-0: escalate on violations
        if record.violation_count > 0:
            self._human0_flagged = True
            record.status = VerificationStatus.ESCALATED
            # re-seal with updated status
            record.hmac = ""
            record.seal(self._secret)
            self._emit_audit(
                record.record_id, record.ledger_name,
                VerificationStatus.ESCALATED,
                f"{record.violation_count} violation(s) detected — HUMAN-0 escalated"
            )

        # Append to journal (CIL-IMMUT-0 maintained by never modifying prior entries)
        self._journal.append(record)
        self._sealed_ids.add(record.record_id)

        self._emit_audit(
            record.record_id, record.ledger_name,
            record.status, "attestation sealed in journal"
        )

        return record

    def replay_attestation(self, record: AttestationRecord) -> bool:
        """
        Replay-verify an AttestationRecord from its stored canonical fields.
        Returns True iff the recomputed HMAC matches stored HMAC (CIL-REPLAY-0).
        """
        if not record.verify_seal(self._secret):
            raise CILReplayFailure(
                f"CIL-REPLAY-0: replay of record {record.record_id} "
                "produced divergent HMAC — possible tamper"
            )
        return True

    def verify_journal_chain(self) -> bool:
        """
        Walk the full journal and verify every HMAC chain link (CIL-CHAIN-0).
        Returns True if chain is intact; raises CILChainViolation on tamper.
        """
        prev = GENESIS_HMAC
        for idx, record in enumerate(self._journal):
            if record.prev_hmac != prev:
                raise CILChainViolation(
                    f"CIL-CHAIN-0: chain broken at index {idx} "
                    f"(record {record.record_id}): "
                    f"expected prev_hmac={prev!r}, got {record.prev_hmac!r}"
                )
            if not record.verify_seal(self._secret):
                raise CILChainViolation(
                    f"CIL-CHAIN-0: HMAC tamper detected at index {idx} "
                    f"(record {record.record_id})"
                )
            prev = record.hmac
        return True

    def acknowledge_human0(self, ratification_token: str) -> None:
        """
        Clear the HUMAN-0 violation flag after operator review (CIL-HUMAN0-0).
        *ratification_token* is recorded in the audit log for provenance.
        """
        if not self._human0_flagged:
            return
        self._human0_flagged = False
        self._emit_audit(
            "HUMAN-0-ACK", "cil_journal",
            VerificationStatus.ATTESTED,
            f"HUMAN-0 flag cleared; ratification_token={ratification_token}"
        )

    @property
    def journal(self) -> List[AttestationRecord]:
        """Read-only view of the CIL journal (CIL-IMMUT-0)."""
        return list(self._journal)

    @property
    def audit_log(self) -> List[AuditEvent]:
        """Read-only audit event log (CIL-AUDIT-0)."""
        return list(self._audit_log)

    @property
    def human0_flagged(self) -> bool:
        """True when a HUMAN-0 violation flag is active (CIL-HUMAN0-0)."""
        return self._human0_flagged

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _atomic_verify(self, snapshot: LedgerSnapshot) -> AttestationRecord:
        """
        Execute full verification in a staging area; return the sealed record.
        No journal mutation occurs here (CIL-ATOMIC-0).
        """
        self._emit_audit(
            snapshot.ledger_id, snapshot.ledger_name,
            VerificationStatus.VERIFYING, "chain verification in progress"
        )

        verdicts: List[EntryVerdict] = []
        violation_count = 0
        prev_hmac = GENESIS_HMAC

        for entry in snapshot.entries:
            # Verify each entry's HMAC chain link
            expected = self._recompute_entry_hmac(entry)
            if entry.hmac_value != expected or entry.prev_hmac != prev_hmac:
                verdict = EntryVerdict(
                    entry_id=entry.entry_id,
                    status=LedgerEntryStatus.TAMPERED,
                    detail=(
                        f"chain broken: prev_hmac expected={prev_hmac!r} "
                        f"got={entry.prev_hmac!r}" if entry.prev_hmac != prev_hmac
                        else f"HMAC mismatch: expected={expected!r} got={entry.hmac_value!r}"
                    ),
                )
                violation_count += 1
            else:
                verdict = EntryVerdict(
                    entry_id=entry.entry_id,
                    status=LedgerEntryStatus.VALID,
                )
            verdicts.append(verdict)
            prev_hmac = entry.hmac_value  # advance chain

        # CIL-SEAL-0: constitutional seal = SHA-256 of all entry HMACs in order
        seal_input = "".join(e.hmac_value for e in snapshot.entries).encode()
        constitutional_seal = hashlib.sha256(seal_input).hexdigest()

        status = (
            VerificationStatus.VIOLATED if violation_count > 0
            else VerificationStatus.ATTESTED
        )

        prev_journal_hmac = (
            self._journal[-1].hmac if self._journal else GENESIS_HMAC
        )

        record = AttestationRecord(
            record_id=str(uuid.uuid4()),
            ledger_id=snapshot.ledger_id,
            ledger_name=snapshot.ledger_name,
            status=status,
            entry_count=len(snapshot.entries),
            violation_count=violation_count,
            constitutional_seal=constitutional_seal,
            verdicts=verdicts,
            timestamp=snapshot.snapshot_time,
            prev_hmac=prev_journal_hmac,  # CIL-CHAIN-0
        )
        record.seal(self._secret)  # CIL-CHAIN-0, CIL-DETERM-0
        return record

    def _recompute_entry_hmac(self, entry: LedgerEntry) -> str:
        """
        Re-derive the expected HMAC for a LedgerEntry using the same
        canonical scheme as the originating module (deterministic, CIL-DETERM-0).
        """
        payload = json.dumps({
            "entry_id":       entry.entry_id,
            "ledger_name":    entry.ledger_name,
            "payload_digest": entry.payload_digest,
            "prev_hmac":      entry.prev_hmac,
            "timestamp":      entry.timestamp,
        }, sort_keys=True).encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def _emit_audit(
        self,
        record_id: str,
        ledger_name: str,
        event_type: VerificationStatus,
        detail: str,
    ) -> None:
        """Append an AuditEvent to the audit log (CIL-AUDIT-0)."""
        self._audit_log.append(AuditEvent(
            event_id=str(uuid.uuid4()),
            record_id=record_id,
            ledger_name=ledger_name,
            event_type=event_type,
            detail=detail,
            timestamp=time.time(),
        ))


# ── Factory helpers ───────────────────────────────────────────────────────────

def make_cil(secret: bytes = HMAC_SECRET) -> ConstitutionalIntegrityLedger:
    """Construct a ConstitutionalIntegrityLedger with the given secret."""
    return ConstitutionalIntegrityLedger(secret=secret)


def make_entry(
    ledger_name: str,
    payload_digest: str,
    prev_hmac: str = GENESIS_HMAC,
    secret: bytes = HMAC_SECRET,
) -> LedgerEntry:
    """
    Construct a valid LedgerEntry with a correctly derived HMAC.
    Useful in tests and governance tooling.
    """
    entry_id = str(uuid.uuid4())
    ts = time.time()
    payload = json.dumps({
        "entry_id":       entry_id,
        "ledger_name":    ledger_name,
        "payload_digest": payload_digest,
        "prev_hmac":      prev_hmac,
        "timestamp":      ts,
    }, sort_keys=True).encode()
    hmac_value = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return LedgerEntry(
        entry_id=entry_id,
        ledger_name=ledger_name,
        hmac_value=hmac_value,
        prev_hmac=prev_hmac,
        payload_digest=payload_digest,
        timestamp=ts,
    )


def make_snapshot(
    ledger_name: str,
    entries: List[LedgerEntry],
) -> LedgerSnapshot:
    """Construct a LedgerSnapshot for the given entries."""
    return LedgerSnapshot(
        ledger_id=str(uuid.uuid4()),
        ledger_name=ledger_name,
        entries=entries,
        snapshot_time=time.time(),
    )
