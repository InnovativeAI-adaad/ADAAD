# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase144_innov50_rags.py
Phase 144 · INNOV-50 · Retrieval-Augmented Governance Synthesis (RAGS)
30/30 acceptance tests — pytest -m phase144
"""
import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Module under test ──────────────────────────────────────────────────────────
from dorkllm.grounded_responder import (
    RAGS_HMAC_SECRET,
    RAGS_MAX_CONTEXT_CHARS,
    RAGS_MIN_COSINE_THRESHOLD,
    RAGS_TOP_K,
    CorpusEntry,
    GroundedQuery,
    RAGSChainViolation,
    RAGSGroundingViolation,
    RAGSInvariantViolation,
    RAGSLedgerWriteError,
    RAGSZeroGroundingError,
    RetrievedChunk,
    _assert_chain_hashes,
    _keyword_score,
    _last_ledger_state,
    append_grounding_ledger,
    assemble_context,
    assert_grounded,
    ground_query,
    load_corpus,
    retrieve_top_k,
    verify_grounding_ledger,
)

pytestmark = pytest.mark.phase144

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_entry(id_: str, title: str, content: str, hash_: str = "") -> CorpusEntry:
    return CorpusEntry(
        id=id_,
        type="governance",
        title=title,
        content=content,
        corpus_entry_hash=hash_ or hashlib.sha256(content.encode()).hexdigest(),
    )


CORPUS_FIXTURE = [
    _make_entry("INV-001", "GovernanceGate Hard Invariant",
                "GovernanceGate is the final arbiter of all constitutional mutations. "
                "Hard-class invariants cannot be bypassed by any agent."),
    _make_entry("INV-002", "HUMAN-0 Ratification",
                "Dustin L. Reid is HUMAN-0. GPG signing and ratification are "
                "non-delegatable. Only HUMAN-0 may approve Tier-0 amendments."),
    _make_entry("INV-003", "CMU Context Window",
                "CMU-CTX-0 requires num_ctx >= 16384. The phi4 model uses 32768 "
                "context tokens to fit full corpus and conversation history."),
    _make_entry("INV-004", "CEL Constitutional Evolution Loop",
                "The Constitutional Evolution Loop drives all phase execution. "
                "15 steps from proposal through ratification and telemetry."),
    _make_entry("INV-005", "LKSE Corpus Sync",
                "LKSE-SYNC-0 requires the corpus to be synchronized with each "
                "phase commit. All corpus entries are HMAC-SHA256 chain-linked."),
]


@pytest.fixture()
def tmp_ledger(tmp_path):
    return tmp_path / "rags_grounding_ledger.jsonl"


@pytest.fixture()
def tmp_corpus_file(tmp_path):
    p = tmp_path / "corpus.jsonl"
    with p.open("w") as f:
        for entry in CORPUS_FIXTURE:
            d = {
                "id": entry.id, "type": entry.type, "title": entry.title,
                "content": entry.content, "corpus_entry_hash": entry.corpus_entry_hash,
            }
            f.write(json.dumps(d) + "\n")
    return p


# ════════════════════════════════════════════════════════════════════════════════
# T144-RAGS-01 through T144-RAGS-10 — Constants & error hierarchy
# ════════════════════════════════════════════════════════════════════════════════

def test_T144_RAGS_01_constants_defined():
    """RAGS-GROUND-0/GATE-0: constitutional constants are non-zero."""
    assert RAGS_MIN_COSINE_THRESHOLD > 0.0
    assert RAGS_TOP_K >= 3
    assert RAGS_MAX_CONTEXT_CHARS >= 4000


def test_T144_RAGS_02_error_hierarchy():
    """All violation errors inherit from RAGSInvariantViolation."""
    assert issubclass(RAGSGroundingViolation, RAGSInvariantViolation)
    assert issubclass(RAGSZeroGroundingError, RAGSInvariantViolation)
    assert issubclass(RAGSLedgerWriteError, RAGSInvariantViolation)
    assert issubclass(RAGSChainViolation, RAGSInvariantViolation)


def test_T144_RAGS_03_error_hierarchy_is_runtime():
    """All violation errors are RuntimeError subclasses (ADAAD invariant pattern)."""
    assert issubclass(RAGSInvariantViolation, RuntimeError)


def test_T144_RAGS_04_rags_ground_violation_message():
    """RAGS-GROUND-0 violation carries invariant code in message."""
    with pytest.raises(RAGSGroundingViolation, match="RAGS-GROUND-0"):
        assert_grounded([])


def test_T144_RAGS_05_rags_zero_grounding_empty_corpus():
    """RAGS-GATE-0: empty corpus raises RAGSZeroGroundingError."""
    with pytest.raises(RAGSZeroGroundingError, match="RAGS-GATE-0"):
        retrieve_top_k("governance query", [])


def test_T144_RAGS_06_rags_gate_no_score_above_threshold():
    """RAGS-GATE-0: corpus with zero keyword overlap raises RAGSZeroGroundingError."""
    corpus = [_make_entry("X", "zzz qqq", "zzz qqq mmm")]
    with pytest.raises(RAGSZeroGroundingError, match="RAGS-GATE-0"):
        retrieve_top_k("governance invariant constitutional", corpus, min_score=0.5)


def test_T144_RAGS_07_corpus_entry_dataclass():
    """CorpusEntry dataclass stores fields correctly."""
    e = _make_entry("T001", "Test Title", "Test content", "abc123")
    assert e.id == "T001"
    assert e.title == "Test Title"
    assert e.corpus_entry_hash == "abc123"


def test_T144_RAGS_08_corpus_entry_from_dict():
    """CorpusEntry.from_dict handles both 'content' and 'body' keys."""
    d1 = {"id": "A", "type": "governance", "title": "T", "content": "C", "corpus_entry_hash": "hA"}
    d2 = {"id": "B", "type": "invariant", "title": "T2", "body": "C2", "entry_hash": "hB"}
    e1 = CorpusEntry.from_dict(d1)
    e2 = CorpusEntry.from_dict(d2)
    assert e1.content == "C"
    assert e1.corpus_entry_hash == "hA"
    assert e2.content == "C2"
    assert e2.corpus_entry_hash == "hB"


def test_T144_RAGS_09_retrieved_chunk_dataclass():
    """RetrievedChunk stores entry and score."""
    e = _make_entry("R1", "Title", "content")
    chunk = RetrievedChunk(entry=e, score=0.42)
    assert chunk.score == 0.42
    assert chunk.entry.id == "R1"


def test_T144_RAGS_10_grounded_query_dataclass():
    """GroundedQuery carries all required fields."""
    gq = GroundedQuery(
        query="q", grounded_prompt="ctx\nq", cited_ids=["A"],
        cited_hashes=["hA"], top_score=0.5, context_chars=100,
        truncated=False, ledger_seq=0, ledger_entry_hash="eh",
    )
    assert gq.ledger_seq == 0
    assert gq.cited_hashes == ["hA"]


# ════════════════════════════════════════════════════════════════════════════════
# T144-RAGS-11 through T144-RAGS-18 — Keyword retrieval
# ════════════════════════════════════════════════════════════════════════════════

def test_T144_RAGS_11_keyword_score_overlap():
    """_keyword_score returns > 0 for overlapping terms."""
    score = _keyword_score("governance invariant", "governance Hard-class invariant")
    assert score > 0.0


def test_T144_RAGS_12_keyword_score_no_overlap():
    """_keyword_score returns 0 for fully disjoint strings."""
    score = _keyword_score("zebra xylophone", "constitutional governance ledger")
    assert score == 0.0


def test_T144_RAGS_13_keyword_score_empty_query():
    """_keyword_score returns 0 for empty query."""
    assert _keyword_score("", "anything here") == 0.0


def test_T144_RAGS_14_retrieve_top_k_returns_ranked():
    """retrieve_top_k returns entries sorted by score descending."""
    chunks = retrieve_top_k(
        "GovernanceGate Hard-class invariant",
        CORPUS_FIXTURE,
        top_k=3,
        min_score=0.01,
    )
    assert len(chunks) >= 1
    scores = [c.score for c in chunks]
    assert scores == sorted(scores, reverse=True)


def test_T144_RAGS_15_retrieve_top_k_respects_k():
    """retrieve_top_k returns at most top_k results."""
    chunks = retrieve_top_k(
        "constitutional governance",
        CORPUS_FIXTURE,
        top_k=2,
        min_score=0.001,
    )
    assert len(chunks) <= 2


def test_T144_RAGS_16_retrieve_filters_below_threshold():
    """retrieve_top_k: returned entries all meet min_score; below-threshold entries excluded.
    Uses a very low threshold so at least one entry passes and sub-threshold entries
    are excluded from results (score-filter semantics, not gate semantics).
    """
    threshold = 0.001
    chunks = retrieve_top_k(
        "GovernanceGate invariant constitutional",
        CORPUS_FIXTURE,
        top_k=5,
        min_score=threshold,
    )
    # All returned entries must satisfy the threshold (filter semantics)
    for c in chunks:
        assert c.score >= threshold
    # Verify that RAGS-GATE-0 fires when the best entry cannot meet a very high threshold
    with pytest.raises(RAGSZeroGroundingError, match="RAGS-GATE-0"):
        retrieve_top_k("GovernanceGate", CORPUS_FIXTURE, top_k=5, min_score=0.999)


def test_T144_RAGS_17_retrieve_top_k_best_match_first():
    """retrieve_top_k first result has highest score."""
    chunks = retrieve_top_k(
        "HUMAN-0 Dustin ratification GPG",
        CORPUS_FIXTURE,
        top_k=3,
        min_score=0.001,
    )
    assert chunks[0].score == max(c.score for c in chunks)


def test_T144_RAGS_18_retrieve_returns_corpus_entry_hash():
    """Retrieved chunks carry corpus_entry_hash (RAGS-CHAIN-0 prerequisite)."""
    chunks = retrieve_top_k(
        "constitutional invariant",
        CORPUS_FIXTURE,
        top_k=3,
        min_score=0.001,
    )
    for c in chunks:
        assert c.entry.corpus_entry_hash != ""


# ════════════════════════════════════════════════════════════════════════════════
# T144-RAGS-19 through T144-RAGS-22 — Context assembly (RAGS-CTX-0)
# ════════════════════════════════════════════════════════════════════════════════

def test_T144_RAGS_19_context_not_truncated_normal():
    """assemble_context returns truncated=False for small corpus."""
    chunks = [RetrievedChunk(entry=e, score=0.5) for e in CORPUS_FIXTURE[:2]]
    ctx, truncated = assemble_context(chunks, max_chars=RAGS_MAX_CONTEXT_CHARS)
    assert not truncated
    assert len(ctx) > 0


def test_T144_RAGS_20_context_truncation_flag():
    """assemble_context returns truncated=True when max_chars exceeded."""
    big_entry = _make_entry("BIG", "Big Entry", "x" * 5000)
    chunks = [RetrievedChunk(entry=big_entry, score=0.9)] * 5
    ctx, truncated = assemble_context(chunks, max_chars=1000)
    assert truncated


def test_T144_RAGS_21_context_contains_title():
    """assemble_context output includes entry titles."""
    chunks = retrieve_top_k("GovernanceGate", CORPUS_FIXTURE, top_k=2, min_score=0.001)
    ctx, _ = assemble_context(chunks)
    assert "GovernanceGate" in ctx or any(c.entry.title in ctx for c in chunks)


def test_T144_RAGS_22_context_contains_header():
    """assemble_context output begins with RAGS grounding header."""
    chunks = [RetrievedChunk(entry=CORPUS_FIXTURE[0], score=0.8)]
    ctx, _ = assemble_context(chunks)
    assert "RAGS GROUNDING CONTEXT" in ctx


# ════════════════════════════════════════════════════════════════════════════════
# T144-RAGS-23 through T144-RAGS-27 — Ledger & chain (RAGS-DETERM-0, RAGS-CHAIN-0)
# ════════════════════════════════════════════════════════════════════════════════

def test_T144_RAGS_23_chain_hashes_raises_on_missing(tmp_ledger):
    """RAGS-CHAIN-0: assert_chain_hashes raises if corpus_entry_hash is empty."""
    bad_entry = CorpusEntry(id="X", type="g", title="T", content="C", corpus_entry_hash="")
    chunk = RetrievedChunk(entry=bad_entry, score=0.9)
    with pytest.raises(RAGSChainViolation, match="RAGS-CHAIN-0"):
        _assert_chain_hashes([chunk])


def test_T144_RAGS_24_append_ledger_creates_file(tmp_ledger):
    """RAGS-DETERM-0: append_grounding_ledger creates file on first write."""
    chunks = [RetrievedChunk(entry=CORPUS_FIXTURE[0], score=0.7)]
    entry = append_grounding_ledger("test query", chunks, 100, False, ledger_path=tmp_ledger)
    assert tmp_ledger.exists()
    assert entry.seq == 0
    assert entry.entry_hash != ""


def test_T144_RAGS_25_ledger_chain_links(tmp_ledger):
    """RAGS-DETERM-0: successive ledger entries chain prev_hash correctly."""
    chunks = [RetrievedChunk(entry=CORPUS_FIXTURE[0], score=0.6)]
    e1 = append_grounding_ledger("query one", chunks, 50, False, ledger_path=tmp_ledger)
    e2 = append_grounding_ledger("query two", chunks, 60, False, ledger_path=tmp_ledger)
    assert e2.prev_hash == e1.entry_hash
    assert e2.seq == 1


def test_T144_RAGS_26_verify_ledger_valid(tmp_ledger):
    """verify_grounding_ledger returns ok=True for intact chain."""
    chunks = [RetrievedChunk(entry=CORPUS_FIXTURE[0], score=0.8)]
    for i in range(3):
        append_grounding_ledger(f"query {i}", chunks, 80, False, ledger_path=tmp_ledger)
    result = verify_grounding_ledger(tmp_ledger)
    assert result["ok"] is True
    assert result["entries"] == 3


def test_T144_RAGS_27_verify_ledger_detects_tamper(tmp_ledger):
    """verify_grounding_ledger detects tampered entry_hash."""
    chunks = [RetrievedChunk(entry=CORPUS_FIXTURE[0], score=0.8)]
    append_grounding_ledger("q", chunks, 80, False, ledger_path=tmp_ledger)
    # Tamper with the entry_hash
    lines = tmp_ledger.read_text().strip().split("\n")
    entry = json.loads(lines[0])
    entry["entry_hash"] = "deadbeef" * 8
    tmp_ledger.write_text(json.dumps(entry) + "\n")
    result = verify_grounding_ledger(tmp_ledger)
    assert result["ok"] is False


# ════════════════════════════════════════════════════════════════════════════════
# T144-RAGS-28 through T144-RAGS-30 — Full pipeline (ground_query)
# ════════════════════════════════════════════════════════════════════════════════

def test_T144_RAGS_28_ground_query_returns_grounded_query(tmp_ledger):
    """ground_query returns a GroundedQuery with populated fields."""
    result = ground_query(
        "GovernanceGate constitutional invariant",
        corpus=CORPUS_FIXTURE,
        min_score=0.001,
        ledger_path=tmp_ledger,
    )
    assert isinstance(result, GroundedQuery)
    assert len(result.cited_ids) >= 1
    assert len(result.cited_hashes) == len(result.cited_ids)
    assert result.ledger_seq >= 0
    assert "RAGS GROUNDING CONTEXT" in result.grounded_prompt
    assert result.query in result.grounded_prompt


def test_T144_RAGS_29_ground_query_ledger_entry_written(tmp_ledger):
    """ground_query writes ledger entry; verify_grounding_ledger passes."""
    ground_query(
        "HUMAN-0 ratification GPG",
        corpus=CORPUS_FIXTURE,
        min_score=0.001,
        ledger_path=tmp_ledger,
    )
    result = verify_grounding_ledger(tmp_ledger)
    assert result["ok"] is True
    assert result["entries"] == 1


def test_T144_RAGS_30_load_corpus_from_file(tmp_corpus_file):
    """load_corpus reads JSONL corpus file and returns CorpusEntry list."""
    entries = load_corpus(tmp_corpus_file)
    assert len(entries) == len(CORPUS_FIXTURE)
    ids = {e.id for e in entries}
    assert "INV-001" in ids
    assert all(e.corpus_entry_hash for e in entries)
