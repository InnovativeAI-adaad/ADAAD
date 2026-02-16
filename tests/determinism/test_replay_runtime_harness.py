# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime.evolution.governor import EvolutionGovernor
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.evolution.runtime import EvolutionRuntime
from runtime.governance.foundation import SeededDeterminismProvider


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _build_bundle_payload(epoch_id: str, mutation_index: int) -> dict:
    bundle_id = f"bundle-{mutation_index:04d}"
    impact = round(0.1 + ((mutation_index % 7) * 0.01), 4)
    strategy_set = [f"strategy-{mutation_index % 3}"]
    certificate = {
        "bundle_id": bundle_id,
        "strategy_set": strategy_set,
        "strategy_snapshot_hash": f"sha256:snapshot-{mutation_index:04d}",
        "strategy_version_set": ["v1"],
    }
    return {
        "epoch_id": epoch_id,
        "bundle_id": bundle_id,
        "impact": impact,
        "certificate": certificate,
        "strategy_set": strategy_set,
    }


def _run_replay_harness(tmp_path: Path, mutation_count: int) -> dict:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    epoch_id = f"epoch-integration-{mutation_count}"

    ledger.append_event("EpochStartEvent", {"epoch_id": epoch_id, "ts": "2026-02-10T14:00:00Z"})

    fixtures: list[dict] = []
    for mutation_index in range(mutation_count):
        payload = _build_bundle_payload(epoch_id, mutation_index)
        epoch_digest = ledger.append_bundle_with_digest(epoch_id, payload)
        fixtures.append(
            {
                "index": mutation_index,
                "bundle_id": payload["bundle_id"],
                "bundle_digest": ledger.compute_bundle_digest(payload),
                "epoch_digest": epoch_digest,
            }
        )

    ledger.append_event("EpochEndEvent", {"epoch_id": epoch_id, "ts": "2026-02-10T14:30:00Z"})

    manifest = {
        "epoch_id": epoch_id,
        "mutation_count": mutation_count,
        "fixtures": fixtures,
        "expected_epoch_digest": ledger.get_epoch_digest(epoch_id),
    }
    manifest_canonical = _canonical_json(manifest)
    manifest_hash = hashlib.sha256(manifest_canonical.encode("utf-8")).hexdigest()

    runtime = EvolutionRuntime()
    runtime.ledger = ledger
    runtime.governor = EvolutionGovernor(ledger=ledger, provider=SeededDeterminismProvider(seed="runtime-harness"))
    runtime.replay_engine = ReplayEngine(ledger)

    runtime.current_epoch_id = epoch_id
    runtime.baseline_id = "baseline-integration"
    runtime.baseline_hash = "sha256:baseline-integration"
    runtime.baseline_store.find_for_epoch = lambda _epoch_id: {
        "epoch_id": epoch_id,
        "baseline_id": "baseline-integration",
        "baseline_hash": "sha256:baseline-integration",
    }

    verify_result = runtime.verify_epoch(epoch_id)
    preflight_result = runtime.replay_preflight("audit", epoch_id=epoch_id)
    replay_result = runtime.replay_engine.replay_epoch(epoch_id)

    replay_events = [
        entry["payload"]
        for entry in ledger.read_epoch(epoch_id)
        if entry.get("type") == "ReplayVerificationEvent"
    ]
    return {
        "manifest": manifest,
        "manifest_canonical": manifest_canonical,
        "manifest_hash": manifest_hash,
        "verify_result": verify_result,
        "preflight_result": preflight_result,
        "replay_result": replay_result,
        "replay_events": replay_events,
    }


def _assert_runtime_parity(result: dict) -> None:
    expected_digest = result["manifest"]["expected_epoch_digest"]
    verify_result = result["verify_result"]
    preflight_item = result["preflight_result"]["results"][0]
    replay_result = result["replay_result"]

    assert verify_result["passed"]
    assert verify_result["expected_digest"] == expected_digest
    assert verify_result["actual_digest"] == expected_digest
    assert verify_result["digest"] == expected_digest

    assert replay_result["digest"] == expected_digest
    assert preflight_item["passed"]
    assert preflight_item["expected_digest"] == expected_digest
    assert preflight_item["actual_digest"] == expected_digest

    assert len(result["replay_events"]) == 2
    for replay_event in result["replay_events"]:
        assert replay_event["epoch_digest"] == expected_digest
        assert replay_event["replay_digest"] == expected_digest
        assert replay_event["replay_passed"] is True
        assert replay_event["replay_score"] == 1.0
        assert replay_event["cause_buckets"] == {
            "digest_mismatch": False,
            "baseline_mismatch": False,
            "time_input_variance": False,
            "external_dependency_variance": False,
        }

    assert result["manifest_canonical"] == _canonical_json(result["manifest"])


def test_replay_runtime_harness_parity_for_10_mutations(tmp_path: Path) -> None:
    result = _run_replay_harness(tmp_path, mutation_count=10)
    _assert_runtime_parity(result)
    assert result["manifest"]["mutation_count"] == 10
    assert len(result["manifest"]["fixtures"]) == 10


def test_replay_runtime_harness_parity_for_100_mutations(tmp_path: Path) -> None:
    result = _run_replay_harness(tmp_path, mutation_count=100)
    _assert_runtime_parity(result)
    assert result["manifest"]["mutation_count"] == 100
    assert len(result["manifest"]["fixtures"]) == 100
