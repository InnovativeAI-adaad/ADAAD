# tests/innovations/test_phase135_cvr.py
# Phase 135 · INNOV-43 · Constitution Versioning and Rollback (CVR)
# 30 tests — must pass 30/30

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from runtime.innovations30.constitution_version_ledger import (
    CONSTITUTIONAL_INVARIANTS,
    GENESIS_PREV_HASH,
    INNOV_ID,
    PHASE,
    VERSION,
    WORLD_FIRST,
    CVLAuthorizationViolation,
    CVLChainViolation,
    CVLDigestViolation,
    CVLImmutabilityViolation,
    CVLRollbackViolation,
    ConstitutionVersion,
    ConstitutionVersionLedger,
    _compute_content_digest,
    _compute_entry_hash,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_ledger(tmp_path):
    """Fresh ledger backed by a temp file."""
    return ConstitutionVersionLedger(path=tmp_path / "cvl.jsonl")


@pytest.fixture
def seeded_ledger(tmp_path):
    """Ledger with two committed amendments."""
    cvl = ConstitutionVersionLedger(path=tmp_path / "cvl.jsonl")
    cvl.commit("Amendment alpha text.", "AMEND-001", "constitution-v1.0.0", 100)
    cvl.commit("Amendment beta text.", "AMEND-002", "constitution-v1.1.0", 101)
    return cvl


# ── Metadata ──────────────────────────────────────────────────────────────────
def test_cvr_01_innov_id():
    assert INNOV_ID == "INNOV-43"


def test_cvr_02_phase():
    assert PHASE == 135


def test_cvr_03_version():
    assert VERSION == "9.67.0"


def test_cvr_04_world_first_non_empty():
    assert len(WORLD_FIRST) > 20


def test_cvr_05_invariants_count():
    assert len(CONSTITUTIONAL_INVARIANTS) == 5
    assert "CVR-IMMUT-0" in CONSTITUTIONAL_INVARIANTS
    assert "CVR-DIGEST-0" in CONSTITUTIONAL_INVARIANTS
    assert "CVR-ROLLBACK-0" in CONSTITUTIONAL_INVARIANTS
    assert "CVR-HUMAN0-0" in CONSTITUTIONAL_INVARIANTS
    assert "CVR-CHAIN-0" in CONSTITUTIONAL_INVARIANTS


# ── Commit: basic behaviour ───────────────────────────────────────────────────
def test_cvr_06_commit_appends_entry(tmp_ledger):
    tmp_ledger.commit("First amendment.", "AMEND-001", "constitution-v1.0.0", 135)
    assert len(tmp_ledger._cache) == 1


def test_cvr_07_commit_digest_stored_correctly(tmp_ledger):
    text = "Deterministic amendment content."
    entry = tmp_ledger.commit(text, "AMEND-001", "constitution-v1.0.0", 135)
    expected = hashlib.sha256(text.encode()).hexdigest()
    assert entry.content_digest == expected


def test_cvr_08_genesis_prev_hash(tmp_ledger):
    entry = tmp_ledger.commit("Genesis text.", "AMEND-001", "constitution-v1.0.0", 135)
    assert entry.prev_hash == GENESIS_PREV_HASH


def test_cvr_09_second_entry_chains_first(tmp_ledger):
    e1 = tmp_ledger.commit("First.", "AMEND-001", "constitution-v1.0.0", 135)
    e2 = tmp_ledger.commit("Second.", "AMEND-002", "constitution-v1.1.0", 135)
    assert e2.prev_hash == e1.entry_hash


def test_cvr_10_entry_hash_deterministic(tmp_ledger):
    e = tmp_ledger.commit("Text.", "AMEND-001", "constitution-v1.0.0", 135)
    recomputed = _compute_entry_hash(e.to_dict())
    assert e.entry_hash == recomputed


# ── Immutability ──────────────────────────────────────────────────────────────
def test_cvr_11_file_is_appended_not_overwritten(tmp_ledger):
    tmp_ledger.commit("First.", "AMEND-001", "constitution-v1.0.0", 135)
    tmp_ledger.commit("Second.", "AMEND-002", "constitution-v1.1.0", 135)
    lines = tmp_ledger._path.read_text().splitlines()
    assert len([l for l in lines if l.strip()]) == 2


def test_cvr_12_mutated_entry_hash_detected_on_reload(tmp_ledger):
    tmp_ledger.commit("Text.", "AMEND-001", "constitution-v1.0.0", 135)
    # Corrupt entry_hash in file
    lines = tmp_ledger._path.read_text().splitlines()
    d = json.loads(lines[0])
    d["entry_hash"] = "deadbeef" * 8
    tmp_ledger._path.write_text(json.dumps(d) + "\n")
    with pytest.raises(CVLChainViolation):
        ConstitutionVersionLedger(path=tmp_ledger._path)


def test_cvr_13_mutated_prev_hash_detected_on_reload(tmp_ledger):
    tmp_ledger.commit("First.", "AMEND-001", "constitution-v1.0.0", 135)
    tmp_ledger.commit("Second.", "AMEND-002", "constitution-v1.1.0", 135)
    lines = tmp_ledger._path.read_text().splitlines()
    d = json.loads(lines[1])
    d["prev_hash"] = "badbadbad" * 7 + "bad"
    tmp_ledger._path.write_text(lines[0] + "\n" + json.dumps(d) + "\n")
    with pytest.raises(CVLChainViolation):
        ConstitutionVersionLedger(path=tmp_ledger._path)


# ── Chain verify ──────────────────────────────────────────────────────────────
def test_cvr_14_verify_chain_passes_clean_ledger(seeded_ledger):
    assert seeded_ledger.verify_chain() is True


def test_cvr_15_verify_chain_empty_ledger(tmp_ledger):
    assert tmp_ledger.verify_chain() is True


def test_cvr_16_verify_chain_detects_broken_link(seeded_ledger):
    # Manually corrupt cache entry
    seeded_ledger._cache[1] = ConstitutionVersion(
        **{**seeded_ledger._cache[1].to_dict(), "prev_hash": "0" * 64}
    )
    with pytest.raises(CVLChainViolation):
        seeded_ledger.verify_chain()


def test_cvr_17_verify_chain_detects_entry_hash_mismatch(seeded_ledger):
    d = seeded_ledger._cache[0].to_dict()
    d["entry_hash"] = "ff" * 32
    seeded_ledger._cache[0] = ConstitutionVersion.from_dict(d)
    with pytest.raises(CVLChainViolation):
        seeded_ledger.verify_chain()


# ── Rollback ──────────────────────────────────────────────────────────────────
def test_cvr_18_valid_rollback_creates_forward_entry(seeded_ledger):
    before = len(seeded_ledger._cache)
    seeded_ledger.rollback("constitution-v1.0.0", "HUMAN0-TEST-TOKEN", 135)
    assert len(seeded_ledger._cache) == before + 1


def test_cvr_19_rollback_entry_has_rollback_of_set(seeded_ledger):
    entry = seeded_ledger.rollback("constitution-v1.0.0", "HUMAN0-TEST-TOKEN", 135)
    assert entry.rollback_of == "constitution-v1.0.0"


def test_cvr_20_rollback_prior_entry_still_present(seeded_ledger):
    seeded_ledger.rollback("constitution-v1.0.0", "HUMAN0-TEST-TOKEN", 135)
    ids = [e.version_id for e in seeded_ledger._cache]
    assert "constitution-v1.0.0" in ids


def test_cvr_21_rollback_missing_token_raises(seeded_ledger):
    with pytest.raises(CVLAuthorizationViolation):
        seeded_ledger.rollback("constitution-v1.0.0", "", 135)


def test_cvr_22_rollback_none_token_raises(seeded_ledger):
    with pytest.raises((CVLAuthorizationViolation, TypeError)):
        seeded_ledger.rollback("constitution-v1.0.0", None, 135)  # type: ignore


def test_cvr_23_rollback_unknown_target_raises(seeded_ledger):
    with pytest.raises(CVLRollbackViolation):
        seeded_ledger.rollback("constitution-v99.0.0", "HUMAN0-TEST-TOKEN", 135)


def test_cvr_24_rollback_entry_is_chained(seeded_ledger):
    tail_before = seeded_ledger._prev_hash
    entry = seeded_ledger.rollback("constitution-v1.0.0", "HUMAN0-TEST-TOKEN", 135)
    assert entry.prev_hash == tail_before


# ── Blame ─────────────────────────────────────────────────────────────────────
def test_cvr_25_blame_resolves_amendment_id(seeded_ledger):
    entry = seeded_ledger.blame("AMEND-001")
    assert entry.amendment_id == "AMEND-001"


def test_cvr_26_blame_returns_correct_phase(seeded_ledger):
    entry = seeded_ledger.blame("AMEND-001")
    assert entry.phase == 100


def test_cvr_27_blame_returns_correct_digest(seeded_ledger):
    entry = seeded_ledger.blame("AMEND-001")
    expected = _compute_content_digest("Amendment alpha text.")
    assert entry.content_digest == expected


def test_cvr_28_blame_unknown_raises_key_error(seeded_ledger):
    with pytest.raises(KeyError):
        seeded_ledger.blame("AMEND-UNKNOWN")


# ── History ───────────────────────────────────────────────────────────────────
def test_cvr_29_history_newest_first(seeded_ledger):
    entries = seeded_ledger.history(limit=10)
    assert entries[0].amendment_id == "AMEND-002"
    assert entries[1].amendment_id == "AMEND-001"


def test_cvr_30_determinism_identical_text_same_digest(tmp_ledger):
    text = "Canonical amendment content for determinism test."
    d1 = _compute_content_digest(text)
    d2 = _compute_content_digest(text)
    assert d1 == d2 == hashlib.sha256(text.encode()).hexdigest()
