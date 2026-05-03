# SPDX-License-Identifier: Apache-2.0
"""Phase 166 · INNOV-72 · GAE — Genome Alignment Engine — 30-test suite.

T166-GAE-01..30 — Grade-A · 30/30 target
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dorkllm.genome_alignment_engine import (
    GOVERNOR,
    GAE_DRIFT_GATE,
    GAE_VERSION,
    _AMENDMENT_HASH,
    _AMENDMENT_TEXT,
    AlignmentStatus,
    DimensionResult,
    GAEChainError,
    GAEHuman0Flag,
    GAEScopeError,
    GenomeAlignmentEngine,
    GenomeAlignmentReport,
    get_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _engine(tmp_path: Path) -> GenomeAlignmentEngine:
    return GenomeAlignmentEngine(ledger_path=tmp_path / "genome_alignment.jsonl")


def _aligned_inputs(tag: str = "v9.99.0") -> dict:
    return {
        "baseline_tag": tag,
        "baseline_genome": {
            "version": "9.99.0",
            "commit_sha": "abc123def456",
            "invariant_count": "320",
        },
        "current_genome": {
            "version": "9.99.0",
            "commit_sha": "abc123def456",
            "invariant_count": "320",
        },
    }


def _drifted_inputs(tag: str = "v9.98.0") -> dict:
    return {
        "baseline_tag": tag,
        "baseline_genome": {
            "version": "9.98.0",
            "commit_sha": "oldsha111",
            "invariant_count": "310",
        },
        "current_genome": {
            "version": "9.99.0",
            "commit_sha": "newsha222",
            "invariant_count": "320",
        },
    }


# ===========================================================================
# T166-GAE-01  Module imports without error
# ===========================================================================
def test_t166_gae_01_import():
    from dorkllm import genome_alignment_engine  # noqa: F401
    assert genome_alignment_engine.GOVERNOR == "DUSTIN L REID"


# ===========================================================================
# T166-GAE-02  GOVERNOR constant correct
# ===========================================================================
def test_t166_gae_02_governor():
    assert GOVERNOR == "DUSTIN L REID"


# ===========================================================================
# T166-GAE-03  Amendment text hashes correctly (GAE-AMEND-0)
# ===========================================================================
def test_t166_gae_03_amendment_hash():
    expected = hashlib.sha256(_AMENDMENT_TEXT.encode()).hexdigest()
    assert _AMENDMENT_HASH == expected


# ===========================================================================
# T166-GAE-04  Engine instantiates with clean ledger
# ===========================================================================
def test_t166_gae_04_instantiation(tmp_path):
    eng = _engine(tmp_path)
    assert eng is not None
    assert eng.history() == []


# ===========================================================================
# T166-GAE-05  Fully aligned genomes score 1.0
# ===========================================================================
def test_t166_gae_05_full_alignment(tmp_path):
    eng = _engine(tmp_path)
    report = eng.align(_aligned_inputs())
    assert report.alignment_score == 1.0
    assert report.status == AlignmentStatus.ALIGNED


# ===========================================================================
# T166-GAE-06  Aligned report has human0_review_required=False
# ===========================================================================
def test_t166_gae_06_no_human0_flag_when_aligned(tmp_path):
    eng = _engine(tmp_path)
    report = eng.align(_aligned_inputs())
    assert report.human0_review_required is False


# ===========================================================================
# T166-GAE-07  Drifted genomes raise GAEHuman0Flag (GAE-HUMAN0-0)
# ===========================================================================
def test_t166_gae_07_human0_flag_on_drift(tmp_path):
    eng = _engine(tmp_path)
    with pytest.raises(GAEHuman0Flag):
        eng.align(_drifted_inputs())


# ===========================================================================
# T166-GAE-08  Drifted report still appended to ledger (GAE-PERSIST-0)
# ===========================================================================
def test_t166_gae_08_drifted_still_persisted(tmp_path):
    eng = _engine(tmp_path)
    try:
        eng.align(_drifted_inputs())
    except GAEHuman0Flag:
        pass
    assert len(eng.history()) == 1


# ===========================================================================
# T166-GAE-09  score() returns float in [0.0, 1.0]
# ===========================================================================
def test_t166_gae_09_score_range(tmp_path):
    eng = _engine(tmp_path)
    s = eng.score(_aligned_inputs())
    assert 0.0 <= s <= 1.0
    assert s == 1.0


# ===========================================================================
# T166-GAE-10  score() on drifted inputs returns < 1.0
# ===========================================================================
def test_t166_gae_10_score_drifted(tmp_path):
    eng = _engine(tmp_path)
    s = eng.score(_drifted_inputs())
    assert s < 1.0


# ===========================================================================
# T166-GAE-11  Exactly three canonical dimensions evaluated (GAE-SCOPE-0)
# ===========================================================================
def test_t166_gae_11_canonical_dimensions(tmp_path):
    eng = _engine(tmp_path)
    report = eng.align(_aligned_inputs())
    dim_names = {d.dimension for d in report.dimensions}
    assert dim_names == {"version", "commit_sha", "invariant_count"}


# ===========================================================================
# T166-GAE-12  report_id is deterministic for same inputs
# ===========================================================================
def test_t166_gae_12_deterministic_report_id(tmp_path):
    eng1 = _engine(tmp_path / "a")
    eng2 = GenomeAlignmentEngine(ledger_path=tmp_path / "b" / "ledger.jsonl")
    inp = _aligned_inputs()
    r1 = eng1.align(inp)
    r2 = eng2.align(inp)
    assert r1.report_id == r2.report_id


# ===========================================================================
# T166-GAE-13  HMAC chain initialises from CHAIN_ROOT on empty ledger
# ===========================================================================
def test_t166_gae_13_chain_root_on_empty(tmp_path):
    eng = _engine(tmp_path)
    report = eng.align(_aligned_inputs())
    assert report.prev_digest == "0" * 64


# ===========================================================================
# T166-GAE-14  Second report chains to first (GAE-CHAIN-0)
# ===========================================================================
def test_t166_gae_14_chaining(tmp_path):
    eng = _engine(tmp_path)
    r1 = eng.align(_aligned_inputs("v9.99.0"))
    r2 = eng.align(_aligned_inputs("v9.100.0"))
    assert r2.prev_digest == r1.chain_digest


# ===========================================================================
# T166-GAE-15  verify_chain() returns True on valid chain
# ===========================================================================
def test_t166_gae_15_verify_chain_valid(tmp_path):
    eng = _engine(tmp_path)
    eng.align(_aligned_inputs())
    eng.align(_aligned_inputs("v9.100.0"))
    assert eng.verify_chain() is True


# ===========================================================================
# T166-GAE-16  verify_chain() raises GAEChainError on tampered ledger
# ===========================================================================
def test_t166_gae_16_verify_chain_tampered(tmp_path):
    eng = _engine(tmp_path)
    eng.align(_aligned_inputs())
    ledger = tmp_path / "genome_alignment.jsonl"
    content = ledger.read_text()
    tampered = content.replace("1.0", "0.9")
    ledger.write_text(tampered)
    with pytest.raises(GAEChainError):
        eng.verify_chain()


# ===========================================================================
# T166-GAE-17  history() returns all appended records in order
# ===========================================================================
def test_t166_gae_17_history_order(tmp_path):
    eng = _engine(tmp_path)
    eng.align(_aligned_inputs("v9.99.0"))
    eng.align(_aligned_inputs("v9.100.0"))
    h = eng.history()
    assert len(h) == 2
    assert h[0]["baseline_tag"] == "v9.99.0"
    assert h[1]["baseline_tag"] == "v9.100.0"


# ===========================================================================
# T166-GAE-18  amendment() returns correct amendment_id
# ===========================================================================
def test_t166_gae_18_amendment_id(tmp_path):
    eng = _engine(tmp_path)
    amend = eng.amendment()
    assert amend["amendment_id"] == "CA-GAE-001"


# ===========================================================================
# T166-GAE-19  amendment() hash matches module-level constant
# ===========================================================================
def test_t166_gae_19_amendment_hash_matches(tmp_path):
    eng = _engine(tmp_path)
    amend = eng.amendment()
    assert amend["sha256"] == _AMENDMENT_HASH


# ===========================================================================
# T166-GAE-20  amendment() specifies GA_ALIGNMENT as redefined criterion
# ===========================================================================
def test_t166_gae_20_amendment_criterion(tmp_path):
    eng = _engine(tmp_path)
    amend = eng.amendment()
    assert amend["redefines_criterion"] == "GA_ALIGNMENT"


# ===========================================================================
# T166-GAE-21  amendment() has ratification_required=True
# ===========================================================================
def test_t166_gae_21_amendment_ratification_required(tmp_path):
    eng = _engine(tmp_path)
    amend = eng.amendment()
    assert amend["ratification_required"] is True


# ===========================================================================
# T166-GAE-22  Partial dimension match returns fractional score
# ===========================================================================
def test_t166_gae_22_partial_score(tmp_path):
    eng = _engine(tmp_path)
    inp = {
        "baseline_tag": "v9.98.0",
        "baseline_genome": {
            "version": "9.98.0",
            "commit_sha": "same_sha",
            "invariant_count": "310",
        },
        "current_genome": {
            "version": "9.99.0",  # differs
            "commit_sha": "same_sha",  # same
            "invariant_count": "310",  # same
        },
    }
    s = eng.score(inp)
    assert s == pytest.approx(2 / 3, rel=1e-5)


# ===========================================================================
# T166-GAE-23  Empty baseline genome scores 0.0
# ===========================================================================
def test_t166_gae_23_empty_baseline(tmp_path):
    eng = _engine(tmp_path)
    inp = {
        "baseline_tag": "v9.98.0",
        "baseline_genome": {},
        "current_genome": {"version": "9.99.0", "commit_sha": "abc", "invariant_count": "320"},
    }
    s = eng.score(inp)
    assert s == 0.0


# ===========================================================================
# T166-GAE-24  DimensionResult.aligned is True only on exact string match
# ===========================================================================
def test_t166_gae_24_dimension_exact_match(tmp_path):
    eng = _engine(tmp_path)
    inp = _aligned_inputs()
    report = eng.align(inp)
    for dim in report.dimensions:
        assert dim.aligned is True
        assert dim.score == 1.0


# ===========================================================================
# T166-GAE-25  Ledger file created on first align()
# ===========================================================================
def test_t166_gae_25_ledger_created(tmp_path):
    ledger = tmp_path / "genome_alignment.jsonl"
    eng = GenomeAlignmentEngine(ledger_path=ledger)
    assert not ledger.exists()
    eng.align(_aligned_inputs())
    assert ledger.exists()


# ===========================================================================
# T166-GAE-26  Ledger entries are valid JSON lines
# ===========================================================================
def test_t166_gae_26_ledger_valid_jsonl(tmp_path):
    eng = _engine(tmp_path)
    eng.align(_aligned_inputs())
    ledger = tmp_path / "genome_alignment.jsonl"
    for line in ledger.read_text().strip().splitlines():
        obj = json.loads(line)
        assert "report_id" in obj
        assert "chain_digest" in obj


# ===========================================================================
# T166-GAE-27  get_engine() returns singleton
# ===========================================================================
def test_t166_gae_27_singleton():
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


# ===========================================================================
# T166-GAE-28  amendment_hash stored in each alignment report
# ===========================================================================
def test_t166_gae_28_amendment_hash_in_report(tmp_path):
    eng = _engine(tmp_path)
    report = eng.align(_aligned_inputs())
    assert report.amendment_hash == _AMENDMENT_HASH


# ===========================================================================
# T166-GAE-29  governor field present in report
# ===========================================================================
def test_t166_gae_29_governor_in_report(tmp_path):
    eng = _engine(tmp_path)
    report = eng.align(_aligned_inputs())
    assert report.governor == "DUSTIN L REID"


# ===========================================================================
# T166-GAE-30  Full lifecycle: align, history, verify_chain — no errors
# ===========================================================================
def test_t166_gae_30_full_lifecycle(tmp_path):
    eng = _engine(tmp_path)
    r1 = eng.align(_aligned_inputs("v9.99.0"))
    r2 = eng.align(_aligned_inputs("v9.100.0"))
    h = eng.history()
    assert len(h) == 2
    assert eng.verify_chain() is True
    assert r1.alignment_score == 1.0
    assert r2.alignment_score == 1.0
    amend = eng.amendment()
    assert amend["redefines_criterion"] == "GA_ALIGNMENT"
