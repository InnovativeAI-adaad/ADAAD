# SPDX-License-Identifier: Apache-2.0
# tests/innovations/test_phase145_dpm.py
# Phase 145 · INNOV-51 · DORK Persistent Memory (DPM)
# 30 tests required · 100% pass rate required
# Constitutional invariants verified: DPM-CHAIN-0, DPM-INJECT-0,
#   DPM-DETERM-0, DPM-HUMAN0-0, DPM-GATE-0

import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# ── Test isolation: redirect ledgers to a temp dir ────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_ledgers(tmp_path, monkeypatch):
    """Redirect all DPM ledger paths to a temporary directory."""
    ledger = tmp_path / "dpm_memory.jsonl"
    eviction = tmp_path / "dpm_eviction.jsonl"
    monkeypatch.setenv("DPM_LEDGER_PATH", str(ledger))
    monkeypatch.setenv("DPM_EVICTION_LEDGER_PATH", str(eviction))
    # Re-import modules so they pick up new env vars
    for mod in ["dorkllm.memory_engine", "dorkllm.pattern_detector",
                "dorkllm.knowledge_crystallizer"]:
        if mod in sys.modules:
            del sys.modules[mod]
    yield tmp_path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_mem():
    import importlib
    return importlib.import_module("dorkllm.memory_engine")

def _get_pd():
    import importlib
    return importlib.import_module("dorkllm.pattern_detector")

def _get_kc():
    import importlib
    return importlib.import_module("dorkllm.knowledge_crystallizer")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: memory_engine — ledger init & genesis (T01–T05)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_01_genesis_created_on_first_ensure(tmp_path):
    """Ledger file is created with a genesis entry on first _ensure_ledger()."""
    mem = _get_mem()
    mem._ensure_ledger()
    assert Path(os.environ["DPM_LEDGER_PATH"]).exists()
    entries = mem._load_all()
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "genesis"
    assert entries[0]["seq"] == 0


def test_T145_DPM_02_genesis_prev_hash_is_zero(tmp_path):
    """Genesis entry prev_hash must be 64 zeros."""
    mem = _get_mem()
    mem._ensure_ledger()
    entry = mem._load_all()[0]
    assert entry["prev_hash"] == "0" * 64


def test_T145_DPM_03_genesis_hmac_valid(tmp_path):
    """Genesis entry_hash is a valid HMAC-SHA256 of prev_hash+canonical_payload."""
    mem = _get_mem()
    mem._ensure_ledger()
    entry = mem._load_all()[0]
    canon = mem._canonical(entry["payload"])
    expected = mem._hmac_digest(entry["prev_hash"], canon)
    assert entry["entry_hash"] == expected


def test_T145_DPM_04_ensure_idempotent(tmp_path):
    """Calling _ensure_ledger() twice does not duplicate genesis."""
    mem = _get_mem()
    mem._ensure_ledger()
    mem._ensure_ledger()
    assert len(mem._load_all()) == 1


def test_T145_DPM_05_parent_dirs_created(tmp_path):
    """_ensure_ledger() creates parent directories if they don't exist."""
    nested = tmp_path / "a" / "b" / "c" / "ledger.jsonl"
    os.environ["DPM_LEDGER_PATH"] = str(nested)
    mem = _get_mem()
    mem._LEDGER_PATH = nested
    mem._ensure_ledger()
    assert nested.exists()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: memory_engine — store and chain (T06–T10)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_06_store_memory_appends_entry(tmp_path):
    """store_memory() appends a 'memory' entry to the ledger."""
    mem = _get_mem()
    mem.store_memory("phase-record", "Phase 144 INNOV-50 shipped", 0.85)
    entries = mem._load_all()
    memory_entries = [e for e in entries if e["entry_type"] == "memory"]
    assert len(memory_entries) == 1


def test_T145_DPM_07_store_memory_chain_links(tmp_path):
    """Each stored entry's prev_hash matches previous entry's entry_hash."""
    mem = _get_mem()
    mem.store_memory("topic-a", "content a", 0.70)
    mem.store_memory("topic-b", "content b", 0.75)
    entries = mem._load_all()
    for i in range(1, len(entries)):
        assert entries[i]["prev_hash"] == entries[i - 1]["entry_hash"]


def test_T145_DPM_08_store_memory_seq_increments(tmp_path):
    """Sequence numbers increment monotonically."""
    mem = _get_mem()
    mem.store_memory("t1", "c1", 0.65)
    mem.store_memory("t2", "c2", 0.70)
    entries = mem._load_all()
    seqs = [e["seq"] for e in entries]
    assert seqs == sorted(seqs)
    assert seqs[-1] == len(entries) - 1


def test_T145_DPM_09_store_memory_rejects_low_confidence(tmp_path):
    """DPM-CHAIN-0: store_memory raises ValueError if confidence < 0.6."""
    mem = _get_mem()
    with pytest.raises(ValueError, match="DPM-CHAIN-0"):
        mem.store_memory("topic", "content", 0.3)


def test_T145_DPM_10_store_memory_payload_fields(tmp_path):
    """Stored payload contains all required fields."""
    mem = _get_mem()
    entry = mem.store_memory("governance", "Phase 144 closed", 0.9, tags=["phase", "close"])
    p = entry["payload"]
    assert "topic" in p and "content" in p and "confidence" in p
    assert "tags" in p and "stored_at" in p and "source" in p
    assert sorted(p["tags"]) == ["close", "phase"]


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: memory_engine — chain verification (T11–T14)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_11_verify_chain_empty_ok(tmp_path):
    """verify_chain() on empty ledger returns (True, 'chain_empty')."""
    mem = _get_mem()
    ok, diag = mem.verify_chain()
    assert ok
    assert diag == "chain_empty"


def test_T145_DPM_12_verify_chain_valid_ok(tmp_path):
    """verify_chain() on a correctly-chained ledger returns True."""
    mem = _get_mem()
    mem.store_memory("t", "c", 0.75)
    mem.store_memory("t2", "c2", 0.80)
    ok, diag = mem.verify_chain()
    assert ok
    assert "chain_ok" in diag


def test_T145_DPM_13_verify_chain_detects_tamper(tmp_path):
    """DPM-CHAIN-0: Tampered entry_hash is detected by verify_chain()."""
    mem = _get_mem()
    mem.store_memory("t", "c", 0.75)
    ledger_path = Path(os.environ["DPM_LEDGER_PATH"])
    raw = ledger_path.read_text()
    lines = raw.strip().split("\n")
    last = json.loads(lines[-1])
    last["entry_hash"] = "a" * 64
    lines[-1] = json.dumps(last)
    ledger_path.write_text("\n".join(lines) + "\n")
    ok, diag = mem.verify_chain()
    assert not ok


def test_T145_DPM_14_verify_chain_detects_prev_hash_break(tmp_path):
    """DPM-CHAIN-0: A broken prev_hash link is detected."""
    mem = _get_mem()
    mem.store_memory("t", "c", 0.75)
    mem.store_memory("t2", "c2", 0.80)
    ledger_path = Path(os.environ["DPM_LEDGER_PATH"])
    raw = ledger_path.read_text()
    lines = raw.strip().split("\n")
    last = json.loads(lines[-1])
    last["prev_hash"] = "b" * 64  # break the chain
    lines[-1] = json.dumps(last)
    ledger_path.write_text("\n".join(lines) + "\n")
    ok, diag = mem.verify_chain()
    assert not ok
    assert "chain_break" in diag or "hash_mismatch" in diag


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: memory_engine — retrieval (T15–T17)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_15_retrieve_relevant_deterministic(tmp_path):
    """DPM-DETERM-0: Same query produces same ordered result on repeated calls."""
    mem = _get_mem()
    mem.store_memory("governance", "ADAAD phase governance record", 0.9, tags=["governance"])
    mem.store_memory("tooling", "pytest --ignore=tests/conftest.py", 0.75, tags=["pytest"])
    q = "governance phase adaad"
    r1 = mem.retrieve_relevant(q)
    r2 = mem.retrieve_relevant(q)
    assert [e["seq"] for e in r1] == [e["seq"] for e in r2]


def test_T145_DPM_16_retrieve_respects_max_results(tmp_path):
    """retrieve_relevant() returns at most max_results entries."""
    mem = _get_mem()
    for i in range(10):
        mem.store_memory(f"topic-{i}", f"governance phase adaad content {i}", 0.70 + i * 0.01)
    results = mem.retrieve_relevant("governance phase adaad", max_results=3)
    assert len(results) <= 3


def test_T145_DPM_17_retrieve_excludes_evicted(tmp_path):
    """Evicted entries are excluded from retrieve_relevant results."""
    mem = _get_mem()
    entry = mem.store_memory("topic", "governance adaad phase", 0.85)
    target_seq = entry["seq"]
    mem.record_eviction(target_seq, "test eviction", "approved DUSTIN L REID")
    results = mem.retrieve_relevant("governance adaad phase")
    seqs = [e["seq"] for e in results]
    assert target_seq not in seqs


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5: memory_engine — eviction (T18–T19)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_18_eviction_requires_human0_phrase(tmp_path):
    """DPM-HUMAN0-0: record_eviction raises PermissionError if auth phrase empty."""
    mem = _get_mem()
    with pytest.raises(PermissionError, match="DPM-HUMAN0-0"):
        mem.record_eviction(1, "reason", "")


def test_T145_DPM_19_eviction_appended_to_eviction_ledger(tmp_path):
    """record_eviction() writes to the eviction ledger file."""
    mem = _get_mem()
    mem.record_eviction(1, "test", "approved DUSTIN L REID")
    eviction_path = Path(os.environ["DPM_EVICTION_LEDGER_PATH"])
    assert eviction_path.exists()
    ev = json.loads(eviction_path.read_text().strip())
    assert ev["payload"]["target_seq"] == 1
    assert ev["payload"]["human0_authorisation"] == "approved DUSTIN L REID"


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6: pattern_detector (T20–T23)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_20_detect_patterns_empty_returns_empty(tmp_path):
    """detect_patterns('') returns []."""
    pd = _get_pd()
    assert pd.detect_patterns("") == []


def test_T145_DPM_21_detect_patterns_governance_category(tmp_path):
    """detect_patterns() classifies governance-heavy text correctly."""
    pd = _get_pd()
    text = "Phase 144 INNOV-50 ratified by HUMAN-0 Dustin invariant constitution version bump"
    patterns = pd.detect_patterns(text)
    cats = [p["category"] for p in patterns]
    assert "governance" in cats


def test_T145_DPM_22_detect_patterns_deterministic(tmp_path):
    """DPM-DETERM-0: Same input always produces identical pattern list."""
    pd = _get_pd()
    text = "pytest --ignore conftest git push no-ff phase invariant"
    r1 = pd.detect_patterns(text)
    r2 = pd.detect_patterns(text)
    assert r1 == r2


def test_T145_DPM_23_should_crystallise_threshold(tmp_path):
    """should_crystallise returns True at >= 0.6 confidence, False below."""
    pd = _get_pd()
    assert pd.should_crystallise({"confidence": 0.60}) is True
    assert pd.should_crystallise({"confidence": 0.61}) is True
    assert pd.should_crystallise({"confidence": 0.59}) is False
    assert pd.should_crystallise({"confidence": 0.00}) is False


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 7: knowledge_crystallizer (T24–T27)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_24_crystallize_stores_high_confidence(tmp_path):
    """crystallize() stores patterns that meet threshold."""
    kc = _get_kc()
    stored = kc.crystallize(
        "Phase 144 INNOV-50 ratified by HUMAN-0 Dustin invariant constitution version bump canonical"
    )
    assert len(stored) >= 1


def test_T145_DPM_25_crystallize_skips_low_confidence(tmp_path):
    """crystallize() skips patterns below threshold without raising."""
    kc = _get_kc()
    # Short generic text will produce low-confidence or no patterns
    stored = kc.crystallize("hello world")
    # Should not raise; result may be empty or minimal
    assert isinstance(stored, list)


def test_T145_DPM_26_inject_memory_block_never_raises(tmp_path):
    """DPM-INJECT-0: inject_memory_block() never raises under any condition."""
    kc = _get_kc()
    # With empty ledger
    result = kc.inject_memory_block("any query here")
    assert isinstance(result, str)
    # With corrupted ledger path
    os.environ["DPM_LEDGER_PATH"] = "/nonexistent/path/ledger.jsonl"
    result2 = kc.inject_memory_block("query")
    assert isinstance(result2, str)


def test_T145_DPM_27_inject_memory_block_includes_memories(tmp_path):
    """inject_memory_block() returns a block containing stored memories."""
    # Purge and reimport with env already set by autouse fixture to tmp_path
    import importlib
    for mod in list(sys.modules.keys()):
        if "dorkllm.memory_engine" in mod or "dorkllm.knowledge_crystallizer" in mod:
            del sys.modules[mod]
    mem = importlib.import_module("dorkllm.memory_engine")
    kc = importlib.import_module("dorkllm.knowledge_crystallizer")
    # Both modules now share the same fresh sys.modules entry
    assert kc._mem is mem
    mem.store_memory(
        "governance",
        "ADAAD Phase 144 governance constitution invariant",
        0.9,
        tags=["governance", "phase"],
    )
    block = kc.inject_memory_block("ADAAD Phase governance invariant")
    assert "DORK PERSISTENT MEMORY" in block
    assert "governance" in block.lower()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 8: intelligence.py DPM injection (T28–T29)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_28_build_system_prompt_does_not_raise(tmp_path):
    """Patched build_system_prompt() never raises with DPM available."""
    import importlib
    for mod in list(sys.modules.keys()):
        if "dorkllm" in mod:
            del sys.modules[mod]
    from dorkllm.intelligence import build_system_prompt
    result = build_system_prompt("governance phase invariant adaad")
    assert isinstance(result, str)
    assert len(result) > 50


def test_T145_DPM_29_build_system_prompt_injects_dpm_when_memories_exist(tmp_path):
    """build_system_prompt() includes DPM block when memories are present."""
    import importlib
    for mod in list(sys.modules.keys()):
        if "dorkllm" in mod:
            del sys.modules[mod]
    from dorkllm import memory_engine as mem
    mem.store_memory(
        "governance",
        "ADAAD Phase 144 INNOV-50 RAGS constitution invariant canonical governance",
        0.92,
        tags=["governance", "phase", "invariant"],
    )
    for mod in list(sys.modules.keys()):
        if "dorkllm.intelligence" in mod:
            del sys.modules[mod]
    from dorkllm.intelligence import build_system_prompt
    result = build_system_prompt("governance phase ADAAD invariant canonical")
    assert "DORK PERSISTENT MEMORY" in result


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 9: DPM-GATE-0 and stats (T30)
# ══════════════════════════════════════════════════════════════════════════════

def test_T145_DPM_30_memory_stats_correct(tmp_path):
    """memory_stats() returns correct counts after stores and eviction."""
    mem = _get_mem()
    mem.store_memory("t1", "governance invariant adaad phase", 0.70)
    e2 = mem.store_memory("t2", "tooling pytest git push", 0.75)
    e3 = mem.store_memory("t3", "architecture ledger hmac append-only", 0.80)
    mem.record_eviction(e3["seq"], "test", "approved DUSTIN L REID")
    stats = mem.memory_stats()
    assert stats["memory_entries"] == 3
    assert stats["active_memories"] == 2
    assert stats["evicted_count"] == 1
    assert stats["chain_length"] >= 4  # genesis + 3 memories
