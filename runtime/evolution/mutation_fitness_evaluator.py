# SPDX-License-Identifier: Apache-2.0
"""Deterministic mutation fitness evaluator for EvolutionKernel."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from runtime import fitness


class MutationFitnessEvaluator:
    """Evaluate mutation fitness against an optional goal graph."""

    def evaluate(self, agent_id: str, mutation: Mapping[str, Any], goal_graph: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        explanation = fitness.explain_score(agent_id, dict(mutation))
        base_score = float(explanation.get("score", 0.0) or 0.0)

        objective_weight = 1.0
        if goal_graph and isinstance(goal_graph, Mapping):
            objectives = goal_graph.get("objectives")
            if isinstance(objectives, list):
                objective_weight = min(1.0, max(0.0, float(len(objectives)) / 10.0))

        weighted_score = max(0.0, min(1.0, base_score * objective_weight))
        return {
            "score": weighted_score,
            "base_score": base_score,
            "objective_weight": objective_weight,
            "reasons": explanation.get("reasons", {}),
            "passed": weighted_score >= 0.7,
        }


__all__ = ["MutationFitnessEvaluator"]
