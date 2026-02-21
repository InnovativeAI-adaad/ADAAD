# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from runtime.evolution.goal_graph import GoalGraph


def test_goal_graph_load_and_compute_is_deterministic() -> None:
    graph = GoalGraph.load(Path("runtime/evolution/goal_graph.json"))
    state = {
        "metrics": {
            "tests_ok": 1.0,
            "survival_score": 0.8,
            "risk_score_inverse": 0.9,
            "entropy_compliance": 1.0,
            "deterministic_replay_seed": 1.0,
        },
        "capabilities": [
            "mutation_execution",
            "test_validation",
            "impact_analysis",
            "entropy_discipline",
            "audit_logging",
        ],
    }

    first = graph.compute_goal_score(state)
    second = graph.compute_goal_score(state)

    assert first == second
    assert 0.0 <= first <= 1.0


def test_goal_graph_threshold_penalty_reduces_score() -> None:
    graph = GoalGraph.load(Path("runtime/evolution/goal_graph.json"))
    strong_state = {
        "metrics": {
            "tests_ok": 1.0,
            "survival_score": 0.8,
            "risk_score_inverse": 0.9,
            "entropy_compliance": 1.0,
            "deterministic_replay_seed": 1.0,
        },
        "capabilities": [
            "mutation_execution",
            "test_validation",
            "impact_analysis",
            "entropy_discipline",
            "audit_logging",
        ],
    }
    weak_state = {
        "metrics": {
            "tests_ok": 0.0,
            "survival_score": 0.1,
            "risk_score_inverse": 0.1,
            "entropy_compliance": 0.0,
            "deterministic_replay_seed": 0.0,
        },
        "capabilities": [],
    }

    assert graph.compute_goal_score(weak_state) < graph.compute_goal_score(strong_state)
