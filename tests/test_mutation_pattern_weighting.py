import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from adaad.agents.mutation_engine import MutationEngine
from adaad.agents.mutation_request import MutationRequest
from adaad.agents.mutation_strategies import load_pattern_scores


def _request(intent: str) -> MutationRequest:
    return MutationRequest(
        agent_id="a",
        generation_ts="2026-04-23T00:00:00Z",
        intent=intent,
        ops=[],
        signature="sig",
        nonce="n",
    )


def test_refresh_state_emits_pattern_updates(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    state_path = tmp_path / "state.json"
    patterns_path = tmp_path / "patterns.json"

    ts = datetime.now(timezone.utc).isoformat()
    events = [
        {"event": "mutation_score", "timestamp": ts, "payload": {"strategy_id": "ai_propose", "score": 0.9}},
        {"event": "mutation_failed", "timestamp": ts, "payload": {"strategy_id": "ai_propose"}},
    ]
    metrics_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    engine = MutationEngine(metrics_path=metrics_path, state_path=state_path)
    engine.patterns_path = patterns_path
    engine.refresh_state_from_metrics()

    store = json.loads(patterns_path.read_text(encoding="utf-8"))
    assert store["schema_version"] == "1.0"
    assert store["patterns"][0]["pattern_id"] == "ai_propose"
    assert store["patterns"][0]["sample_size"] == 2
    assert store["patterns"][0]["success_rate"] < 0.9


def test_pattern_decay_reduces_stale_priority(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    state_path = tmp_path / "state.json"
    patterns_path = tmp_path / "patterns.json"

    old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    patterns = {
        "schema_version": "1.0",
        "patterns": [
            {
                "pattern_id": "increment_version",
                "context": "global",
                "success_rate": 1.0,
                "sample_size": 20,
                "last_used_at": old_ts,
            }
        ],
    }
    patterns_path.write_text(json.dumps(patterns), encoding="utf-8")

    engine = MutationEngine(metrics_path=metrics_path, state_path=state_path)
    engine.patterns_path = patterns_path
    delta, confidence = engine._pattern_signal("increment_version")

    assert delta < 0.05
    assert confidence < 0.25


def test_load_pattern_scores_uses_context_and_decay(tmp_path: Path) -> None:
    patterns_path = tmp_path / "patterns.json"
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    patterns_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "patterns": [
                    {
                        "pattern_id": "add_metadata",
                        "context": "mutation_cycle",
                        "success_rate": 0.8,
                        "sample_size": 12,
                        "last_used_at": recent_ts,
                    },
                    {
                        "pattern_id": "add_capability",
                        "context": "global",
                        "success_rate": 1.0,
                        "sample_size": 20,
                        "last_used_at": stale_ts,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    scores = load_pattern_scores(patterns_path, context="mutation_cycle")
    assert "add_metadata" in scores
    assert "add_capability" not in scores


def test_select_uses_pattern_confidence_threshold(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    state_path = tmp_path / "state.json"
    patterns_path = tmp_path / "patterns.json"

    now_ts = datetime.now(timezone.utc).isoformat()
    patterns_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "patterns": [
                    {
                        "pattern_id": "add_capability",
                        "context": "global",
                        "success_rate": 1.0,
                        "sample_size": 30,
                        "last_used_at": now_ts,
                    },
                    {
                        "pattern_id": "increment_version",
                        "context": "global",
                        "success_rate": 0.0,
                        "sample_size": 30,
                        "last_used_at": now_ts,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    engine = MutationEngine(metrics_path=metrics_path, state_path=state_path)
    engine.patterns_path = patterns_path
    selected, _ = engine.select([_request("add_capability"), _request("increment_version")])
    assert selected is not None
    assert selected.intent == "add_capability"
