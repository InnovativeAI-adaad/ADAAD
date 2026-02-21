# SPDX-License-Identifier: Apache-2.0
"""Deprecated compatibility layer for mutation fitness scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from runtime.evolution.economic_fitness import EconomicFitnessEvaluator


@dataclass(frozen=True)
class FitnessScore:
    score: float
    passed_syntax: bool
    passed_tests: bool
    passed_constitution: bool
    performance_delta: float

    def is_viable(self) -> bool:
        return self.score >= 0.7

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "passed_syntax": self.passed_syntax,
            "passed_tests": self.passed_tests,
            "passed_constitution": self.passed_constitution,
            "performance_delta": self.performance_delta,
        }


class FitnessEvaluator:
    """Legacy facade backed by :class:`EconomicFitnessEvaluator`."""

    def __init__(self) -> None:
        self._economic_evaluator = EconomicFitnessEvaluator()

    def evaluate_content(self, mutation_content: str, *, constitution_ok: bool = True) -> FitnessScore:
        result = self._economic_evaluator.evaluate_content(mutation_content, constitution_ok=constitution_ok)
        return FitnessScore(
            score=result.score,
            passed_syntax=result.passed_syntax,
            passed_tests=result.passed_tests,
            passed_constitution=result.passed_constitution,
            performance_delta=result.performance_delta,
        )


__all__ = ["FitnessScore", "FitnessEvaluator"]
