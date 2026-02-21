# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.metrics_schema import EvolutionMetricsEmitter
from runtime.governance.foundation import canonical_json


def _seed_epoch(ledger: LineageLedgerV2, epoch_id: str) -> None:
    ledger.append_event("EpochStartEvent", {"epoch_id": epoch_id})
    ledger.append_event(
        "GovernanceDecisionEvent",
        {
            "epoch_id": epoch_id,
            "accepted": True,
            "reason": "accepted",
            "impact_score": 0.2,
            "entropy_consumed": 3,
            "entropy_budget": 10,
        },
    )
    ledger.append_event(
        "GovernanceDecisionEvent",
        {
            "epoch_id": epoch_id,
            "accepted": False,
            "reason": "impact_threshold_exceeded",
            "impact_score": 0.9,
            "entropy_consumed": 7,
            "entropy_budget": 10,
        },
    )
    ledger.append_event(
        "MutationBundleEvent",
        {
            "epoch_id": epoch_id,
            "bundle_id": "bundle-1",
            "impact": 0.2,
            "certificate": {"bundle_id": "bundle-1"},
        },
    )


def test_metrics_serialization_is_deterministic(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    _seed_epoch(ledger, "epoch-0001")
    emitter = EvolutionMetricsEmitter(ledger, metrics_dir=tmp_path / "metrics", history_limit=2)

    payload = emitter.emit_cycle_metrics(
        epoch_id="epoch-0001",
        cycle_id="cycle-0001",
        result={"status": "executed", "mutation_id": "m-1", "goal_score_before": 0.1, "goal_score_after": 0.6},
    )
    cycle_path = tmp_path / "metrics" / "epoch-0001" / "cycle-0001.json"
    history_path = tmp_path / "metrics" / "history.json"

    cycle_text_first = cycle_path.read_text(encoding="utf-8")
    history_text_first = history_path.read_text(encoding="utf-8")

    payload_second = emitter.emit_cycle_metrics(
        epoch_id="epoch-0001",
        cycle_id="cycle-0001",
        result={"status": "executed", "mutation_id": "m-1", "goal_score_before": 0.1, "goal_score_after": 0.6},
    )

    assert payload_second == payload
    assert cycle_path.read_text(encoding="utf-8") == cycle_text_first
    assert history_path.read_text(encoding="utf-8") == history_text_first
    assert cycle_text_first == canonical_json(payload) + "\n"
    assert "efficiency_ratio" in payload
    assert (tmp_path / "metrics" / "epoch-0001" / "summary.json").exists()
    assert (tmp_path / "metrics" / "patterns.json").exists()


def test_metrics_replay_equivalence_and_bounded_history(tmp_path: Path) -> None:
    source_ledger = LineageLedgerV2(tmp_path / "source.jsonl")
    _seed_epoch(source_ledger, "epoch-0002")

    replay_ledger = LineageLedgerV2(tmp_path / "replay.jsonl")
    for entry in source_ledger.read_all():
        replay_ledger.append_event(str(entry.get("type") or ""), dict(entry.get("payload") or {}))

    source_emitter = EvolutionMetricsEmitter(source_ledger, metrics_dir=tmp_path / "metrics-source", history_limit=2)
    replay_emitter = EvolutionMetricsEmitter(replay_ledger, metrics_dir=tmp_path / "metrics-replay", history_limit=2)

    result = {"status": "rejected", "mutation_id": "m-2", "goal_score_delta": -0.2, "efficiency_score": 0.3, "cost_units": 11}
    source_payload = source_emitter.emit_cycle_metrics(epoch_id="epoch-0002", cycle_id="cycle-0002", result=result)
    replay_payload = replay_emitter.emit_cycle_metrics(epoch_id="epoch-0002", cycle_id="cycle-0002", result=result)

    assert source_payload == replay_payload
    assert "efficiency_ratio" in source_payload

    source_emitter.emit_cycle_metrics(epoch_id="epoch-0003", cycle_id="cycle-0001", result=result)
    source_emitter.emit_cycle_metrics(epoch_id="epoch-0004", cycle_id="cycle-0001", result=result)
    history_entries = json.loads((tmp_path / "metrics-source" / "history.json").read_text(encoding="utf-8"))["entries"]

    assert len(history_entries) == 2
    assert [(item["epoch_id"], item["cycle_id"]) for item in history_entries] == [
        ("epoch-0003", "cycle-0001"),
        ("epoch-0004", "cycle-0001"),
    ]


def test_epoch_summary_contains_ewma_and_volatility(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage.jsonl")
    _seed_epoch(ledger, "epoch-0099")
    emitter = EvolutionMetricsEmitter(ledger, metrics_dir=tmp_path / "metrics", history_limit=5)
    emitter.emit_cycle_metrics(epoch_id="epoch-0099", cycle_id="cycle-1", result={"goal_score_delta": 0.2, "entropy_spent": 2, "mutation_operator": "set"})
    emitter.emit_cycle_metrics(epoch_id="epoch-0099", cycle_id="cycle-2", result={"goal_score_delta": 0.1, "entropy_spent": 1, "mutation_operator": "set"})

    summary = json.loads((tmp_path / "metrics" / "epoch-0099" / "summary.json").read_text(encoding="utf-8"))
    assert "ewma" in summary
    assert "volatility" in summary
    assert "local_optima_risk" in summary

    patterns = json.loads((tmp_path / "metrics" / "patterns.json").read_text(encoding="utf-8"))
    assert patterns["patterns"]
    assert "selection_hint" in patterns["patterns"][0]
