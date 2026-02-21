# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Deterministic fitness evaluator for mutations.
"""

from __future__ import annotations

from typing import Any, Dict

from runtime import metrics
from runtime.evolution.economic_fitness import EconomicFitnessEvaluator

_ECONOMIC_EVALUATOR = EconomicFitnessEvaluator()


def _evaluate(mutation_payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _ECONOMIC_EVALUATOR.evaluate(mutation_payload)
    reasons = {
        "correctness": round(result.correctness_score, 6),
        "efficiency": round(result.efficiency_score, 6),
        "policy_compliance": round(result.policy_compliance_score, 6),
        "goal_alignment": round(result.goal_alignment_score, 6),
        "simulated_market": round(result.simulated_market_score, 6),
    }
    return {
        "score": result.score,
        "reasons": reasons,
        "weights": result.weights,
        "breakdown": result.breakdown,
        "passed_syntax": result.passed_syntax,
        "passed_tests": result.passed_tests,
        "passed_constitution": result.passed_constitution,
        "performance_delta": result.performance_delta,
    }


def score_mutation(agent_id: str, mutation_payload: Dict[str, Any]) -> float:
    """
    Deterministically score a mutation payload between 0 and 1.
    """
    result = _evaluate(mutation_payload)
    metrics.log(
        event_type="fitness_scored",
        payload={"agent": agent_id, "score": result["score"], "reasons": result["reasons"]},
        level="INFO",
    )
    return result["score"]


def explain_score(agent_id: str, mutation_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a structured explanation for a mutation score without side effects.
    """
    return _evaluate(mutation_payload)
