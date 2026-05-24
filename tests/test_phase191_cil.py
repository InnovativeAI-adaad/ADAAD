# SPDX-License-Identifier: Apache-2.0
"""
Phase 191 · INNOV-96 · CIL — Constitutional Integrity Ledger
Acceptance test suite — 30 tests (T191-CIL-01 … T191-CIL-30)

Coverage:
  T01–T05  Invariant registry & constants
  T06–T10  CIL-VERIFY-0 / CIL-CHAIN-0 — journal sealing & HMAC chain
  T11–T13  CIL-HUMAN0-0 — escalation, latch, and clearance
  T14–T15  CIL-IMMUT-0  — append-only enforcement
  T16–T17  CIL-DETERM-0 — deterministic attestation records
  T18–T20  CIL-SCOPE-0  — out-of-scope rejection
  T21–T23  CIL-AUDIT-0  — lifecycle event logging
  T24–T25  CIL-ATOMIC-0 — partial-failure journal unchanged
  T26–T27  CIL-REPLAY-0 — replay attestation
  T28–T29  CIL-SEAL-0   — constitutional seal digest
  T30      End-to-end multi-ledger pipeline
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import time
import uuid

import pytest

from dorkllm.constitutional_integrity_ledger import (
    CONSTITUTIONAL_SCOPE,
    GENESIS_HMAC,
    HARD_CLASS,
    HMAC_SECRET,
    INVARIANT_COUNT,
    INVARIANTS,
    AttestationRecord,
    AuditEvent,
    CILAtomicViolation,
    CILChainViolation,
    CILHuman0Flag,
    CILReplayFailure,
    CILScopeViolation,
    ConstitutionalIntegrityLedger,
    LedgerEntry,
    LedgerEntryStatus,
    LedgerSnapshot,
    VerificationStatus,
    make_cil,
    make_entry,
    make_snapshot,
)

pytestmark = pytest.mark.phase191


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def cil():
    return make_cil()


@pytest.fixture
def valid_snap():
    e1 = make_entry("mutation_ledger", "payload-aaa")
    e2 = make_entry("mutation_ledger", "payload-bbb", prev_hmac=e1.hmac_value)
    return make_snapshot("mutation_ledger", [e1, e2])


@pytest.fixture
def tampered_snap():
    e1 = make_entry("mutation_ledger", "payload-xxx")
    # manually corrupt the hmac
    bad = LedgerEntry(
        entry_id=e1.entry_id,
        ledger_name=e1.ledger_name,
        hmac_value="deadbeef" * 8,   # wrong HMAC
        prev_hmac=e1.prev_hmac,
        payload_digest=e1.payload_digest,
        timestamp=e1.timestamp,
    )
    return make_snapshot("mutation_ledger", [bad])


# ── T01–T05: Invariant registry & constants ───────────────────────────────────

def test_T191_CIL_01_invariants_count():
    """CIL-VERIFY-0: exactly 10 hard-class invariants registered."""
    assert INVARIANT_COUNT == 10
    assert len(INVARIANTS) == 10


def test_T191_CIL_02_invariant_names():
    """All 10 canonical invariant codes present."""
    expected = {
        "CIL-VERIFY-0", "CIL-CHAIN-0", "CIL-HUMAN0-0", "CIL-IMMUT-0",
        "CIL-DETERM-0", "CIL-SCOPE-0", "CIL-AUDIT-0", "CIL-ATOMIC-0",
        "CIL-REPLAY-0", "CIL-SEAL-0",
    }
    assert set(INVARIANTS) == expected


def test_T191_CIL_03_hard_class():
    """HARD_CLASS constant is 'Hard'."""
    assert HARD_CLASS == "Hard"


def test_T191_CIL_04_constitutional_scope_size():
    """CONSTITUTIONAL_SCOPE contains exactly 10 ledger namespaces."""
    assert len(CONSTITUTIONAL_SCOPE) == 10


def test_T191_CIL_05_genesis_hmac_sentinel():
    """GENESIS_HMAC is the 64-zero-char sentinel."""
    assert GENESIS_HMAC == "0" * 64


# ── T06–T10: CIL-VERIFY-0 / CIL-CHAIN-0 ─────────────────────────────────────

def test_T191_CIL_06_verify_returns_attestation(cil, valid_snap):
    """CIL-VERIFY-0: verify_ledger() returns an AttestationRecord."""
    rec = cil.verify_ledger(valid_snap)
    assert isinstance(rec, AttestationRecord)


def test_T191_CIL_07_attestation_sealed_in_journal(cil, valid_snap):
    """CIL-VERIFY-0: attestation record is appended to the CIL journal."""
    rec = cil.verify_ledger(valid_snap)
    assert rec in cil.journal


def test_T191_CIL_08_chain_link_genesis(cil, valid_snap):
    """CIL-CHAIN-0: first journal entry uses GENESIS_HMAC as prev_hmac."""
    rec = cil.verify_ledger(valid_snap)
    assert rec.prev_hmac == GENESIS_HMAC


def test_T191_CIL_09_chain_link_second_entry(cil):
    """CIL-CHAIN-0: second journal entry's prev_hmac equals first entry's hmac."""
    snap1 = make_snapshot("mutation_ledger", [make_entry("mutation_ledger", "p1")])
    snap2 = make_snapshot("governance_ledger", [make_entry("governance_ledger", "p2")])
    rec1 = cil.verify_ledger(snap1)
    rec2 = cil.verify_ledger(snap2)
    assert rec2.prev_hmac == rec1.hmac


def test_T191_CIL_10_chain_verify_intact(cil):
    """CIL-CHAIN-0: verify_journal_chain() returns True for an intact journal."""
    for name in ("mutation_ledger", "governance_ledger", "audit_ledger"):
        cil.verify_ledger(make_snapshot(name, [make_entry(name, "x")]))
    assert cil.verify_journal_chain() is True


# ── T11–T13: CIL-HUMAN0-0 ────────────────────────────────────────────────────

def test_T191_CIL_11_tampered_ledger_raises_human0_flag(cil, tampered_snap):
    """CIL-HUMAN0-0: a tampered ledger sets the HUMAN-0 flag."""
    cil.verify_ledger(tampered_snap)
    assert cil.human0_flagged is True


def test_T191_CIL_12_human0_flag_blocks_new_verification(cil, tampered_snap, valid_snap):
    """CIL-HUMAN0-0: subsequent verify_ledger raises CILHuman0Flag while flag is set."""
    cil.verify_ledger(tampered_snap)
    with pytest.raises(CILHuman0Flag):
        cil.verify_ledger(valid_snap)


def test_T191_CIL_13_acknowledge_clears_human0_flag(cil, tampered_snap, valid_snap):
    """CIL-HUMAN0-0: acknowledge_human0() clears the flag; verification resumes."""
    cil.verify_ledger(tampered_snap)
    assert cil.human0_flagged
    cil.acknowledge_human0("DUSTIN-L-REID-TOKEN-001")
    assert not cil.human0_flagged
    rec = cil.verify_ledger(valid_snap)
    assert rec.status == VerificationStatus.ATTESTED


# ── T14–T15: CIL-IMMUT-0 ─────────────────────────────────────────────────────

def test_T191_CIL_14_journal_property_returns_copy(cil, valid_snap):
    """CIL-IMMUT-0: journal property returns a list copy, not the internal list."""
    cil.verify_ledger(valid_snap)
    j1 = cil.journal
    j2 = cil.journal
    assert j1 is not j2
    assert j1 == j2


def test_T191_CIL_15_journal_grows_append_only(cil):
    """CIL-IMMUT-0: journal grows monotonically; existing records are unchanged."""
    snaps = [
        make_snapshot(name, [make_entry(name, f"p{i}")])
        for i, name in enumerate(("mutation_ledger", "audit_ledger", "replay_ledger"))
    ]
    recs = [cil.verify_ledger(s) for s in snaps]
    journal = cil.journal
    for i, rec in enumerate(recs):
        assert journal[i].record_id == rec.record_id
        assert journal[i].hmac == rec.hmac


# ── T16–T17: CIL-DETERM-0 ────────────────────────────────────────────────────

def test_T191_CIL_16_deterministic_hmac_same_inputs():
    """CIL-DETERM-0: identical inputs produce identical AttestationRecord HMACs."""
    ts = 1_700_000_000.0
    entry = LedgerEntry("eid-1", "mutation_ledger", "aahex" * 12 + "aaaa",
                        GENESIS_HMAC, "digest001", ts)
    # Build two records with identical fields
    r1 = AttestationRecord(
        record_id="rid-fixed", ledger_id="lid-1", ledger_name="mutation_ledger",
        status=VerificationStatus.ATTESTED, entry_count=1, violation_count=0,
        constitutional_seal="seal001",
        verdicts=[], timestamp=ts, prev_hmac=GENESIS_HMAC,
    )
    r1.seal()
    r2 = AttestationRecord(
        record_id="rid-fixed", ledger_id="lid-1", ledger_name="mutation_ledger",
        status=VerificationStatus.ATTESTED, entry_count=1, violation_count=0,
        constitutional_seal="seal001",
        verdicts=[], timestamp=ts, prev_hmac=GENESIS_HMAC,
    )
    r2.seal()
    assert r1.hmac == r2.hmac


def test_T191_CIL_17_different_inputs_different_hmac():
    """CIL-DETERM-0: different record_id produces different HMAC."""
    def make_rec(rid):
        r = AttestationRecord(
            record_id=rid, ledger_id="lid-1", ledger_name="mutation_ledger",
            status=VerificationStatus.ATTESTED, entry_count=1, violation_count=0,
            constitutional_seal="seal001",
            verdicts=[], timestamp=1_700_000_000.0, prev_hmac=GENESIS_HMAC,
        )
        r.seal()
        return r
    assert make_rec("A").hmac != make_rec("B").hmac


# ── T18–T20: CIL-SCOPE-0 ─────────────────────────────────────────────────────

def test_T191_CIL_18_out_of_scope_raises(cil):
    """CIL-SCOPE-0: ledger_name not in CONSTITUTIONAL_SCOPE raises CILScopeViolation."""
    snap = LedgerSnapshot(str(uuid.uuid4()), "rogue_ledger", [], time.time())
    with pytest.raises(CILScopeViolation):
        cil.verify_ledger(snap)


def test_T191_CIL_19_out_of_scope_does_not_touch_journal(cil):
    """CIL-SCOPE-0: scope rejection leaves journal empty."""
    snap = LedgerSnapshot(str(uuid.uuid4()), "external_service", [], time.time())
    try:
        cil.verify_ledger(snap)
    except CILScopeViolation:
        pass
    assert len(cil.journal) == 0


def test_T191_CIL_20_all_scope_members_accepted(cil):
    """CIL-SCOPE-0: every member of CONSTITUTIONAL_SCOPE is accepted."""
    for name in sorted(CONSTITUTIONAL_SCOPE):
        snap = make_snapshot(name, [make_entry(name, "p")])
        rec = cil.verify_ledger(snap)
        assert rec.ledger_name == name
    assert len(cil.journal) == len(CONSTITUTIONAL_SCOPE)


# ── T21–T23: CIL-AUDIT-0 ─────────────────────────────────────────────────────

def test_T191_CIL_21_audit_log_populated(cil, valid_snap):
    """CIL-AUDIT-0: verification emits audit events."""
    cil.verify_ledger(valid_snap)
    assert len(cil.audit_log) > 0


def test_T191_CIL_22_audit_contains_submitted_event(cil, valid_snap):
    """CIL-AUDIT-0: SUBMITTED event appears for each verification."""
    cil.verify_ledger(valid_snap)
    types = [e.event_type for e in cil.audit_log]
    assert VerificationStatus.SUBMITTED in types


def test_T191_CIL_23_tampered_audit_contains_escalated(cil, tampered_snap):
    """CIL-AUDIT-0: ESCALATED event logged for tampered ledger."""
    cil.verify_ledger(tampered_snap)
    types = [e.event_type for e in cil.audit_log]
    assert VerificationStatus.ESCALATED in types


# ── T24–T25: CIL-ATOMIC-0 ────────────────────────────────────────────────────

def test_T191_CIL_24_atomic_violation_journal_unchanged(cil, monkeypatch):
    """CIL-ATOMIC-0: if _atomic_verify raises, journal is unchanged."""
    def _bad_atomic(snap):
        raise RuntimeError("simulated mid-verify failure")
    monkeypatch.setattr(cil, "_atomic_verify", _bad_atomic)
    snap = make_snapshot("mutation_ledger", [make_entry("mutation_ledger", "x")])
    with pytest.raises(CILAtomicViolation):
        cil.verify_ledger(snap)
    assert len(cil.journal) == 0


def test_T191_CIL_25_atomic_violation_human0_not_set(cil, monkeypatch):
    """CIL-ATOMIC-0: atomic failure does not set the HUMAN-0 flag."""
    def _bad_atomic(snap):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(cil, "_atomic_verify", _bad_atomic)
    snap = make_snapshot("mutation_ledger", [make_entry("mutation_ledger", "x")])
    with pytest.raises(CILAtomicViolation):
        cil.verify_ledger(snap)
    assert cil.human0_flagged is False


# ── T26–T27: CIL-REPLAY-0 ────────────────────────────────────────────────────

def test_T191_CIL_26_replay_valid_attestation(cil, valid_snap):
    """CIL-REPLAY-0: replay_attestation() returns True for a genuine record."""
    rec = cil.verify_ledger(valid_snap)
    assert cil.replay_attestation(rec) is True


def test_T191_CIL_27_replay_tampered_attestation_raises(cil, valid_snap):
    """CIL-REPLAY-0: replay_attestation() raises CILReplayFailure for tampered HMAC."""
    rec = cil.verify_ledger(valid_snap)
    # corrupt the stored hmac
    object.__setattr__(rec, "hmac", "badhmacsignature" * 4)
    with pytest.raises(CILReplayFailure):
        cil.replay_attestation(rec)


# ── T28–T29: CIL-SEAL-0 ──────────────────────────────────────────────────────

def test_T191_CIL_28_constitutional_seal_is_sha256_of_hmacs(cil):
    """CIL-SEAL-0: constitutional_seal equals SHA-256 of concatenated entry HMACs."""
    e1 = make_entry("mutation_ledger", "p1")
    e2 = make_entry("mutation_ledger", "p2", prev_hmac=e1.hmac_value)
    snap = make_snapshot("mutation_ledger", [e1, e2])
    rec = cil.verify_ledger(snap)
    expected_seal = hashlib.sha256(
        (e1.hmac_value + e2.hmac_value).encode()
    ).hexdigest()
    assert rec.constitutional_seal == expected_seal


def test_T191_CIL_29_empty_ledger_seal_is_sha256_of_empty(cil):
    """CIL-SEAL-0: empty ledger produces SHA-256 of empty string as seal."""
    snap = make_snapshot("replay_ledger", [])
    rec = cil.verify_ledger(snap)
    expected_seal = hashlib.sha256(b"").hexdigest()
    assert rec.constitutional_seal == expected_seal


# ── T30: End-to-end multi-ledger pipeline ────────────────────────────────────

def test_T191_CIL_30_end_to_end_multi_ledger_pipeline():
    """
    End-to-end: verify 3 ledgers, introduce 1 tamper, escalate HUMAN-0,
    acknowledge, resume — journal chain verified throughout.
    """
    cil = make_cil()

    # 1. Two clean ledgers
    for name in ("mutation_ledger", "governance_ledger"):
        e = make_entry(name, f"ok-payload-{name}")
        snap = make_snapshot(name, [e])
        rec = cil.verify_ledger(snap)
        assert rec.status == VerificationStatus.ATTESTED
        assert rec.violation_count == 0

    # 2. Tampered ledger — triggers HUMAN-0
    bad_entry = LedgerEntry(
        entry_id=str(uuid.uuid4()),
        ledger_name="audit_ledger",
        hmac_value="0bad" * 16,   # corrupted
        prev_hmac=GENESIS_HMAC,
        payload_digest="digest-bad",
        timestamp=time.time(),
    )
    tampered = make_snapshot("audit_ledger", [bad_entry])
    rec_violated = cil.verify_ledger(tampered)
    assert rec_violated.status == VerificationStatus.ESCALATED
    assert cil.human0_flagged

    # 3. New verification blocked
    with pytest.raises(CILHuman0Flag):
        cil.verify_ledger(make_snapshot("mutation_ledger", [make_entry("mutation_ledger", "x")]))

    # 4. HUMAN-0 acknowledges
    cil.acknowledge_human0("HUMAN-0-RATIFICATION-DUSTIN-REID")
    assert not cil.human0_flagged

    # 5. Resume — clean ledger accepted
    clean = make_snapshot("rollback_ledger", [make_entry("rollback_ledger", "clean")])
    rec_clean = cil.verify_ledger(clean)
    assert rec_clean.status == VerificationStatus.ATTESTED

    # 6. Journal chain is fully intact across all 4 entries
    assert cil.verify_journal_chain() is True
    assert len(cil.journal) == 4

    # 7. All entries replayable
    for record in cil.journal:
        assert cil.replay_attestation(record) is True
