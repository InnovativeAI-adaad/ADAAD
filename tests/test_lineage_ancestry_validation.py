# SPDX-License-Identifier: Apache-2.0

import hashlib
import json

import pytest

from app.agents.mutation_request import MutationRequest
from runtime import constitution
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.runtime import EvolutionRuntime
from runtime.governance.foundation.determinism import SeededDeterminismProvider


def _with_hash(prev_hash: str, entry: dict) -> dict:
    payload = dict(entry)
    payload["prev_hash"] = prev_hash
    material = prev_hash + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["hash"] = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return payload


def _request() -> MutationRequest:
    return MutationRequest(
        agent_id="lineage-test",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-static-test",
        nonce="n-1",
    )


def test_valid_ancestry_passes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"tx": "genesis", "type": "genesis", "payload": {"epoch_id": "ep-1"}})
    m1 = _with_hash(g["hash"], {"tx": "m1", "type": "mutation", "payload": {"epoch_id": "ep-1", "mutation_id": "m1"}})
    m2 = _with_hash(
        m1["hash"],
        {
            "tx": "m2",
            "type": "mutation",
            "payload": {"epoch_id": "ep-1", "mutation_id": "m2", "parent_mutation_id": "m1", "ancestor_chain": ["m1"]},
        },
    )
    genesis.write_text(json.dumps(g) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(m1) + "\n" + json.dumps(m2) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    result = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    assert result["ok"] is True


def test_broken_ancestry_halts_boot(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"tx": "genesis", "type": "genesis", "payload": {"epoch_id": "ep-1"}})
    broken = _with_hash(
        g["hash"],
        {
            "tx": "m2",
            "type": "mutation",
            "payload": {"epoch_id": "ep-1", "mutation_id": "m2", "parent_mutation_id": "missing-m1", "ancestor_chain": ["missing-m1"]},
        },
    )
    genesis.write_text(json.dumps(g) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(broken) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    runtime = EvolutionRuntime(provider=SeededDeterminismProvider(seed="lineage-test"))
    runtime.set_replay_mode("strict")
    with pytest.raises(RuntimeError, match="lineage_continuity_failed"):
        runtime.boot()
    assert runtime.fail_closed is True


def test_append_only_lineage_v2_continuity_preserved(tmp_path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.append_event("EpochCheckpointEvent", {"epoch_id": "ep-1", "epoch_digest": "sha256:0", "phase": "start"})
    ledger.append_bundle_with_digest("ep-1", {"epoch_id": "ep-1", "bundle_id": "b-1", "impact": 0.1, "certificate": {}})
    ledger.verify_integrity()
    assert len(ledger.read_all()) == 2


def test_replay_strict_produces_identical_fail_outcome(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"tx": "genesis", "type": "genesis", "payload": {"epoch_id": "ep-1"}})
    broken = _with_hash(
        g["hash"],
        {
            "tx": "m2",
            "type": "mutation",
            "payload": {"epoch_id": "ep-1", "mutation_id": "m2", "parent_mutation_id": "missing-m1"},
        },
    )
    genesis.write_text(json.dumps(g) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(broken) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    first = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    constitution._LINEAGE_VALIDATION_CACHE.clear()
    second = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())

    assert first["ok"] is False
    assert second["ok"] is False
    assert first["reason"] == second["reason"] == "lineage_violation_detected"
    assert first["details"]["missing_or_invalid_link"] == second["details"]["missing_or_invalid_link"]
    assert first["details"]["observed_reference"] == second["details"]["observed_reference"]



def test_lineage_cache_invalidates_after_journal_change(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"tx": "genesis", "type": "genesis", "payload": {"epoch_id": "ep-1"}})
    m1 = _with_hash(g["hash"], {"tx": "m1", "type": "mutation", "payload": {"epoch_id": "ep-1", "mutation_id": "m1"}})
    genesis.write_text(json.dumps(g) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(m1) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    first = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    assert first["ok"] is True

    broken = _with_hash(
        m1["hash"],
        {
            "tx": "m2",
            "type": "mutation",
            "payload": {"epoch_id": "ep-1", "mutation_id": "m2", "parent_mutation_id": "missing-parent"},
        },
    )
    journal_path.write_text(json.dumps(m1) + "\n" + json.dumps(broken) + "\n", encoding="utf-8")

    second = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    assert second["ok"] is False
    assert second["reason"] == "lineage_violation_detected"



def test_ancestor_chain_reverse_order_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"tx": "genesis", "type": "genesis", "payload": {"epoch_id": "ep-1"}})
    m1 = _with_hash(g["hash"], {"tx": "m1", "type": "mutation", "payload": {"epoch_id": "ep-1", "mutation_id": "m1"}})
    m2 = _with_hash(
        m1["hash"],
        {
            "tx": "m2",
            "type": "mutation",
            "payload": {
                "epoch_id": "ep-1",
                "mutation_id": "m2",
                "parent_mutation_id": "m1",
                "ancestor_chain": ["m1", "root"],
            },
        },
    )
    genesis.write_text(json.dumps(g) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(m1) + "\n" + json.dumps(m2) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    result = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    assert result["ok"] is False
    assert result["details"]["missing_or_invalid_link"] == "ancestor_chain_tail"


def test_missing_mutation_identity_with_parent_reference_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"tx": "genesis", "type": "genesis", "payload": {"epoch_id": "ep-1"}})
    m1 = _with_hash(g["hash"], {"tx": "m1", "type": "mutation", "payload": {"epoch_id": "ep-1"}})
    m2 = _with_hash(
        m1["hash"],
        {
            "tx": "m2",
            "type": "mutation",
            "payload": {"epoch_id": "ep-1", "mutation_id": "m2", "parent_mutation_id": "m1"},
        },
    )
    genesis.write_text(json.dumps(g) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(m1) + "\n" + json.dumps(m2) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    result = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    assert result["ok"] is False
    assert result["details"]["missing_or_invalid_link"] == "parent_mutation_id"
