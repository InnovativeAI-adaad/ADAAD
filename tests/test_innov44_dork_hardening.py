# SPDX-License-Identifier: Apache-2.0
# Phase 137 · INNOV-44 · DORK Intelligence Hardening & Capability Expansion
# 30 acceptance tests covering all invariants and enhancement surfaces.

import hashlib
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─── context.py tests ─────────────────────────────────────────────────────────

def test_01_tokenize_produces_bigrams():
    """_tokenize produces bigrams for improved short-query matching."""
    from dorkllm.context import _tokenize
    tokens = _tokenize("fleet heal")
    assert "fleet heal" in tokens
    assert "fleet" in tokens
    assert "heal" in tokens


def test_02_classify_query_fleet_category():
    """'dfsb heal' classifies as fleet (Phase 133+ taxonomy)."""
    from dorkllm.context import classify_query
    cat, conf = classify_query("dfsb heal probe")
    assert cat == "fleet"
    assert conf > 0.0


def test_03_classify_query_persist_category():
    """'restore conversation ledger' classifies as persist."""
    from dorkllm.context import classify_query
    cat, conf = classify_query("restore conversation session persist")
    assert cat in {"persist", "ledger"}


def test_04_get_taxonomy_hints_returns_top3():
    """get_taxonomy_hints returns exactly top_n results."""
    from dorkllm.context import get_taxonomy_hints
    hints = get_taxonomy_hints("gate policy invariant", top_n=3)
    assert len(hints) == 3
    assert all("category" in h and "score" in h for h in hints)


def test_05_get_relevant_context_includes_kb_block():
    """get_relevant_context always includes a KB RETRIEVAL section (DORK-KB-0)."""
    from dorkllm.context import get_relevant_context
    ctx = get_relevant_context("what is the gate status")
    assert "KB RETRIEVAL" in ctx


def test_06_get_relevant_context_includes_category():
    """get_relevant_context includes query category line."""
    from dorkllm.context import get_relevant_context
    ctx = get_relevant_context("fleet provider health")
    assert "Query category:" in ctx


def test_07_context_keyword_taxonomy_has_persist():
    """CONTEXT_KEYWORD_TAXONOMY includes 'persist' category (Phase 133+)."""
    from dorkllm.context import CONTEXT_KEYWORD_TAXONOMY
    assert "persist" in CONTEXT_KEYWORD_TAXONOMY


def test_08_context_keyword_taxonomy_fleet_includes_dfsb():
    """Fleet taxonomy includes dfsb keyword."""
    from dorkllm.context import CONTEXT_KEYWORD_TAXONOMY
    assert "dfsb" in CONTEXT_KEYWORD_TAXONOMY["fleet"]


# ─── retriever.py tests ───────────────────────────────────────────────────────

def test_09_load_kb_returns_list():
    """_load_kb returns a list (empty or populated) — never raises."""
    from dorkllm.retriever import _load_kb, invalidate_kb_cache
    invalidate_kb_cache()
    result = _load_kb()
    assert isinstance(result, list)


def test_10_get_kb_matches_returns_none_on_empty_kb(tmp_path, monkeypatch):
    """get_kb_matches returns None when KB file is absent."""
    import dorkllm.retriever as ret
    monkeypatch.setattr(ret, "KB_PATH", tmp_path / "nonexistent.js")
    ret.invalidate_kb_cache()
    assert ret.get_kb_matches("anything") is None


def test_11_get_kb_matches_json_parse_strategy(tmp_path, monkeypatch):
    """get_kb_matches parses JSON-embedded KB and returns a hit."""
    import dorkllm.retriever as ret
    kb_js = tmp_path / "dork_knowledge_base.js"
    kb_js.write_text(
        'const KB = [{"key": "what is gate", "answer": "The gate is a governance checkpoint.", "tags": ["gate"]}];',
        encoding="utf-8",
    )
    monkeypatch.setattr(ret, "KB_PATH", kb_js)
    ret.invalidate_kb_cache()
    result = ret.get_kb_matches("what is gate", threshold=0.1)
    assert result is not None
    assert result["key"] == "what is gate"
    assert result["score"] > 0


def test_12_get_kb_top_n_returns_multiple(tmp_path, monkeypatch):
    """get_kb_top_n returns up to top_n results."""
    import dorkllm.retriever as ret
    kb_js = tmp_path / "dork_knowledge_base.js"
    entries = [{"key": f"key {i}", "answer": f"answer {i}", "tags": []} for i in range(5)]
    kb_js.write_text(
        f"const KB = {json.dumps(entries)};", encoding="utf-8"
    )
    monkeypatch.setattr(ret, "KB_PATH", kb_js)
    ret.invalidate_kb_cache()
    results = ret.get_kb_top_n("key", threshold=0.0, top_n=3)
    assert len(results) <= 3


def test_13_invalidate_kb_cache_clears_lru():
    """invalidate_kb_cache resets lru_cache — currsize drops to 0 after clear."""
    from dorkllm.retriever import _load_kb, invalidate_kb_cache
    _ = _load_kb()  # prime the cache
    assert _load_kb.cache_info().currsize == 1
    invalidate_kb_cache()
    # After invalidation cache is empty — currsize=0 until next call
    assert _load_kb.cache_info().currsize == 0


# ─── state.py tests ───────────────────────────────────────────────────────────

def test_14_conversation_ledger_hash_includes_seq():
    """DORK-LEDGER-HASH-0: ConversationLedger includes seq in hash payload."""
    from dorkllm.state import ConversationLedger
    ledger = ConversationLedger()
    e = ledger.append("user", "hello")
    # Recompute with seq=0 and verify it matches
    payload = json.dumps(
        {"seq": 0, "role": "user", "content_digest": e["content_digest"],
         "timestamp": e["timestamp"], "prev_hash": e["prev_hash"]},
        sort_keys=True,
    )
    expected = hashlib.sha256(payload.encode()).hexdigest()
    assert e["entry_hash"] == expected


def test_15_conversation_ledger_seq_field_present():
    """ConversationLedger entries include seq field."""
    from dorkllm.state import ConversationLedger
    ledger = ConversationLedger()
    e = ledger.append("user", "hello")
    assert "seq" in e
    assert e["seq"] == 0


def test_16_conversation_ledger_verify_passes():
    """ConversationLedger.verify() returns chain_valid after multiple appends."""
    from dorkllm.state import ConversationLedger
    ledger = ConversationLedger()
    ledger.append("user", "first")
    ledger.append("assistant", "second")
    ledger.append("user", "third")
    valid, reason = ledger.verify()
    assert valid is True
    assert reason == "chain_valid"


def test_17_conversation_ledger_restore_entry_matches_append_schema():
    """DORK-LEDGER-HASH-0: restore_entry accepts entry produced by append() schema."""
    from dorkllm.state import ConversationLedger
    ledger = ConversationLedger()
    entry = ledger.append("user", "hello")
    # Create fresh ledger and restore
    ledger2 = ConversationLedger()
    restored = ledger2.restore_entry(
        seq=entry["seq"],
        role=entry["role"],
        content_digest=entry["content_digest"],
        timestamp=entry["timestamp"],
        prev_hash=entry["prev_hash"],
        entry_hash=entry["entry_hash"],
    )
    assert restored["entry_hash"] == entry["entry_hash"]


def test_18_provider_health_registry_circuit_open():
    """ProviderHealthRegistry.circuit_open() trips after repeated failures."""
    from dorkllm.state import ProviderHealthRegistry, ProviderStatus
    registry = ProviderHealthRegistry(window_size=5)
    for _ in range(5):
        registry.record(ProviderStatus("ollama", healthy=False, latency_ms=0.0, error="conn refused"))
    assert registry.circuit_open("ollama", min_probes=3, threshold=0.34) is True


def test_19_provider_health_registry_circuit_closed_when_healthy():
    """ProviderHealthRegistry.circuit_open() stays closed when availability is above threshold."""
    from dorkllm.state import ProviderHealthRegistry, ProviderStatus
    registry = ProviderHealthRegistry(window_size=5)
    for _ in range(5):
        registry.record(ProviderStatus("ollama", healthy=True, latency_ms=10.0))
    assert registry.circuit_open("ollama") is False


def test_20_provider_health_registry_configurable_window():
    """ProviderHealthRegistry respects custom window_size."""
    from dorkllm.state import ProviderHealthRegistry, ProviderStatus
    registry = ProviderHealthRegistry(window_size=3)
    for _ in range(10):
        registry.record(ProviderStatus("x", healthy=True, latency_ms=1.0))
    assert len(registry._registry["x"]) == 3


def test_21_provider_health_registry_summary_includes_circuit_open():
    """ProviderHealthRegistry.summary() includes circuit_open key."""
    from dorkllm.state import ProviderHealthRegistry, ProviderStatus
    registry = ProviderHealthRegistry()
    registry.record(ProviderStatus("p1", healthy=True, latency_ms=5.0))
    s = registry.summary()
    assert "circuit_open" in s["p1"]


# ─── intelligence.py tests ────────────────────────────────────────────────────

def test_22_opt_007_kb_enrich_injects_block_on_hit(tmp_path, monkeypatch):
    """OPT-007: KB enrichment prepends authoritative KB block when hit."""
    import dorkllm.intelligence as intel
    mock_retriever = MagicMock()
    mock_retriever.get_kb_matches.return_value = {
        "score": 0.8, "key": "gate status", "answer": "Gate is the governance checkpoint."
    }
    monkeypatch.setattr(intel, "retriever", mock_retriever)
    enriched, meta = intel.opt_007_kb_enrich("gate status", "base_prompt")
    assert "AUTHORITATIVE KB MATCH" in enriched
    assert meta["kb_hit"] is True


def test_23_opt_007_kb_enrich_returns_original_on_miss(monkeypatch):
    """OPT-007: returns original prompt unchanged on KB miss."""
    import dorkllm.intelligence as intel
    mock_retriever = MagicMock()
    mock_retriever.get_kb_matches.return_value = None
    monkeypatch.setattr(intel, "retriever", mock_retriever)
    enriched, meta = intel.opt_007_kb_enrich("unknown query xyz", "base_prompt")
    assert enriched == "base_prompt"
    assert meta["kb_hit"] is False


def test_24_opt_008_cache_hit_returns_cached():
    """OPT-008: cache returns same response within TTL."""
    import dorkllm.intelligence as intel
    intel._QUERY_CACHE.clear()
    intel.opt_008_query_cache_set("hello query", "cached response")
    result = intel.opt_008_query_cache_get("hello query")
    assert result == "cached response"
    intel._QUERY_CACHE.clear()


def test_25_opt_008_cache_expires_after_ttl(monkeypatch):
    """OPT-008: cache misses after TTL expiry."""
    import dorkllm.intelligence as intel
    monkeypatch.setattr(intel, "_CACHE_TTL_SEC", 0.001)
    intel._QUERY_CACHE.clear()
    intel.opt_008_query_cache_set("ttl query", "stale")
    time.sleep(0.05)
    result = intel.opt_008_query_cache_get("ttl query")
    assert result is None
    intel._QUERY_CACHE.clear()


def test_26_opt_008_cache_evicts_on_overflow():
    """OPT-008: cache evicts oldest entry when 128 entries reached."""
    import dorkllm.intelligence as intel
    intel._QUERY_CACHE.clear()
    for i in range(129):
        intel.opt_008_query_cache_set(f"query_{i}", f"resp_{i}")
    assert len(intel._QUERY_CACHE) <= 128
    intel._QUERY_CACHE.clear()


def test_27_provider_chain_includes_ollama():
    """_get_provider_chain always includes ollama as first provider."""
    from dorkllm.intelligence import _get_provider_chain
    chain = _get_provider_chain()
    assert len(chain) >= 1
    assert chain[0]["name"] == "ollama"


def test_28_provider_chain_includes_fallback_when_env_set(monkeypatch):
    """_get_provider_chain includes fallback provider when env vars set."""
    from dorkllm.intelligence import _get_provider_chain
    monkeypatch.setenv("DORK_FALLBACK_URL", "http://backup:11434")
    monkeypatch.setenv("DORK_FALLBACK_MODEL", "dork-backup")
    chain = _get_provider_chain()
    assert any(p["name"] == "fallback" for p in chain)


# ─── dork_intents.py tests ────────────────────────────────────────────────────

def test_29_dork_intent_name_includes_all_fleet_intents():
    """DORK-INTENT-0: DorkIntentName Literal includes all INNOV-41/42 intents."""
    from app.api.schemas.dork_intents import DorkIntentName
    import typing
    args = typing.get_args(DorkIntentName)
    fleet_intents = {
        "show_fleet_status", "resolve_slash_command", "query_provider_health",
        "replay_conversation_ledger", "classify_query_intent", "inspect_fleet_dispatch",
        "query_fleet_persist", "trigger_fleet_heal", "query_fleet_fitness",
        "verify_fleet_chain", "query_fleet_endpoints",
    }
    for intent in fleet_intents:
        assert intent in args, f"Missing from DorkIntentName: {intent}"


def test_30_dork_intent_name_includes_consensus_mode():
    """DorkTrustMetadata mode Literal includes 'consensus'."""
    import typing
    from app.api.schemas.dork_intents import DorkTrustMetadata
    mode_field = DorkTrustMetadata.model_fields["mode"]
    mode_args = typing.get_args(mode_field.annotation)
    assert "consensus" in mode_args
