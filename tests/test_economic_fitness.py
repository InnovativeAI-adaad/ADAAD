# SPDX-License-Identifier: Apache-2.0

from runtime.evolution.economic_fitness import EconomicFitnessEvaluator
from runtime.evolution.fitness import FitnessEvaluator


def test_economic_fitness_is_deterministic() -> None:
    evaluator = EconomicFitnessEvaluator()
    payload = {
        "content": "mutation: candidate",
        "tests_ok": True,
        "sandbox_ok": True,
        "constitution_ok": True,
        "policy_valid": True,
        "goal_graph": {"alignment_score": 0.8},
        "task_value_proxy": {"value_score": 0.75},
        "platform": {"memory_mb": 2048, "cpu_percent": 20, "runtime_ms": 2000},
    }
    first = evaluator.evaluate(payload)
    second = evaluator.evaluate(payload)
    assert first.to_dict() == second.to_dict()


def test_legacy_fitness_facade_keeps_old_schema() -> None:
    legacy = FitnessEvaluator().evaluate_content("mutation: candidate", constitution_ok=True)
    payload = legacy.to_dict()
    assert set(payload) == {
        "score",
        "passed_syntax",
        "passed_tests",
        "passed_constitution",
        "performance_delta",
    }


def test_economic_fitness_rebalances_weights_from_history() -> None:
    evaluator = EconomicFitnessEvaluator(rebalance_interval=1)
    original = dict(evaluator.weights)
    history = [
        {
            "goal_score_delta": 0.5,
            "fitness_component_scores": {
                "correctness_score": 1.0,
                "efficiency_score": 0.0,
                "policy_compliance_score": 0.0,
                "goal_alignment_score": 0.0,
                "simulated_market_score": 0.0,
            },
        }
    ]
    tuned = evaluator.rebalance_from_history(history)
    assert tuned["correctness_score"] >= original["correctness_score"]
    assert abs(sum(tuned.values()) - 1.0) < 1e-9
