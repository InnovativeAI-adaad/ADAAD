# SPDX-License-Identifier: Apache-2.0

"""
Enhanced fitness scoring with domain-specific heuristics.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from runtime import metrics
from runtime.governance.foundation import safe_get


def score_trait_addition(mutation_payload: Dict[str, Any]) -> float:
    """Reward adding useful capabilities."""
    content = mutation_payload.get("content", {})
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = {}

    traits = content.get("traits", [])
    trait_score = min(len(traits) / 5.0, 1.0)
    valuable_traits = {"type_aware", "test_generator", "error_handler"}
    bonus = sum(0.1 for trait in traits if trait in valuable_traits)
    return min(trait_score + bonus, 1.0)


def score_metadata_quality(mutation_payload: Dict[str, Any]) -> float:
    """Reward well-documented mutations."""
    content = mutation_payload.get("content", {})
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return 0.3

    has_timestamp = "last_mutation" in content
    has_version = "version" in content
    has_lineage = "lineage" in content

    fields_present = sum([has_timestamp, has_version, has_lineage])
    return 0.4 + (fields_present * 0.2)


def score_mutation_enhanced(agent_id: str, mutation_payload: Dict[str, Any]) -> float:
    """
    Enhanced scoring that considers mutation semantics.
    """
    if not mutation_payload.get("parent"):
        return 0.0

    intent = mutation_payload.get("intent", "unknown")

    if intent == "add_capability":
        score = score_trait_addition(mutation_payload)
    elif intent == "add_metadata":
        score = score_metadata_quality(mutation_payload)
    elif intent == "increment_version":
        score = 0.6
    else:
        score = 0.5

    metrics.log(
        event_type="fitness_scored_v2",
        payload={
            "agent": agent_id,
            "intent": intent,
            "score": score,
        },
        level="INFO",
    )

    return score


def _clamp(value: float, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return max(floor, min(value, ceiling))


def _estimate_op_complexity(ops: Any) -> Tuple[int, int]:
    if not isinstance(ops, list):
        return 0, 0
    count = 0
    size = 0
    for op in ops:
        if not isinstance(op, dict):
            continue
        count += 1
        for key in ("value", "content", "source", "code"):
            if key not in op:
                continue
            value = op.get(key)
            if isinstance(value, (dict, list)):
                try:
                    serialized = json.dumps(value, sort_keys=True)
                except TypeError:
                    serialized = str(value)
                size += len(serialized)
            elif value is not None:
                size += len(str(value))
    return count, size


def _score_constitutional_compliance(payload: Dict[str, Any]) -> float:
    verified = payload.get("verified")
    if verified is True:
        return 1.0
    if verified is False:
        return 0.0
    return 0.7


def _score_stability_heuristics(payload: Dict[str, Any]) -> float:
    tests_ok = payload.get("tests_ok")
    if tests_ok is True:
        base = 1.0
    elif tests_ok is False:
        base = 0.2
    else:
        base = 0.6

    applied = safe_get(payload, "lineage", "applied")
    skipped = safe_get(payload, "lineage", "skipped")
    if isinstance(applied, (int, float)) and isinstance(skipped, (int, float)):
        denom = max(applied + skipped, 1.0)
        success_ratio = float(applied) / denom
    else:
        success_ratio = 0.5

    return _clamp(0.6 * base + 0.4 * success_ratio)


def _score_performance_delta(payload: Dict[str, Any]) -> float:
    if "performance_delta" in payload:
        return _clamp(float(payload.get("performance_delta", 0.0)))
    count, size = _estimate_op_complexity(payload.get("ops"))
    complexity = count * 50 + size
    return _clamp(1.0 - min(complexity / 5000.0, 1.0))


def _score_resource_efficiency(payload: Dict[str, Any]) -> float:
    if "resource_efficiency" in payload:
        return _clamp(float(payload.get("resource_efficiency", 0.0)))
    count, size = _estimate_op_complexity(payload.get("ops"))
    overhead = count * 0.05 + size / 10000.0
    return _clamp(1.0 - overhead)


def _score_lineage_distance(payload: Dict[str, Any]) -> float:
    applied = safe_get(payload, "lineage", "applied")
    if not isinstance(applied, (int, float)):
        return 0.5
    if applied <= 0:
        return 0.2
    return _clamp(min(applied / 3.0, 1.0))


def score_mutation_survival(agent_id: str, strategy_id: str, mutation_payload: Dict[str, Any]) -> float:
    """
    Compute a composite survival score with interpretable components.
    """
    components = {
        "constitutional_compliance": _score_constitutional_compliance(mutation_payload),
        "stability_heuristics": _score_stability_heuristics(mutation_payload),
        "performance_delta": _score_performance_delta(mutation_payload),
        "resource_efficiency": _score_resource_efficiency(mutation_payload),
        "lineage_distance": _score_lineage_distance(mutation_payload),
    }
    weights = {
        "constitutional_compliance": 0.25,
        "stability_heuristics": 0.25,
        "performance_delta": 0.2,
        "resource_efficiency": 0.15,
        "lineage_distance": 0.15,
    }
    score = sum(components[key] * weights[key] for key in components)
    score = _clamp(score)

    metrics.log(
        event_type="mutation_survival_scored",
        payload={
            "agent": agent_id,
            "strategy_id": strategy_id,
            "score": score,
            "components": components,
            "weights": weights,
        },
        level="INFO",
    )

    return score


__all__ = ["score_mutation_enhanced", "score_mutation_survival"]
