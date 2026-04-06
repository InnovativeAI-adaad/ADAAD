import json
from pathlib import Path

import pytest

from runtime.governance.simulation import operator_forecast

pytestmark = pytest.mark.governance_gate


def _sample_state() -> dict:
    return {
        "blocked_reason": None,
        "last_gate_results": {"tier_0": "pass", "tier_1": "pass", "tier_2": "pass", "tier_3": "pass"},
        "open_findings": [{"id": "F-1", "status": "open"}, {"id": "F-2", "status": "resolved"}],
        "pending_evidence_rows": ["phase126-row"],
    }


def test_operator_simulation_is_deterministic_and_marked_simulated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_path = tmp_path / "operator_simulation_audit.jsonl"
    metric_calls: list[dict] = []

    monkeypatch.setattr(operator_forecast, "_OPERATOR_SIM_AUDIT_PATH", audit_path)
    monkeypatch.setattr(operator_forecast.metrics, "log", lambda event_type, payload=None, level="INFO", element_id=None: metric_calls.append({"event": event_type, "payload": payload}))

    actions = [
        {"type": "prioritize_replay_hardening", "strength": 0.7},
        {"type": "increase_review_strictness", "level": 0.5},
    ]

    first = operator_forecast.run_operator_simulation(state=_sample_state(), actions=actions, scenario_name="release-prep")
    second = operator_forecast.run_operator_simulation(state=_sample_state(), actions=actions, scenario_name="release-prep")

    assert first["simulation"] is True
    assert "SIMULATED" in first["result_label"]
    assert first["simulation_id"] == second["simulation_id"]
    assert first["predicted"]["replay_integrity"] >= first["current"]["replay_integrity"]
    assert first["predicted"]["queue_throughput"] <= first["current"]["queue_throughput"]
    assert audit_path.exists()
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    assert rows[0]["simulation_id"] == first["simulation_id"]
    assert metric_calls and metric_calls[0]["event"] == "operator_simulation_forecast"


def test_operator_simulation_unknown_action_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operator_forecast, "_OPERATOR_SIM_AUDIT_PATH", tmp_path / "operator_simulation_audit.jsonl")
    monkeypatch.setattr(operator_forecast.metrics, "log", lambda *args, **kwargs: None)

    result = operator_forecast.run_operator_simulation(
        state=_sample_state(),
        actions=[{"type": "unknown_action_type"}],
        scenario_name="unknown-action",
    )

    assert result["ok"] is True
    assert "Unknown action" in result["action_effects"][0]
    assert result["delta"]["blocker_count"] == 0
