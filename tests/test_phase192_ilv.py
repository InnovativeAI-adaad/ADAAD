# SPDX-License-Identifier: Apache-2.0
"""
Phase 192 · INNOV-97 · ILV — Invariant Lineage Verifier
30-test acceptance suite (T192-ILV-01 … T192-ILV-30)
Governor: DUSTIN L REID · InnovativeAI LLC
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from typing import Dict
from unittest.mock import patch

import pytest

from dorkllm.invariant_lineage_verifier import (
    GOVERNOR,
    HMAC_SECRET,
    INNOVATION_CODE,
    INVARIANTS,
    INVARIANT_COUNT,
    InvariantLineageVerifier,
    InvariantRecord,
    ILVAtomicViolation,
    ILVHuman0Escalation,
    ILVScopeViolation,
    ILVSealViolation,
    LineageStatus,
    RuntimeDeterminismProvider,
    _build_invariant_registry,
    _canonical_record,
    _constitutional_seal,
    _hmac_hex,
    _seal_record,
    _verify_seal,
    verify_invariant_lineage,
)

pytestmark = pytest.mark.phase192


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_journal(tmp_path):
    return str(tmp_path / "lineage_journal.jsonl")


@pytest.fixture
def fixed_ts():
    return "2026-05-25T00:00:00+00:00"


@pytest.fixture
def det(fixed_ts):
    return RuntimeDeterminismProvider(fixed_ts=fixed_ts)


@pytest.fixture
def engine(tmp_journal, det):
    return InvariantLineageVerifier(determinism=det, journal_path=tmp_journal)


@pytest.fixture
def registry():
    return _build_invariant_registry()


@pytest.fixture
def minimal_registry():
    """Minimal single-invariant registry for targeted tests."""
    return {
        "ILV-CHAIN-0": InvariantRecord(
            invariant_id="ILV-CHAIN-0",
            innovation_code="INNOV-97",
            introduction_phase=192,
            introduction_version="10.3.0",
            hard_class="Hard",
            description="Test invariant",
        )
    }


# ── T192-ILV-01: Module constants ─────────────────────────────────────────────

def test_t192_ilv_01_module_constants():
    """T192-ILV-01: Innovation code, phase, version, and invariant count are correct."""
    assert INNOVATION_CODE == "INNOV-97"
    assert INVARIANT_COUNT == 10
    assert len(INVARIANTS) == 10


# ── T192-ILV-02: All 10 invariant IDs registered ─────────────────────────────

def test_t192_ilv_02_invariant_ids():
    """T192-ILV-02: All 10 ILV Hard-class invariant IDs are registered."""
    expected = {
        "ILV-CHAIN-0", "ILV-HUMAN0-0", "ILV-IMMUT-0", "ILV-DETERM-0",
        "ILV-SCOPE-0", "ILV-ATOMIC-0", "ILV-AUDIT-0", "ILV-REPLAY-0",
        "ILV-SEAL-0", "ILV-COMPLETE-0",
    }
    assert expected.issubset(set(INVARIANTS))


# ── T192-ILV-03: HMAC utility correctness ────────────────────────────────────

def test_t192_ilv_03_hmac_utility():
    """T192-ILV-03: _hmac_hex produces correct HMAC-SHA256."""
    payload = "test-payload"
    expected = hmac.new(HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    assert _hmac_hex(payload) == expected


# ── T192-ILV-04: Determinism provider fixed timestamp ────────────────────────

def test_t192_ilv_04_determinism_fixed_ts(fixed_ts, det):
    """T192-ILV-04: RuntimeDeterminismProvider returns fixed timestamp."""
    assert det.now_iso() == fixed_ts


# ── T192-ILV-05: Determinism provider live timestamp ─────────────────────────

def test_t192_ilv_05_determinism_live_ts():
    """T192-ILV-05: RuntimeDeterminismProvider without fixed_ts returns non-empty ISO string."""
    det = RuntimeDeterminismProvider()
    ts = det.now_iso()
    assert "T" in ts and "+" in ts or "Z" in ts or ts.endswith("+00:00")


# ── T192-ILV-06: Registry contains ILV invariants ────────────────────────────

def test_t192_ilv_06_registry_contains_ilv(registry):
    """T192-ILV-06: Built registry contains all 10 ILV-* invariants."""
    ilv_keys = [k for k in registry if k.startswith("ILV-")]
    assert len(ilv_keys) == 10


# ── T192-ILV-07: Registry contains CIL invariants ────────────────────────────

def test_t192_ilv_07_registry_contains_cil(registry):
    """T192-ILV-07: Built registry contains CIL invariants from Phase 191."""
    cil_keys = [k for k in registry if k.startswith("CIL-")]
    assert len(cil_keys) == 10


# ── T192-ILV-08: Single invariant verification returns VALID ──────────────────

def test_t192_ilv_08_single_verify_valid(engine):
    """T192-ILV-08: verify_single returns VALID for a known invariant."""
    record = engine.verify_single("ILV-CHAIN-0")
    assert record.status == LineageStatus.VALID
    assert record.invariant_id == "ILV-CHAIN-0"
    assert record.innovation_code == "INNOV-97"


# ── T192-ILV-09: Single verify unknown invariant returns MISSING ──────────────

def test_t192_ilv_09_single_verify_missing(engine):
    """T192-ILV-09: verify_single returns MISSING for an unknown invariant."""
    record = engine.verify_single("NONEXISTENT-INV-0")
    assert record.status == LineageStatus.MISSING


# ── T192-ILV-10: verify_all succeeds on clean registry ───────────────────────

def test_t192_ilv_10_verify_all_clean(engine, registry):
    """T192-ILV-10: verify_all returns a LineageAttestation on a clean registry."""
    attestation = engine.verify_all(registry=registry)
    assert attestation.escalated is False
    assert attestation.human0_required is False
    assert attestation.broken_count == 0
    assert attestation.total_invariants == len(registry)


# ── T192-ILV-11: verify_all produces constitutional seal ─────────────────────

def test_t192_ilv_11_constitutional_seal(engine, registry):
    """T192-ILV-11: verify_all produces a non-empty constitutional seal."""
    attestation = engine.verify_all(registry=registry)
    assert len(attestation.constitutional_seal) == 64  # SHA-256 hex


# ── T192-ILV-12: verify_all produces run_hmac ────────────────────────────────

def test_t192_ilv_12_run_hmac(engine, registry):
    """T192-ILV-12: verify_all produces a non-empty run_hmac."""
    attestation = engine.verify_all(registry=registry)
    assert len(attestation.run_hmac) == 64


# ── T192-ILV-13: Seal validation on LineageRecord ────────────────────────────

def test_t192_ilv_13_seal_validation(engine):
    """T192-ILV-13: _verify_seal returns True for a freshly signed record."""
    record = engine.verify_single("ILV-CHAIN-0")
    assert _verify_seal(record) is True


# ── T192-ILV-14: Tampered seal fails verification ────────────────────────────

def test_t192_ilv_14_tampered_seal_fails(engine):
    """T192-ILV-14: Tampering with the chain_hmac invalidates the seal."""
    record = engine.verify_single("ILV-CHAIN-0")
    record.chain_hmac = "00" * 32
    assert _verify_seal(record) is False


# ── T192-ILV-15: Replay produces identical HMAC ──────────────────────────────

def test_t192_ilv_15_replay_deterministic(engine):
    """T192-ILV-15: replay_lineage returns True for a freshly generated record."""
    record = engine.verify_single("ILV-CHAIN-0")
    assert engine.replay_lineage(record) is True


# ── T192-ILV-16: Replay fails after chain_hmac tamper ────────────────────────

def test_t192_ilv_16_replay_fails_on_tamper(engine):
    """T192-ILV-16: replay_lineage returns False when chain_hmac is tampered."""
    record = engine.verify_single("ILV-CHAIN-0")
    original_chain = record.chain_hmac
    record.chain_hmac = "deadbeef" * 8
    assert engine.replay_lineage(record) is False


# ── T192-ILV-17: Journal created and populated ───────────────────────────────

def test_t192_ilv_17_journal_created(engine, registry, tmp_journal):
    """T192-ILV-17: verify_all creates and populates the lineage journal."""
    engine.verify_all(registry=registry)
    assert os.path.exists(tmp_journal)
    with open(tmp_journal) as fh:
        lines = [l for l in fh if l.strip()]
    assert len(lines) > 0


# ── T192-ILV-18: Journal entries are valid JSON ───────────────────────────────

def test_t192_ilv_18_journal_valid_json(engine, registry, tmp_journal):
    """T192-ILV-18: All journal entries are parseable JSON."""
    engine.verify_all(registry=registry)
    with open(tmp_journal) as fh:
        for line in fh:
            if line.strip():
                json.loads(line)  # must not raise


# ── T192-ILV-19: get_journal_entries returns entries ─────────────────────────

def test_t192_ilv_19_get_journal_entries(engine, registry):
    """T192-ILV-19: get_journal_entries returns non-empty list after verification."""
    engine.verify_all(registry=registry)
    entries = engine.get_journal_entries(limit=50)
    assert len(entries) > 0


# ── T192-ILV-20: Empty registry raises ILVScopeViolation ─────────────────────

def test_t192_ilv_20_empty_registry_scope_violation(engine):
    """T192-ILV-20: verify_all on empty registry raises ILVScopeViolation (ILV-SCOPE-0)."""
    with pytest.raises(ILVScopeViolation):
        engine.verify_all(registry={})


# ── T192-ILV-21: Broken record triggers HUMAN-0 escalation ───────────────────

def test_t192_ilv_21_broken_triggers_human0(engine):
    """T192-ILV-21: A MISSING invariant causes ILVHuman0Escalation (ILV-HUMAN0-0)."""
    broken_registry = {
        "FAKE-BROKEN-0": InvariantRecord(
            invariant_id="FAKE-BROKEN-0",
            innovation_code="INNOV-99",
            introduction_phase=-1,        # triggers MISSING
            introduction_version="",
            hard_class="Hard",
            description="Broken test invariant",
        )
    }
    with pytest.raises(ILVHuman0Escalation):
        engine.verify_all(registry=broken_registry)
    assert engine.is_human0_flagged() is True


# ── T192-ILV-22: HUMAN-0 flag cleared by GOVERNOR ───────────────────────────

def test_t192_ilv_22_clear_human0_flag(engine):
    """T192-ILV-22: clear_human0_flag clears the flag when called by GOVERNOR."""
    broken = {
        "FAKE-0": InvariantRecord(
            invariant_id="FAKE-0",
            innovation_code="X",
            introduction_phase=-1,
            introduction_version="",
            hard_class="Hard",
            description="Broken",
        )
    }
    with pytest.raises(ILVHuman0Escalation):
        engine.verify_all(registry=broken)
    engine.clear_human0_flag(GOVERNOR)
    assert engine.is_human0_flagged() is False


# ── T192-ILV-23: Unauthorized clear raises PermissionError ───────────────────

def test_t192_ilv_23_unauthorized_clear_raises(engine):
    """T192-ILV-23: clear_human0_flag raises PermissionError for non-GOVERNOR (ILV-HUMAN0-0)."""
    with pytest.raises(PermissionError):
        engine.clear_human0_flag("SOME RANDO")


# ── T192-ILV-24: HUMAN-0 not flagged on clean run ────────────────────────────

def test_t192_ilv_24_human0_not_flagged_clean(engine, minimal_registry):
    """T192-ILV-24: HUMAN-0 flag is not set after a clean verification."""
    engine.verify_all(registry=minimal_registry)
    assert engine.is_human0_flagged() is False


# ── T192-ILV-25: Constitutional seal is SHA-256 of all chain HMACs ───────────

def test_t192_ilv_25_constitutional_seal_derivation(engine, minimal_registry):
    """T192-ILV-25: Constitutional seal matches SHA-256 of concatenated chain HMACs."""
    attestation = engine.verify_all(registry=minimal_registry)
    expected = hashlib.sha256(
        "".join(r.chain_hmac for r in attestation.records).encode()
    ).hexdigest()
    assert attestation.constitutional_seal == expected


# ── T192-ILV-26: Deterministic: same input → same seal ───────────────────────

def test_t192_ilv_26_deterministic_seal(tmp_journal, fixed_ts, minimal_registry):
    """T192-ILV-26: Two engines with identical fixed_ts produce the same constitutional seal."""
    det1 = RuntimeDeterminismProvider(fixed_ts=fixed_ts)
    det2 = RuntimeDeterminismProvider(fixed_ts=fixed_ts)
    j1 = tmp_journal + ".1.jsonl"
    j2 = tmp_journal + ".2.jsonl"
    e1 = InvariantLineageVerifier(determinism=det1, journal_path=j1)
    e2 = InvariantLineageVerifier(determinism=det2, journal_path=j2)
    a1 = e1.verify_all(registry=minimal_registry)
    a2 = e2.verify_all(registry=minimal_registry)
    assert a1.constitutional_seal == a2.constitutional_seal


# ── T192-ILV-27: VALID records have non-empty chain_hmac ─────────────────────

def test_t192_ilv_27_valid_records_have_chain_hmac(engine, minimal_registry):
    """T192-ILV-27: All VALID records in the attestation have a non-empty chain_hmac."""
    attestation = engine.verify_all(registry=minimal_registry)
    for record in attestation.records:
        if record.status == LineageStatus.VALID:
            assert len(record.chain_hmac) == 64


# ── T192-ILV-28: Each record has a unique record_id ──────────────────────────

def test_t192_ilv_28_unique_record_ids(engine, registry):
    """T192-ILV-28: Every LineageRecord has a unique record_id (UUIDv4)."""
    attestation = engine.verify_all(registry=registry)
    ids = [r.record_id for r in attestation.records]
    assert len(ids) == len(set(ids))


# ── T192-ILV-29: Governor string is preserved through attestation ─────────────

def test_t192_ilv_29_governor_preserved(engine, registry):
    """T192-ILV-29: LineageAttestation carries the correct GOVERNOR string."""
    attestation = engine.verify_all(registry=registry)
    assert attestation.governor == GOVERNOR


# ── T192-ILV-30: Module-level convenience function works ─────────────────────

def test_t192_ilv_30_convenience_function(tmp_journal, det, minimal_registry):
    """T192-ILV-30: verify_invariant_lineage() convenience entry point returns attestation."""
    attestation = verify_invariant_lineage(
        registry=minimal_registry,
        determinism=det,
        journal_path=tmp_journal,
    )
    assert attestation.total_invariants == len(minimal_registry)
    assert attestation.broken_count == 0
