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
        acceptance_threshold = float(explanation.get("fitness_threshold", 0.7) or 0.7)
        accepted = base_score >= acceptance_threshold

        return {
            "score": weighted_score,
            "base_score": base_score,
            "objective_weight": objective_weight,
            "acceptance_threshold": acceptance_threshold,
            "accepted": accepted,
            "passed": accepted,
            "reasons": explanation.get("reasons", {}),
            "weights": explanation.get("weights", {}),
            "weighted_contributions": explanation.get("weighted_contributions", {}),
            "explainability": explanation.get("explainability", {}),
            "config_version": explanation.get("config_version"),
            "config_hash": explanation.get("config_hash"),
            "ranking_rationale": "ranking uses objective_weight adjusted score; acceptance uses base score threshold",
        }


__all__ = ["MutationFitnessEvaluator"]
