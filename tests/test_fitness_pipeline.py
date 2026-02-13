# SPDX-License-Identifier: Apache-2.0

from runtime.fitness_pipeline import FitnessPipeline, RiskEvaluator, TestOutcomeEvaluator


def test_fitness_pipeline_composes_weighted_score() -> None:
    pipeline = FitnessPipeline([TestOutcomeEvaluator(), RiskEvaluator()])
    result = pipeline.evaluate({"tests_ok": True, "impact_risk_score": 0.2})
    assert 0.0 <= result["overall_score"] <= 1.0
    assert "tests" in result["breakdown"]
    assert "risk" in result["breakdown"]
