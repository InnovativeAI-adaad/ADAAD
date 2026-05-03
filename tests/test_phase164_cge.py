# SPDX-License-Identifier: Apache-2.0
"""Phase 164 — INNOV-70 · CGE — Constitutional Genome Encoder — 30 acceptance tests.

Split:
  - 10 unit tests        (function-level, deterministic, no I/O beyond tmp_path)
  - 10 integration tests (multi-operation, ledger chain, merge workflows)
  - 10 invariant tests   (constitutional invariant enforcement)

Markers: phase164
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import uuid
from pathlib import Path
from typing import Dict, Tuple

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
DET_TS = "2026-05-02T00:00:00Z"
PHASE = 164


def _loci(n: int = 5, base: float = 0.5) -> Dict[str, Tuple[float, float, str, bool]]:
    """Generate n synthetic loci inputs."""
    return {
        f"locus_{i:02d}": (
            round(base + i * 0.01, 4),
            round(0.7 + i * 0.01, 4),
            f"INV-{i:02d}",
            i % 3 == 0,
        )
        for i in range(n)
    }


@pytest.fixture()
def engine(tmp_path):
    from runtime.innovations30.constitutional_genome_encoder import ConstitutionalGenomeEncoder
    return ConstitutionalGenomeEncoder(
        ledger_path=tmp_path / "genome_audit.jsonl",
        secret=b"test-secret",
        det_timestamp=DET_TS,
    )


@pytest.fixture()
def two_engines(tmp_path):
    from runtime.innovations30.constitutional_genome_encoder import ConstitutionalGenomeEncoder
    e1 = ConstitutionalGenomeEncoder(
        ledger_path=tmp_path / "e1.jsonl",
        secret=b"test-secret",
        det_timestamp=DET_TS,
    )
    e2 = ConstitutionalGenomeEncoder(
        ledger_path=tmp_path / "e2.jsonl",
        secret=b"test-secret",
        det_timestamp=DET_TS,
    )
    return e1, e2


# ===========================================================================
# UNIT TESTS — T164-CGE-01..10
# ===========================================================================

@pytest.mark.phase164
def test_T164_CGE_01_encode_returns_genome_vector(engine):
    """T164-CGE-01: encode_genome returns a valid GenomeVector."""
    from runtime.innovations30.constitutional_genome_encoder import GenomeVector
    gv = engine.encode_genome(PHASE, _loci(5), timestamp_utc=DET_TS)
    assert isinstance(gv, GenomeVector)
    assert gv.phase == PHASE
    assert gv.governor == "DUSTIN L REID"


@pytest.mark.phase164
def test_T164_CGE_02_genome_hash_is_deterministic(tmp_path):
    """T164-CGE-02: same loci always produce the same genome_hash (CGE-ENCODE-0)."""
    from runtime.innovations30.constitutional_genome_encoder import ConstitutionalGenomeEncoder
    loci = _loci(5)
    g1 = ConstitutionalGenomeEncoder(tmp_path / "a.jsonl", b"s", DET_TS).encode_genome(PHASE, loci, DET_TS)
    g2 = ConstitutionalGenomeEncoder(tmp_path / "b.jsonl", b"s", DET_TS).encode_genome(PHASE, loci, DET_TS)
    assert g1.genome_hash == g2.genome_hash


@pytest.mark.phase164
def test_T164_CGE_03_verify_passes_on_valid_genome(engine):
    """T164-CGE-03: verify_genome returns True for a freshly encoded genome."""
    gv = engine.encode_genome(PHASE, _loci(4), DET_TS)
    assert engine.verify_genome(gv) is True


@pytest.mark.phase164
def test_T164_CGE_04_locus_map_index(engine):
    """T164-CGE-04: locus_map() returns a dict keyed by locus name."""
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    lm = gv.locus_map()
    for i in range(3):
        assert f"locus_{i:02d}" in lm


@pytest.mark.phase164
def test_T164_CGE_05_overall_fitness_is_mean(engine):
    """T164-CGE-05: overall_fitness() equals mean fitness_score of loci."""
    loci = _loci(4)
    gv = engine.encode_genome(PHASE, loci, DET_TS)
    expected = sum(v[1] for v in loci.values()) / len(loci)
    assert abs(gv.overall_fitness() - expected) < 1e-9


@pytest.mark.phase164
def test_T164_CGE_06_allele_hash_is_16_hex(engine):
    """T164-CGE-06: each locus allele_hash is exactly 16 hex characters."""
    gv = engine.encode_genome(PHASE, _loci(5), DET_TS)
    for locus in gv.loci:
        ah = locus.allele_hash()
        assert len(ah) == 16
        int(ah, 16)  # must be valid hex


@pytest.mark.phase164
def test_T164_CGE_07_genome_id_is_valid_uuid(engine):
    """T164-CGE-07: genome_id is a valid UUID string."""
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    uuid.UUID(gv.genome_id)  # raises ValueError if invalid


@pytest.mark.phase164
def test_T164_CGE_08_max_loci_enforced(engine):
    """T164-CGE-08: encoding more than MAX_LOCI loci raises CGELociError."""
    from runtime.innovations30.constitutional_genome_encoder import CGELociError, MAX_LOCI
    oversized = _loci(MAX_LOCI + 1)
    with pytest.raises(CGELociError):
        engine.encode_genome(PHASE, oversized, DET_TS)


@pytest.mark.phase164
def test_T164_CGE_09_prev_genome_hash_chain_root_on_first(engine):
    """T164-CGE-09: first genome has prev_genome_hash == CHAIN_ROOT."""
    from runtime.innovations30.constitutional_genome_encoder import CHAIN_ROOT
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    assert gv.prev_genome_hash == CHAIN_ROOT


@pytest.mark.phase164
def test_T164_CGE_10_second_genome_chains_to_first(engine):
    """T164-CGE-10: second genome's prev_genome_hash == first genome's genome_hash."""
    gv1 = engine.encode_genome(PHASE, _loci(3), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(4, base=0.6), DET_TS)
    assert gv2.prev_genome_hash == gv1.genome_hash


# ===========================================================================
# INTEGRATION TESTS — T164-CGE-11..20
# ===========================================================================

@pytest.mark.phase164
def test_T164_CGE_11_diff_returns_genome_diff(engine):
    """T164-CGE-11: diff_genomes returns a GenomeDiff."""
    from runtime.innovations30.constitutional_genome_encoder import GenomeDiff
    gv1 = engine.encode_genome(PHASE, _loci(5), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(5, base=0.8), DET_TS)
    diff = engine.diff_genomes(gv1, gv2, DET_TS)
    assert isinstance(diff, GenomeDiff)
    assert diff.left_genome_id == gv1.genome_id
    assert diff.right_genome_id == gv2.genome_id


@pytest.mark.phase164
def test_T164_CGE_12_diff_self_raises(engine):
    """T164-CGE-12: diffing a genome against itself raises CGEError."""
    from runtime.innovations30.constitutional_genome_encoder import CGEError
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    with pytest.raises(CGEError):
        engine.diff_genomes(gv, gv, DET_TS)


@pytest.mark.phase164
def test_T164_CGE_13_divergence_score_zero_for_identical_loci(tmp_path):
    """T164-CGE-13: identical loci → divergence_score == 0.0."""
    from runtime.innovations30.constitutional_genome_encoder import ConstitutionalGenomeEncoder
    loci = _loci(5)
    e1 = ConstitutionalGenomeEncoder(tmp_path / "a.jsonl", b"s", DET_TS)
    e2 = ConstitutionalGenomeEncoder(tmp_path / "b.jsonl", b"s", DET_TS)
    gv1 = e1.encode_genome(PHASE, loci, DET_TS)
    gv2 = e2.encode_genome(PHASE, loci, DET_TS)
    # Must use same engine for diff; produce from single engine
    from runtime.innovations30.constitutional_genome_encoder import ConstitutionalGenomeEncoder
    e3 = ConstitutionalGenomeEncoder(tmp_path / "c.jsonl", b"s", DET_TS)
    g3a = e3.encode_genome(PHASE, loci, DET_TS)
    g3b = e3.encode_genome(PHASE, loci, DET_TS)
    # identical loci but different genome_id (different chain position) — diff should be zero score
    diff = e3.diff_genomes(g3a, g3b, DET_TS)
    assert diff.divergence_score == 0.0


@pytest.mark.phase164
def test_T164_CGE_14_high_divergence_sets_requires_human0(engine):
    """T164-CGE-14: large value differences set requires_human0=True."""
    from runtime.innovations30.constitutional_genome_encoder import MERGE_HUMAN0_GATE
    gv1 = engine.encode_genome(PHASE, _loci(5, base=0.0), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(5, base=1.0), DET_TS)
    diff = engine.diff_genomes(gv1, gv2, DET_TS)
    assert diff.requires_human0 is True
    assert diff.divergence_score > MERGE_HUMAN0_GATE


@pytest.mark.phase164
def test_T164_CGE_15_merge_fitter_wins_selects_higher_fitness(engine):
    """T164-CGE-15: FITTER_WINS merge picks locus with higher fitness_score."""
    from runtime.innovations30.constitutional_genome_encoder import MergeStrategy
    loci_l = {"shared": (0.3, 0.5, "INV-L", False)}
    loci_r = {"shared": (0.7, 0.9, "INV-R", False)}
    gv1 = engine.encode_genome(PHASE, loci_l, DET_TS)
    gv2 = engine.encode_genome(PHASE, loci_r, DET_TS)
    # single locus; divergence_score == 1.0 → must override
    merged, record = engine.merge_genomes(gv1, gv2, MergeStrategy.FITTER_WINS, DET_TS, human0_override=True)
    lm = merged.locus_map()
    assert abs(lm["shared"].value - 0.7) < 1e-9  # right wins (fitness 0.9 > 0.5)


@pytest.mark.phase164
def test_T164_CGE_16_merge_dominant_always_picks_left(engine):
    """T164-CGE-16: DOMINANT strategy always picks left genome's locus."""
    from runtime.innovations30.constitutional_genome_encoder import MergeStrategy
    loci_l = {"dom": (0.2, 0.4, "INV-L", False)}
    loci_r = {"dom": (0.9, 0.95, "INV-R", False)}
    gv1 = engine.encode_genome(PHASE, loci_l, DET_TS)
    gv2 = engine.encode_genome(PHASE, loci_r, DET_TS)
    merged, _ = engine.merge_genomes(gv1, gv2, MergeStrategy.DOMINANT, DET_TS, human0_override=True)
    lm = merged.locus_map()
    assert abs(lm["dom"].value - 0.2) < 1e-9


@pytest.mark.phase164
def test_T164_CGE_17_merge_record_governor_is_human0(engine):
    """T164-CGE-17: MergeRecord governor == DUSTIN L REID."""
    from runtime.innovations30.constitutional_genome_encoder import MergeStrategy
    gv1 = engine.encode_genome(PHASE, _loci(3), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(3, base=0.55), DET_TS)
    _, record = engine.merge_genomes(gv1, gv2, MergeStrategy.FITTER_WINS, DET_TS)
    assert record.governor == "DUSTIN L REID"


@pytest.mark.phase164
def test_T164_CGE_18_genome_history_ordered_by_seq(engine):
    """T164-CGE-18: genome_history() returns records in ascending ledger_seq order."""
    for i in range(4):
        engine.encode_genome(PHASE, _loci(i + 2), DET_TS)
    history = engine.genome_history()
    seqs = [h["ledger_seq"] for h in history]
    assert seqs == sorted(seqs)


@pytest.mark.phase164
def test_T164_CGE_19_audit_trail_contains_operations(engine):
    """T164-CGE-19: audit trail records encode and diff operations."""
    gv1 = engine.encode_genome(PHASE, _loci(3), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(4), DET_TS)
    engine.diff_genomes(gv1, gv2, DET_TS)
    trail = engine.audit_trail()
    ops = {e["operation"] for e in trail}
    assert "encode" in ops
    assert "diff" in ops


@pytest.mark.phase164
def test_T164_CGE_20_ledger_is_append_only_jsonl(engine):
    """T164-CGE-20: each ledger entry is valid JSON on its own line."""
    engine.encode_genome(PHASE, _loci(3), DET_TS)
    engine.encode_genome(PHASE, _loci(4), DET_TS)
    ledger_path = engine.ledger_path
    for line in ledger_path.read_text().splitlines():
        if line.strip():
            json.loads(line)  # must not raise


# ===========================================================================
# INVARIANT TESTS — T164-CGE-21..30
# ===========================================================================

@pytest.mark.phase164
def test_T164_CGE_21_verify_detects_tampered_hash(engine):
    """T164-CGE-21: CGEVerifyError on tampered genome_hash (CGE-CHAIN-0)."""
    from runtime.innovations30.constitutional_genome_encoder import CGEVerifyError, GenomeVector
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    tampered = GenomeVector(
        genome_id=gv.genome_id,
        version=gv.version,
        phase=gv.phase,
        governor=gv.governor,
        loci=gv.loci,
        genome_hash="deadbeef" * 8,  # tampered
        prev_genome_hash=gv.prev_genome_hash,
        chain_hmac=gv.chain_hmac,
        ledger_seq=gv.ledger_seq,
        timestamp_utc=gv.timestamp_utc,
        metadata=gv.metadata,
    )
    with pytest.raises(CGEVerifyError):
        engine.verify_genome(tampered)


@pytest.mark.phase164
def test_T164_CGE_22_verify_detects_tampered_hmac(engine):
    """T164-CGE-22: CGEVerifyError on tampered chain_hmac (CGE-CHAIN-0)."""
    from runtime.innovations30.constitutional_genome_encoder import CGEVerifyError, GenomeVector
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    tampered = GenomeVector(
        genome_id=gv.genome_id,
        version=gv.version,
        phase=gv.phase,
        governor=gv.governor,
        loci=gv.loci,
        genome_hash=gv.genome_hash,
        prev_genome_hash=gv.prev_genome_hash,
        chain_hmac="0" * 64,  # tampered
        ledger_seq=gv.ledger_seq,
        timestamp_utc=gv.timestamp_utc,
        metadata=gv.metadata,
    )
    with pytest.raises(CGEVerifyError):
        engine.verify_genome(tampered)


@pytest.mark.phase164
def test_T164_CGE_23_merge_self_raises_CGEMergeError(engine):
    """T164-CGE-23: merging genome with itself raises CGEMergeError (CGE-MERGE-0)."""
    from runtime.innovations30.constitutional_genome_encoder import CGEMergeError
    gv = engine.encode_genome(PHASE, _loci(3), DET_TS)
    with pytest.raises(CGEMergeError):
        engine.merge_genomes(gv, gv, timestamp_utc=DET_TS, human0_override=True)


@pytest.mark.phase164
def test_T164_CGE_24_human0_gate_enforced_without_override(engine):
    """T164-CGE-24: CGEHuman0Gate raised when divergence high and human0_override=False (CGE-HUMAN0-0)."""
    from runtime.innovations30.constitutional_genome_encoder import CGEHuman0Gate
    gv1 = engine.encode_genome(PHASE, _loci(5, base=0.0), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(5, base=1.0), DET_TS)
    with pytest.raises(CGEHuman0Gate):
        engine.merge_genomes(gv1, gv2, timestamp_utc=DET_TS, human0_override=False)


@pytest.mark.phase164
def test_T164_CGE_25_human0_gate_bypassed_with_override(engine):
    """T164-CGE-25: merge proceeds when human0_override=True even at high divergence."""
    gv1 = engine.encode_genome(PHASE, _loci(5, base=0.0), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(5, base=1.0), DET_TS)
    merged, record = engine.merge_genomes(gv1, gv2, timestamp_utc=DET_TS, human0_override=True)
    assert merged is not None
    assert record.human0_required is True


@pytest.mark.phase164
def test_T164_CGE_26_merge_produces_new_genome_id(engine):
    """T164-CGE-26: merged genome has a different genome_id from both inputs (CGE-MERGE-0)."""
    gv1 = engine.encode_genome(PHASE, _loci(3), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(3, base=0.55), DET_TS)
    merged, _ = engine.merge_genomes(gv1, gv2, timestamp_utc=DET_TS)
    assert merged.genome_id not in {gv1.genome_id, gv2.genome_id}


@pytest.mark.phase164
def test_T164_CGE_27_diff_does_not_mutate_inputs(engine):
    """T164-CGE-27: diff_genomes does not alter either input genome (CGE-DIFF-0)."""
    gv1 = engine.encode_genome(PHASE, _loci(4), DET_TS)
    gv2 = engine.encode_genome(PHASE, _loci(4, base=0.7), DET_TS)
    hash1_before = gv1.genome_hash
    hash2_before = gv2.genome_hash
    engine.diff_genomes(gv1, gv2, DET_TS)
    assert gv1.genome_hash == hash1_before
    assert gv2.genome_hash == hash2_before


@pytest.mark.phase164
def test_T164_CGE_28_governor_constant_enforced(engine):
    """T164-CGE-28: every encoded genome has governor == DUSTIN L REID."""
    for i in range(3):
        gv = engine.encode_genome(PHASE + i, _loci(2 + i), DET_TS)
        assert gv.governor == "DUSTIN L REID"


@pytest.mark.phase164
def test_T164_CGE_29_loci_sorted_deterministically(tmp_path):
    """T164-CGE-29: loci ordering is deterministic regardless of input dict order (CGE-DETERM-0)."""
    from runtime.innovations30.constitutional_genome_encoder import ConstitutionalGenomeEncoder
    loci_fwd = {"a_locus": (0.1, 0.5, "INV-A", False), "z_locus": (0.9, 0.8, "INV-Z", True)}
    loci_rev = {"z_locus": (0.9, 0.8, "INV-Z", True), "a_locus": (0.1, 0.5, "INV-A", False)}
    e1 = ConstitutionalGenomeEncoder(tmp_path / "fwd.jsonl", b"s", DET_TS)
    e2 = ConstitutionalGenomeEncoder(tmp_path / "rev.jsonl", b"s", DET_TS)
    gv1 = e1.encode_genome(PHASE, loci_fwd, DET_TS)
    gv2 = e2.encode_genome(PHASE, loci_rev, DET_TS)
    assert gv1.genome_hash == gv2.genome_hash


@pytest.mark.phase164
def test_T164_CGE_30_is_hard_class_propagated_through_merge(engine):
    """T164-CGE-30: is_hard_class flag is preserved through merge operations."""
    from runtime.innovations30.constitutional_genome_encoder import MergeStrategy
    loci_l = {"hard_locus": (0.5, 0.6, "HARD-INV", True)}
    loci_r = {"soft_locus": (0.5, 0.5, "SOFT-INV", False)}
    gv1 = engine.encode_genome(PHASE, loci_l, DET_TS)
    gv2 = engine.encode_genome(PHASE, loci_r, DET_TS)
    merged, _ = engine.merge_genomes(gv1, gv2, MergeStrategy.FITTER_WINS, DET_TS, human0_override=True)
    lm = merged.locus_map()
    assert lm["hard_locus"].is_hard_class is True
    assert lm["soft_locus"].is_hard_class is False
