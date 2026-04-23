# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

from adaad.agents.mutation_engine import MutationEngine
from adaad.agents.mutation_request import MutationRequest


def _request(intent: str) -> MutationRequest:
    return MutationRequest(agent_id="agent", intent=intent, ops=[])


def test_mutation_engine_prefers_positive_score_trend(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    state_path = tmp_path / "state.json"
    rows = [
        {"event": "mutation_score", "payload": {"strategy_id": "alpha", "score": 0.2}},
        {"event": "mutation_score", "payload": {"strategy_id": "alpha", "score": 0.9}},
        {"event": "mutation_score", "payload": {"strategy_id": "beta", "score": 0.7}},
        {"event": "mutation_score", "payload": {"strategy_id": "beta", "score": 0.65}},
    ]
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    engine = MutationEngine(metrics_path=metrics_path, state_path=state_path)
    engine.refresh_state_from_metrics()

    selected, scores = engine.select([_request("alpha"), _request("beta")])

    assert selected is not None
    assert selected.intent == "alpha"
    assert scores["alpha"] > scores["beta"]
