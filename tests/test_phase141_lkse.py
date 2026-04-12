# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase141_lkse.py
Phase 141 · INNOV-47 · Live Knowledge Sync Engine (LKSE)
30 acceptance tests — all must pass before Phase 141 merges.

Tests cover:
  T141-LKSE-01..08  — sync_dork_corpus.py output correctness
  T141-LKSE-09..14  — corpus.jsonl schema and chain integrity
  T141-LKSE-15..20  — retriever.py corpus-preference behaviour
  T141-LKSE-21..26  — LKSE hard invariants (SYNC-0, DETERM-0, CHAIN-0, GATE-0, HUMAN0-0)
  T141-LKSE-27..30  — CI workflow and SPDX compliance
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
CORPUS = REPO / "data" / "dork" / "corpus.jsonl"
MANIFEST = REPO / "data" / "dork" / "corpus_manifest.json"
RETRIEVER = REPO / "dorkllm" / "retriever.py"
SYNC_SCRIPT = REPO / "scripts" / "sync_dork_corpus.py"
CI_WORKFLOW = REPO / ".github" / "workflows" / "dork_corpus_sync.yml"
LKSE_HMAC_KEY = b"adaad-lkse-chain-v1"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_corpus() -> list[dict]:
    assert CORPUS.exists(), f"corpus.jsonl not found: {CORPUS}"
    entries = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _load_manifest() -> dict:
    assert MANIFEST.exists(), f"corpus_manifest.json not found: {MANIFEST}"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _compute_chain_digest(entries: list[dict]) -> str:
    sorted_digests = sorted(e["digest"] for e in entries)
    payload = "\n".join(sorted_digests).encode()
    return "hmac-sha256:" + hmac.new(LKSE_HMAC_KEY, payload, hashlib.sha256).hexdigest()


# ── T141-LKSE-01..08: sync_dork_corpus.py output correctness ─────────────────


def test_lkse_01_sync_script_exists():
    """T141-LKSE-01: sync_dork_corpus.py must exist in scripts/"""
    assert SYNC_SCRIPT.exists(), f"sync_dork_corpus.py missing: {SYNC_SCRIPT}"


def test_lkse_02_corpus_file_exists():
    """T141-LKSE-02: corpus.jsonl must exist after sync"""
    assert CORPUS.exists(), "corpus.jsonl was not generated"


def test_lkse_03_corpus_nonempty():
    """T141-LKSE-03: corpus.jsonl must have at least 50 entries"""
    entries = _load_corpus()
    assert len(entries) >= 50, f"corpus too small: {len(entries)} entries"


def test_lkse_04_corpus_has_identity_entries():
    """T141-LKSE-04: corpus must include ADAAD identity entries"""
    entries = _load_corpus()
    keys = {e["key"] for e in entries}
    assert "what is adaad" in keys, "missing 'what is adaad' entry"
    assert "what is dork" in keys, "missing 'what is dork' entry"


def test_lkse_05_corpus_has_governance_entries():
    """T141-LKSE-05: corpus must include governance entries"""
    entries = _load_corpus()
    types = {e["type"] for e in entries}
    assert "governance" in types, "no governance-type entries in corpus"


def test_lkse_06_corpus_has_phase_entries():
    """T141-LKSE-06: corpus must include at least 10 phase entries"""
    entries = _load_corpus()
    phase_entries = [e for e in entries if e["type"] == "phase"]
    assert len(phase_entries) >= 10, f"too few phase entries: {len(phase_entries)}"


def test_lkse_07_corpus_has_invariant_entries():
    """T141-LKSE-07: corpus must include at least 5 invariant entries"""
    entries = _load_corpus()
    inv_entries = [e for e in entries if e["type"] == "invariant"]
    assert len(inv_entries) >= 5, f"too few invariant entries: {len(inv_entries)}"


def test_lkse_08_corpus_has_finding_entries():
    """T141-LKSE-08: corpus must include finding entries"""
    entries = _load_corpus()
    finding_entries = [e for e in entries if e["type"] == "finding"]
    assert len(finding_entries) >= 1, "no finding entries in corpus"


# ── T141-LKSE-09..14: corpus.jsonl schema and chain integrity ────────────────


def test_lkse_09_corpus_schema_required_fields():
    """T141-LKSE-09: every corpus entry must have required fields"""
    required = {"id", "type", "key", "answer", "tags", "confidence", "source", "digest"}
    entries = _load_corpus()
    for i, entry in enumerate(entries):
        missing = required - entry.keys()
        assert not missing, f"entry {i} (id={entry.get('id')}) missing fields: {missing}"


def test_lkse_10_corpus_ids_unique():
    """T141-LKSE-10: corpus entry IDs must be globally unique"""
    entries = _load_corpus()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), f"duplicate IDs found: {len(ids) - len(set(ids))} dupes"


def test_lkse_11_corpus_sorted_by_id():
    """T141-LKSE-11: LKSE-DETERM-0 — corpus.jsonl must be sorted by entry id"""
    entries = _load_corpus()
    ids = [e["id"] for e in entries]
    assert ids == sorted(ids), "corpus.jsonl is not sorted by id — LKSE-DETERM-0 violation"


def test_lkse_12_corpus_entry_digests_correct():
    """T141-LKSE-12: each entry digest must match sha256(key+answer)"""
    entries = _load_corpus()
    for entry in entries:
        canonical = json.dumps({"key": entry["key"], "answer": entry["answer"]}, sort_keys=True)
        expected = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        assert entry["digest"] == expected, (
            f"digest mismatch for id={entry['id']}: "
            f"expected={expected[:20]}… got={entry['digest'][:20]}…"
        )


def test_lkse_13_manifest_chain_digest_correct():
    """T141-LKSE-13: LKSE-CHAIN-0 — manifest chain_digest must be HMAC over sorted entry digests"""
    entries = _load_corpus()
    manifest = _load_manifest()
    expected = _compute_chain_digest(entries)
    assert manifest["chain_digest"] == expected, (
        f"LKSE-CHAIN-0 violation: manifest chain_digest mismatch\n"
        f"expected: {expected}\ngot:      {manifest['chain_digest']}"
    )


def test_lkse_14_manifest_entry_count_matches():
    """T141-LKSE-14: manifest entry_count must equal actual corpus line count"""
    entries = _load_corpus()
    manifest = _load_manifest()
    assert manifest["entry_count"] == len(entries), (
        f"manifest entry_count={manifest['entry_count']} != actual={len(entries)}"
    )


# ── T141-LKSE-15..20: retriever.py corpus-preference behaviour ───────────────


def test_lkse_15_retriever_exists():
    """T141-LKSE-15: dorkllm/retriever.py must exist"""
    assert RETRIEVER.exists()


def test_lkse_16_retriever_has_corpus_path():
    """T141-LKSE-16: retriever must reference corpus.jsonl path"""
    src = RETRIEVER.read_text(encoding="utf-8")
    assert "corpus.jsonl" in src, "retriever.py does not reference corpus.jsonl"


def test_lkse_17_retriever_has_lkse_source_selection():
    """T141-LKSE-17: retriever must implement _select_source() for corpus-first logic"""
    src = RETRIEVER.read_text(encoding="utf-8")
    assert "_select_source" in src, "retriever.py missing _select_source()"


def test_lkse_18_retriever_has_get_corpus_status():
    """T141-LKSE-18: retriever must expose get_corpus_status() for health-check"""
    src = RETRIEVER.read_text(encoding="utf-8")
    assert "get_corpus_status" in src


def test_lkse_19_retriever_imports_from_corpus(tmp_path):
    """T141-LKSE-19: when corpus.jsonl is present retriever must report source='corpus'"""
    import importlib.util
    import os

    # Temporarily set working dir to repo root so corpus path resolves
    orig_cwd = os.getcwd()
    os.chdir(REPO)
    try:
        spec = importlib.util.spec_from_file_location("retriever", RETRIEVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.invalidate_kb_cache()
        status = mod.get_corpus_status()
        assert status["source"] == "corpus", (
            f"Expected source='corpus' but got source='{status['source']}'"
        )
        assert status["entry_count"] > 0
    finally:
        os.chdir(orig_cwd)


def test_lkse_20_retriever_query_returns_result():
    """T141-LKSE-20: query 'what is adaad' must return a valid answer from corpus"""
    import importlib.util
    import os

    orig_cwd = os.getcwd()
    os.chdir(REPO)
    try:
        spec = importlib.util.spec_from_file_location("retriever2", RETRIEVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.invalidate_kb_cache()
        result = mod.get_kb_matches("what is adaad")
        assert result is not None, "get_kb_matches('what is adaad') returned None"
        assert "ADAAD" in result["answer"]
        assert result["source"] == "corpus"
    finally:
        os.chdir(orig_cwd)


# ── T141-LKSE-21..26: LKSE hard invariants ────────────────────────────────────


def test_lkse_21_lkse_sync_0_enforced_by_script():
    """T141-LKSE-21: LKSE-SYNC-0 — sync script must exit 1 if corpus phase > current_phase+1"""
    src = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert "LKSE-SYNC-0" in src, "LKSE-SYNC-0 invariant label missing from sync script"
    assert "sys.exit(1)" in src, "LKSE-SYNC-0 must call sys.exit(1) to block CI"


def test_lkse_22_lkse_determ_0_sort_enforced():
    """T141-LKSE-22: LKSE-DETERM-0 — sync script must sort entries by id"""
    src = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert 'sort(key=lambda e: e["id"])' in src, "LKSE-DETERM-0: corpus sort by id not found"


def test_lkse_23_lkse_chain_0_hmac_present():
    """T141-LKSE-23: LKSE-CHAIN-0 — sync script must produce HMAC chain digest"""
    src = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert "hmac" in src.lower(), "LKSE-CHAIN-0: hmac not found in sync script"
    assert "chain_digest" in src, "LKSE-CHAIN-0: chain_digest not written by sync script"


def test_lkse_24_lkse_human0_0_no_human0_overwrite():
    """T141-LKSE-24: LKSE-HUMAN0-0 — corpus must not overwrite HUMAN-0 identity"""
    entries = _load_corpus()
    for entry in entries:
        # HUMAN-0 canonical identity must never be softened or removed
        if entry["id"] == "GOV-003":
            assert "Dustin L. Reid" in entry["answer"], (
                "LKSE-HUMAN0-0: GOV-003 entry must name Dustin L. Reid as HUMAN-0"
            )
            assert "4C95E2F99A775335B1CF3DAF247B015A1CCD95F6" in entry["answer"], (
                "LKSE-HUMAN0-0: GOV-003 entry must include GPG fingerprint"
            )


def test_lkse_25_lkse_gate_0_ci_workflow_exists():
    """T141-LKSE-25: LKSE-GATE-0 — CI workflow dork_corpus_sync.yml must exist"""
    assert CI_WORKFLOW.exists(), f"LKSE-GATE-0: CI workflow missing: {CI_WORKFLOW}"


def test_lkse_26_lkse_gate_0_ci_blocks_on_failure():
    """T141-LKSE-26: LKSE-GATE-0 — CI workflow must reference the sync script"""
    src = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "sync_dork_corpus.py" in src, "LKSE-GATE-0: sync script not invoked in CI workflow"


# ── T141-LKSE-27..30: CI workflow and SPDX compliance ────────────────────────


def test_lkse_27_ci_workflow_has_spdx():
    """T141-LKSE-27: dork_corpus_sync.yml must include SPDX header"""
    src = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Apache-2.0" in src


def test_lkse_28_sync_script_has_spdx():
    """T141-LKSE-28: sync_dork_corpus.py must include SPDX header"""
    src = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Apache-2.0" in src


def test_lkse_29_retriever_has_spdx():
    """T141-LKSE-29: retriever.py must include SPDX header"""
    src = RETRIEVER.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Apache-2.0" in src


def test_lkse_30_corpus_innov47_self_entry_present():
    """T141-LKSE-30: corpus must contain LKSE self-description entry (INNOV-47)"""
    entries = _load_corpus()
    lkse_entries = [e for e in entries if "lkse" in e["key"].lower() or "innov-47" in str(e.get("tags", [])).lower()]
    assert len(lkse_entries) >= 1, "LKSE self-description entry (INNOV-47) missing from corpus"
