# SPDX-License-Identifier: Apache-2.0

"""
Enhanced fitness scoring with domain-specific heuristics.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from runtime import metrics


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


__all__ = ["score_mutation_enhanced"]
