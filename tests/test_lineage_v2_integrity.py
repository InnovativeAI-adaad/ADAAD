# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
pytestmark = pytest.mark.regression_standard

from adaad.agents.mutation_request import MutationRequest
from runtime.evolution.lineage_v2 import LineageIntegrityError, LineageLedgerV2
from runtime.evolution.runtime import EvolutionRuntime
from runtime.governance.foundation import SeededDeterminismProvider


def _rebuild_hash_chain(entries: list[dict]) -> list[dict]:
    prev_hash = "0" * 64
    rebuilt: list[dict] = []
    for entry in entries:
        normalized = {k: v for k, v in entry.items() if k != "hash"}
        normalized["prev_hash"] = prev_hash
        material = (prev_hash + json.dumps(normalized, ensure_ascii=False, sort_keys=True)).encode("utf-8")
        entry_hash = hashlib.sha256(material).hexdigest()
        normalized["hash"] = entry_hash
        rebuilt.append(normalized)
        prev_hash = entry_hash
    return rebuilt


def test_replay_tamper_fails_closed_and_blocks_governance_promotion(tmp_path: Path) -> None:
    path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(path)
    epoch_id = "ep-replay-tamper"

    ledger.append_event("EpochStartEvent", {"epoch_id": epoch_id})
    payload_a = {
        "epoch_id": epoch_id,
        "bundle_id": "b1",
        "impact": 0.1,
        "strategy_set": ["s1"],
        "certificate": {
            "bundle_id": "b1",
            "strategy_set": ["s1"],
            "strategy_snapshot_hash": "h1",
            "strategy_version_set": ["v1"],
        },
    }
    payload_b = {
        "epoch_id": epoch_id,
        "bundle_id": "b2",
        "impact": 0.2,
        "strategy_set": ["s2"],
        "certificate": {
            "bundle_id": "b2",
            "strategy_set": ["s2"],
            "strategy_snapshot_hash": "h2",
            "strategy_version_set": ["v1"],
        },
    }
    ledger.append_bundle_with_digest(epoch_id, payload_a)
    ledger.append_bundle_with_digest(epoch_id, payload_b)
    ledger.append_event("EpochEndEvent", {"epoch_id": epoch_id})

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    start, first_bundle, second_bundle, end = lines
    tampered_lines = _rebuild_hash_chain([start, second_bundle, first_bundle, end])
    path.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in tampered_lines) + "\n", encoding="utf-8")

    runtime = EvolutionRuntime()
    runtime.ledger = ledger
    runtime.governor.ledger = ledger
    runtime.replay_engine.ledger = ledger
    runtime.governor.provider = SeededDeterminismProvider(seed="tamper-check")
    runtime.set_replay_mode("strict")
    runtime.current_epoch_id = epoch_id
    runtime.baseline_id = "baseline"
    runtime.baseline_hash = "sha256:baseline"
    runtime.baseline_store.find_for_epoch = lambda _epoch: {
        "epoch_id": epoch_id,
        "baseline_id": "baseline",
        "baseline_hash": "sha256:baseline",
    }

    preflight = runtime.replay_preflight("strict", epoch_id=epoch_id)

    assert preflight["has_divergence"] is True
    assert preflight["decision"] == "fail_closed"
    assert runtime.governor.fail_closed is True

    governance_events = [
        entry["payload"]
        for entry in ledger.read_epoch(epoch_id)
        if entry.get("type") == "GovernanceDecisionEvent" and entry.get("payload", {}).get("decision") == "fail_closed"
    ]
    assert governance_events
    assert governance_events[-1]["reason"] == "replay_divergence"

    blocked = runtime.governor.validate_bundle(
        MutationRequest(
            agent_id="agent",
            generation_ts="2026-02-14T00:00:00Z",
            intent="intent",
            ops=[{"op": "noop"}],
            signature="human-recovery-valid",
            nonce="nonce",
        ),
        epoch_id,
    )
    assert blocked.accepted is False
    assert blocked.reason == "governor_fail_closed"


def test_lineage_integrity_valid_chain(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})
    ledger.append_event("MutationBundleEvent", {"epoch_id": "ep-1", "bundle_id": "b1"})

    ledger.verify_integrity()


def test_lineage_integrity_detects_single_line_tamper(tmp_path: Path) -> None:
    path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(path)
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})

    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    entry["payload"]["epoch_id"] = "ep-tampered"
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LineageIntegrityError, match="lineage_hash_mismatch"):
        ledger.verify_integrity()


def test_lineage_integrity_detects_malformed_json(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    ledger.ledger_path.write_text('{"type":"EpochStartEvent"\n', encoding="utf-8")

    with pytest.raises(LineageIntegrityError, match="lineage_invalid_json"):
        ledger.verify_integrity()


def test_lineage_append_blocked_after_corruption(tmp_path: Path) -> None:
    path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(path)
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-1"})

    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    entry["prev_hash"] = "a" * 64
    path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LineageIntegrityError, match="lineage_prev_hash_mismatch"):
        ledger.append_event("EpochEndEvent", {"epoch_id": "ep-1"})


def test_concurrent_appenders_preserve_single_canonical_tail(tmp_path: Path) -> None:
    path = tmp_path / "lineage_v2.jsonl"
    ledger = LineageLedgerV2(path)
    ledger.append_event("EpochStartEvent", {"epoch_id": "ep-concurrent"})

    barrier = threading.Barrier(2)
    outcomes: list[dict] = []
    original_last_hash = ledger._last_hash

    def synchronized_last_hash() -> str:
        tail = original_last_hash()
        # Synchronize only the first racing observation so both appenders
        # compete on the same tail_hash_before value.
        if not hasattr(synchronized_last_hash, "_done"):
            try:
                barrier.wait(timeout=2.0)
            except threading.BrokenBarrierError:
                pass
            setattr(synchronized_last_hash, "_done", True)
        return tail

    ledger._last_hash = synchronized_last_hash  # type: ignore[method-assign]

    def _append(writer_id: str) -> None:
        result = ledger.append_event(
            "MutationBundleEvent",
            {"epoch_id": "ep-concurrent", "bundle_id": writer_id, "writer": writer_id},
            max_attempts=4,
            deterministic_retry=True,
        )
        outcomes.append(result)

    t1 = threading.Thread(target=_append, args=("writer-A",))
    t2 = threading.Thread(target=_append, args=("writer-B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert all(outcome.get("status") == "committed" for outcome in outcomes)
    assert any(int(outcome.get("append_protocol", {}).get("conflict_count", 0)) >= 1 for outcome in outcomes)

    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) == 3
    assert entries[-1]["prev_hash"] == entries[-2]["hash"]
    assert entries[-2]["prev_hash"] == entries[0]["hash"]
    assert entries[-1]["hash"] != entries[-2]["hash"]

    writers_in_chain = [entry.get("payload", {}).get("writer") for entry in entries if entry.get("type") == "MutationBundleEvent"]
    assert set(writers_in_chain) == {"writer-A", "writer-B"}

    ledger.verify_integrity()
