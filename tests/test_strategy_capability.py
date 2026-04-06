# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.governance.strategy_capability import StrategyCapability


@pytest.mark.regression_standard
def test_strategy_capability_outputs_priority_stack_and_jump_links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    records = [
        {"event": "architect_scan", "payload": {"valid": True}},
        {"event": "architect_proposals", "payload": {"count": 3}},
        {"event": "dream_discovery", "payload": {"task_count": 4, "task_sample": ["a", "b"]}},
        {"event": "beast_cycle_end", "payload": {"status": "throttled", "agent": "sample"}},
    ]
    metrics_path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    monkeypatch.setattr("runtime.governance.strategy_capability.METRICS_PATH", metrics_path)

    report = StrategyCapability().build(
        epoch_id="epoch-105",
        routing_health={"health_score": 0.78},
        governance_health_score=0.74,
    )

    assert report["epoch_id"] == "epoch-105"
    assert report["readiness"]["status"] in {"green", "amber", "red"}
    assert len(report["agent_signals"]) == 3
    assert len(report["action_priority_stack"]) == 3
    assert all("jump_link" in item for item in report["action_priority_stack"])
    assert all("why_now" in item and "epoch-105" in item["why_now"] for item in report["action_priority_stack"])
    assert any(link["label"] == "Governance Health" for link in report["jump_links"])


@pytest.mark.regression_standard
def test_strategy_capability_never_emits_bypass_recommendation() -> None:
    report = StrategyCapability().build(
        epoch_id="current",
        routing_health={"health_score": 1.0},
        governance_health_score=1.0,
    )

    joined_constraints = " ".join(report["constitutional_constraints"])
    assert "bypass" in joined_constraints
    assert "no_bypass_recommendations" in report["constitutional_constraints"]
    for item in report["action_priority_stack"]:
        assert item["readiness_gate"].startswith("requires_")


@pytest.mark.regression_standard
def test_strategy_capability_is_deterministic_for_same_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(json.dumps({"event": "dream_discovery", "payload": {"task_count": 2}}) + "\n", encoding="utf-8")
    monkeypatch.setattr("runtime.governance.strategy_capability.METRICS_PATH", metrics_path)

    capability = StrategyCapability()
    first = capability.build(epoch_id="epoch-200", routing_health={"health_score": 0.8}, governance_health_score=0.8)
    second = capability.build(epoch_id="epoch-200", routing_health={"health_score": 0.8}, governance_health_score=0.8)

    assert first == second
