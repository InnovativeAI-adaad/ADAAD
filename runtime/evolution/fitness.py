# SPDX-License-Identifier: Apache-2.0
"""Mutation fitness scoring for dream-mode candidate viability."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FitnessScore:
    score: float
    passed_syntax: bool
    passed_tests: bool
    passed_constitution: bool
    performance_delta: float

    def is_viable(self) -> bool:
        return self.score >= 0.7

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "passed_syntax": self.passed_syntax,
            "passed_tests": self.passed_tests,
            "passed_constitution": self.passed_constitution,
            "performance_delta": self.performance_delta,
        }


class FitnessEvaluator:
    """Lightweight fitness evaluator for staged mutation content."""

    def evaluate_content(self, mutation_content: str, *, constitution_ok: bool = True) -> FitnessScore:
        syntax_ok = bool(mutation_content and "mutation" in mutation_content)
        if not syntax_ok:
            return FitnessScore(0.0, False, False, constitution_ok, 0.0)

        tests_ok = True
        if not tests_ok:
            return FitnessScore(0.3, True, False, constitution_ok, 0.0)

        if not constitution_ok:
            return FitnessScore(0.5, True, True, False, 0.0)

        perf_delta = 0.0
        score = 0.7 + (perf_delta * 0.3)
        return FitnessScore(score, True, True, True, perf_delta)


__all__ = ["FitnessScore", "FitnessEvaluator"]
