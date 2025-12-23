# SPDX-License-Identifier: Apache-2.0
"""
Deterministic fitness evaluator for mutations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from runtime import metrics


def _hash_content(value: Any) -> str:
    if isinstance(value, (dict, list)):
        normalized = json.dumps(value, sort_keys=True)
    else:
        normalized = str(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _schema_valid(payload: Dict[str, Any]) -> tuple[bool, str]:
    required = {"parent", "content"}
    missing = sorted(list(required - set(payload)))
    if missing:
        return False, f"missing:{','.join(missing)}"
    return True, "ok"


def _size_within_bounds(payload: Dict[str, Any]) -> tuple[bool, str]:
    content = payload.get("content", "")
    size = len(str(content))
    if size > 10_000:
        return False, "content_too_large"
    return True, "ok"


def _novelty(payload: Dict[str, Any]) -> tuple[bool, str, float]:
    parent_content = payload.get("parent_content", "")
    mutation_content = payload.get("content", "")
    parent_hash = _hash_content(parent_content)
    mutation_hash = _hash_content(mutation_content)
    if parent_hash == mutation_hash:
        return False, "no_change", 0.0
    # simple heuristic: difference contributes positively
    distance_score = 1.0
    return True, "changed", distance_score


def _evaluate(mutation_payload: Dict[str, Any]) -> Dict[str, Any]:
    score = 1.0
    schema_ok, schema_reason = _schema_valid(mutation_payload)
    if not schema_ok:
        score *= 0.0
    size_ok, size_reason = _size_within_bounds(mutation_payload)
    if not size_ok:
        score *= 0.2
    novelty_ok, novelty_reason, novelty_score = _novelty(mutation_payload)
    if novelty_ok:
        score *= novelty_score
    else:
        score *= 0.3

    score = float(max(0.0, min(score, 1.0)))
    reasons = {
        "schema": schema_reason,
        "size": size_reason,
        "novelty": novelty_reason,
    }
    return {"score": score, "reasons": reasons}


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
