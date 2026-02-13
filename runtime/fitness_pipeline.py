# SPDX-License-Identifier: Apache-2.0
"""Composable fitness pipeline for mutation scoring."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class FitnessMetric:
    name: str
    weight: float
    score: float
    metadata: Dict[str, Any]


class FitnessEvaluator(ABC):
    @abstractmethod
    def evaluate(self, mutation_data: Dict[str, Any]) -> FitnessMetric:
        raise NotImplementedError


class TestOutcomeEvaluator(FitnessEvaluator):
    def evaluate(self, mutation_data: Dict[str, Any]) -> FitnessMetric:
        tests_ok = bool(mutation_data.get("tests_ok"))
        return FitnessMetric(
            name="tests",
            weight=0.5,
            score=1.0 if tests_ok else 0.0,
            metadata={"tests_ok": tests_ok},
        )


class RiskEvaluator(FitnessEvaluator):
    def evaluate(self, mutation_data: Dict[str, Any]) -> FitnessMetric:
        risk_score = float(mutation_data.get("impact_risk_score", 0.0) or 0.0)
        return FitnessMetric(
            name="risk",
            weight=0.5,
            score=max(0.0, min(1.0, 1.0 - risk_score)),
            metadata={"impact_risk_score": risk_score},
        )


class FitnessPipeline:
    def __init__(self, evaluators: List[FitnessEvaluator]):
        self.evaluators = evaluators

    def evaluate(self, mutation_data: Dict[str, Any]) -> Dict[str, Any]:
        metrics = [e.evaluate(mutation_data) for e in self.evaluators]
        total_weight = sum(m.weight for m in metrics) or 1.0
        weighted_score = sum(m.score * m.weight for m in metrics) / total_weight
        return {
            "overall_score": weighted_score,
            "metrics": [m.__dict__ for m in metrics],
            "breakdown": {m.name: m.score for m in metrics},
        }


__all__ = [
    "FitnessMetric",
    "FitnessEvaluator",
    "TestOutcomeEvaluator",
    "RiskEvaluator",
    "FitnessPipeline",
]
