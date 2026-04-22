# SPDX-License-Identifier: Apache-2.0
# tests/innovations/test_phase146_dqr.py
# Phase 146 · INNOV-52 · Dork Query Router (DQR)
# 30 tests required · 100% pass rate required
# Constitutional invariants verified: DQR-ROUTE-0, DQR-CHAIN-0,
#   DQR-DETERM-0, DQR-FALLBACK-0, DQR-AUTH-0

import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# ── Test isolation: redirect DQR ledger to a temp dir ─────────────────────────

@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """Redirect DQR ledger to a temporary directory and reset module state."""
    ledger = tmp_path / "dqr_routing_ledger.jsonl"
    monkeypatch.setenv("DQR_LEDGER_PATH", str(ledger))
    monkeypatch.setenv("DQR_HMAC_SECRET", "adaad-dqr-constitutional-secret-v1")
    monkeypatch.setenv("DQR_HUMAN0_TOKEN", "HUMAN-0:DQR:OVERRIDE")
    # Evict cached module so env vars are re-read
    for mod in list(sys.modules.keys()):
        if "query_router" in mod or "dork_query_router" in mod:
            del sys.modules[mod]
    yield tmp_path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_dqr():
    import importlib
    return importlib.import_module("dorkllm.query_router")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: Ledger initialisation (T01–T05)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_01_genesis_created_on_first_ensure(tmp_path):
    """Ledger is created with a genesis entry on first _ensure_ledger()."""
    dqr = _get_dqr()
    dqr._ensure_ledger()
    assert Path(os.environ["DQR_LEDGER_PATH"]).exists()
    entries = dqr._load_all()
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "genesis"
    assert entries[0]["seq"] == 0


@pytest.mark.T146
def test_T146_DQR_02_genesis_prev_hash_is_zeros(tmp_path):
    """Genesis prev_hash must be 64 zeros."""
    dqr = _get_dqr()
    dqr._ensure_ledger()
    entry = dqr._load_all()[0]
    assert entry["prev_hash"] == "0" * 64


@pytest.mark.T146
def test_T146_DQR_03_genesis_hmac_valid(tmp_path):
    """Genesis entry_hash is a valid HMAC-SHA256."""
    dqr = _get_dqr()
    dqr._ensure_ledger()
    entry = dqr._load_all()[0]
    canon = dqr._canonical(entry["payload"])
    expected = dqr._hmac_digest(entry["prev_hash"], canon)
    assert entry["entry_hash"] == expected


@pytest.mark.T146
def test_T146_DQR_04_ensure_ledger_idempotent(tmp_path):
    """Calling _ensure_ledger() twice does not duplicate genesis."""
    dqr = _get_dqr()
    dqr._ensure_ledger()
    dqr._ensure_ledger()
    assert len(dqr._load_all()) == 1


@pytest.mark.T146
def test_T146_DQR_05_parent_dirs_created(tmp_path):
    """_ensure_ledger() creates nested parent directories."""
    nested = tmp_path / "a" / "b" / "c" / "dqr.jsonl"
    os.environ["DQR_LEDGER_PATH"] = str(nested)
    dqr = _get_dqr()
    dqr._DQR_LEDGER_PATH = nested
    dqr._ensure_ledger()
    assert nested.exists()


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: Deterministic scoring — DQR-DETERM-0 (T06–T10)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_06_score_dpm_memory_keywords():
    """_score_dpm() returns non-zero score for DPM-relevant query."""
    dqr = _get_dqr()
    score = dqr._score_dpm("remember my past sessions from memory")
    assert score > 0.0


@pytest.mark.T146
def test_T146_DQR_07_score_dpm_deterministic():
    """DQR-DETERM-0: _score_dpm() returns identical score on repeated calls."""
    dqr = _get_dqr()
    q = "recall the history of my stored context"
    assert dqr._score_dpm(q) == dqr._score_dpm(q)


@pytest.mark.T146
def test_T146_DQR_08_score_rags_governance_keywords():
    """_score_rags() returns non-zero score for governance-related query."""
    dqr = _get_dqr()
    score = dqr._score_rags("what is the constitutional invariant for governance")
    assert score > 0.0


@pytest.mark.T146
def test_T146_DQR_09_score_rags_deterministic():
    """DQR-DETERM-0: _score_rags() returns identical score on repeated calls."""
    dqr = _get_dqr()
    q = "constitutional mutation governance phase invariant"
    assert dqr._score_rags(q) == dqr._score_rags(q)


@pytest.mark.T146
def test_T146_DQR_10_score_passthrough_query_zero():
    """Generic query scores 0.0 on both DPM and RAGS scorers."""
    dqr = _get_dqr()
    q = "hello world"
    assert dqr._score_dpm(q) == 0.0
    assert dqr._score_rags(q) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: route_query() dispatch — DQR-ROUTE-0 (T11–T16)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_11_route_dpm_for_memory_query():
    """DPM-signal query routes to dpm."""
    dqr = _get_dqr()
    decision = dqr.route_query("remember my past sessions")
    assert decision.route == dqr.ROUTE_DPM


@pytest.mark.T146
def test_T146_DQR_12_route_rags_for_governance_query():
    """Governance-signal query routes to rags."""
    dqr = _get_dqr()
    decision = dqr.route_query("explain the constitutional invariant for governance phase")
    assert decision.route == dqr.ROUTE_RAGS


@pytest.mark.T146
def test_T146_DQR_13_route_passthrough_for_generic_query():
    """Generic query routes to passthrough."""
    dqr = _get_dqr()
    decision = dqr.route_query("hello world")
    assert decision.route == dqr.ROUTE_PASSTHROUGH


@pytest.mark.T146
def test_T146_DQR_14_route_decision_logged_to_ledger():
    """DQR-ROUTE-0: every route_query() call appends an entry to the ledger."""
    dqr = _get_dqr()
    dqr._ensure_ledger()  # initialise genesis so baseline is stable
    before = len(dqr._load_all())
    dqr.route_query("hello world")
    after = len(dqr._load_all())
    assert after == before + 1


@pytest.mark.T146
def test_T146_DQR_15_route_decision_query_hash_correct():
    """RouteDecision.query_hash matches SHA-256 of the query text."""
    dqr = _get_dqr()
    q = "test query for hash verification"
    decision = dqr.route_query(q)
    expected = hashlib.sha256(q.encode()).hexdigest()
    assert decision.query_hash == expected


@pytest.mark.T146
def test_T146_DQR_16_route_seq_increments():
    """RouteDecision seq increments with each new route_query() call."""
    dqr = _get_dqr()
    d1 = dqr.route_query("first query hello")
    d2 = dqr.route_query("second query hello")
    assert d2.seq == d1.seq + 1


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: HMAC chain integrity — DQR-CHAIN-0 (T17–T21)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_17_verify_chain_passes_on_intact_ledger():
    """DQR-CHAIN-0: verify_chain() returns True on a freshly written ledger."""
    dqr = _get_dqr()
    dqr.route_query("query alpha")
    dqr.route_query("query beta")
    assert dqr.verify_chain() is True


@pytest.mark.T146
def test_T146_DQR_18_verify_chain_detects_tampered_entry():
    """DQR-CHAIN-0: verify_chain() raises DQRChainViolation on corrupted entry."""
    dqr = _get_dqr()
    dqr.route_query("query to corrupt")
    ledger_path = Path(os.environ["DQR_LEDGER_PATH"])
    lines = ledger_path.read_text().splitlines()
    # Corrupt last entry's entry_hash
    last = json.loads(lines[-1])
    last["entry_hash"] = "0" * 64
    lines[-1] = json.dumps(last)
    ledger_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(dqr.DQRChainViolation):
        dqr.verify_chain()


@pytest.mark.T146
def test_T146_DQR_19_entry_prev_hash_links_correctly():
    """DQR-CHAIN-0: each entry's prev_hash equals the prior entry's entry_hash."""
    dqr = _get_dqr()
    dqr.route_query("link test one")
    dqr.route_query("link test two")
    entries = dqr._load_all()
    assert entries[2]["prev_hash"] == entries[1]["entry_hash"]


@pytest.mark.T146
def test_T146_DQR_20_hmac_digest_deterministic():
    """_hmac_digest() returns identical value for same inputs."""
    dqr = _get_dqr()
    h = dqr._hmac_digest("aabbcc", '{"key":"value"}')
    assert h == dqr._hmac_digest("aabbcc", '{"key":"value"}')


@pytest.mark.T146
def test_T146_DQR_21_entry_hash_in_route_decision():
    """RouteDecision.entry_hash is non-empty and 64 hex chars."""
    dqr = _get_dqr()
    decision = dqr.route_query("entry hash check")
    assert len(decision.entry_hash) == 64
    assert all(c in "0123456789abcdef" for c in decision.entry_hash)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5: Fallback safety — DQR-FALLBACK-0 (T22–T24)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_22_route_query_never_raises_on_score_error():
    """DQR-FALLBACK-0: if _score_dpm raises, route_query returns passthrough."""
    dqr = _get_dqr()
    with mock.patch.object(dqr, "_score_dpm", side_effect=RuntimeError("fail")):
        decision = dqr.route_query("anything")
    assert decision.route == dqr.ROUTE_PASSTHROUGH


@pytest.mark.T146
def test_T146_DQR_23_route_query_never_raises_on_ledger_error():
    """DQR-FALLBACK-0: if ledger append raises, route_query still returns."""
    dqr = _get_dqr()
    with mock.patch.object(dqr, "_append_decision", side_effect=OSError("disk full")):
        decision = dqr.route_query("ledger fail test")
    assert decision.route == dqr.ROUTE_PASSTHROUGH


@pytest.mark.T146
def test_T146_DQR_24_fallback_decision_has_passthrough_route():
    """DQR-FALLBACK-0: fallback RouteDecision always has route=passthrough."""
    dqr = _get_dqr()
    with mock.patch.object(dqr, "_score_rags", side_effect=ValueError("boom")):
        decision = dqr.route_query("anything at all")
    assert decision.route == dqr.ROUTE_PASSTHROUGH


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6: HUMAN-0 policy override — DQR-AUTH-0 (T25–T28)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_25_override_policy_valid_token_sets_route():
    """DQR-AUTH-0: valid HUMAN-0 token sets override route."""
    dqr = _get_dqr()
    token = dqr._DQR_HUMAN0_TOKEN
    result = dqr.override_policy(dqr.ROUTE_PASSTHROUGH, token)
    assert result is True
    assert dqr._policy_override == dqr.ROUTE_PASSTHROUGH
    dqr._policy_override = None  # cleanup


@pytest.mark.T146
def test_T146_DQR_26_override_policy_invalid_token_raises():
    """DQR-AUTH-0: invalid token raises DQRAuthViolation."""
    dqr = _get_dqr()
    with pytest.raises(dqr.DQRAuthViolation):
        dqr.override_policy(dqr.ROUTE_DPM, b"wrong-token")


@pytest.mark.T146
def test_T146_DQR_27_override_forces_route():
    """DQR-AUTH-0: active override forces every query to that route."""
    dqr = _get_dqr()
    token = dqr._DQR_HUMAN0_TOKEN
    dqr.override_policy(dqr.ROUTE_RAGS, token)
    # Even a DPM-signal query must route to RAGS under override
    decision = dqr.route_query("remember my past memory session history")
    assert decision.route == dqr.ROUTE_RAGS
    dqr._policy_override = None  # cleanup


@pytest.mark.T146
def test_T146_DQR_28_clear_override_restores_natural_routing():
    """clear_override() with valid token removes the forced route."""
    dqr = _get_dqr()
    token = dqr._DQR_HUMAN0_TOKEN
    dqr.override_policy(dqr.ROUTE_RAGS, token)
    dqr.clear_override(token)
    assert dqr._policy_override is None
    decision = dqr.route_query("remember my past memory session history")
    assert decision.route == dqr.ROUTE_DPM


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 7: ledger_stats() + innovations wrapper (T29–T30)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.T146
def test_T146_DQR_29_ledger_stats_counts_correctly():
    """ledger_stats() returns accurate route distribution counts."""
    dqr = _get_dqr()
    dqr.route_query("remember my memory session")         # dpm
    dqr.route_query("constitutional governance invariant phase")  # rags
    dqr.route_query("hello world")                         # passthrough
    stats = dqr.ledger_stats()
    assert stats["total_decisions"] == 3
    assert stats["route_counts"][dqr.ROUTE_DPM] >= 1
    assert stats["route_counts"][dqr.ROUTE_RAGS] >= 1
    assert stats["route_counts"][dqr.ROUTE_PASSTHROUGH] >= 1


@pytest.mark.T146
def test_T146_DQR_30_innovations_wrapper_status():
    """innovations30.dork_query_router.status() returns correct metadata."""
    # Re-import wrapper after env is set
    for mod in list(sys.modules.keys()):
        if "dork_query_router" in mod:
            del sys.modules[mod]
    import importlib
    wrapper = importlib.import_module("runtime.innovations30.dork_query_router")
    s = wrapper.status()
    assert s["innovation_id"] == "INNOV-52"
    assert s["phase"] == 146
    assert len(s["hard_class_invariants"]) == 5
    assert "DQR-ROUTE-0" in s["hard_class_invariants"]
    assert "DQR-FALLBACK-0" in s["hard_class_invariants"]
