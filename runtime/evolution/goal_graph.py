# SPDX-License-Identifier: Apache-2.0
"""Deterministic goal-graph scoring for multi-objective mutation evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class GoalNode:
    objective_id: str
    name: str
    metrics: Dict[str, float]
    required_capabilities: tuple[str, ...]
    child_goals: tuple["GoalNode", ...]
    completion_threshold: float
    reward_weight: float


class GoalGraph:
    """Weighted deterministic objective graph loaded from JSON."""

    def __init__(self, roots: Sequence[GoalNode]) -> None:
        self._roots = tuple(roots)

    @classmethod
    def load(cls, path: str | Path) -> "GoalGraph":
        goal_path = Path(path)
        try:
            raw = json.loads(goal_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            from runtime import metrics

            metrics.log(
                event_type="goal_graph_load_fallback",
                payload={"path": str(goal_path), "error": str(exc)},
                level="WARNING",
            )
            return cls(())
        roots_raw = raw.get("goals") or []
        roots = [cls._parse_node(node) for node in roots_raw]
        return cls(roots)

    @classmethod
    def _parse_node(cls, payload: Mapping[str, Any]) -> GoalNode:
        objective = payload.get("objective") or {}
        objective_id = str(objective.get("id") or payload.get("objective_id") or "")
        name = str(objective.get("name") or payload.get("name") or objective_id)
        metrics_raw = payload.get("metrics") or []
        metrics: Dict[str, float] = {}
        for metric in metrics_raw:
            metric_name = str(metric.get("name") or "").strip()
            if not metric_name:
                continue
            target = float(metric.get("target", 1.0) or 1.0)
            metrics[metric_name] = target if target > 0 else 1.0
        children = tuple(cls._parse_node(child) for child in (payload.get("child_goals") or []))
        capabilities = tuple(sorted({str(item).strip() for item in (payload.get("required_capabilities") or []) if str(item).strip()}))
        threshold = _clamp(float(payload.get("completion_threshold", 0.7) or 0.7))
        reward_weight = max(0.0, float(payload.get("reward_weight", 1.0) or 0.0))
        return GoalNode(
            objective_id=objective_id,
            name=name,
            metrics=metrics,
            required_capabilities=capabilities,
            child_goals=children,
            completion_threshold=threshold,
            reward_weight=reward_weight,
        )

    def compute_goal_score(self, agent_state: Mapping[str, Any]) -> float:
        if not self._roots:
            return 0.0
        total_weight = sum(node.reward_weight for node in self._roots)
        if total_weight <= 0:
            return 0.0
        weighted = sum(self._score_node(node, agent_state) * node.reward_weight for node in self._roots)
        return round(_clamp(weighted / total_weight), 6)

    def _score_node(self, node: GoalNode, agent_state: Mapping[str, Any]) -> float:
        metric_score = self._metric_score(node.metrics, agent_state.get("metrics") or {})
        capability_score = self._capability_score(node.required_capabilities, agent_state.get("capabilities") or ())
        self_score = (metric_score * 0.8) + (capability_score * 0.2)
        if node.child_goals:
            child_weight = sum(child.reward_weight for child in node.child_goals)
            if child_weight > 0:
                child_score = sum(self._score_node(child, agent_state) * child.reward_weight for child in node.child_goals) / child_weight
            else:
                child_score = 0.0
            self_score = (self_score * 0.7) + (child_score * 0.3)
        if self_score < node.completion_threshold:
            self_score *= 0.5
        return round(_clamp(self_score), 6)

    @staticmethod
    def _metric_score(targets: Mapping[str, float], state_metrics: Mapping[str, Any]) -> float:
        if not targets:
            return 1.0
        values: list[float] = []
        for metric_name in sorted(targets):
            target = max(float(targets[metric_name]), 1e-9)
            observed = float(state_metrics.get(metric_name, 0.0) or 0.0)
            values.append(_clamp(observed / target))
        return round(sum(values) / len(values), 6)

    @staticmethod
    def _capability_score(required: Iterable[str], available: Iterable[str]) -> float:
        required_set = {item for item in required}
        if not required_set:
            return 1.0
        available_set = {str(item).strip() for item in available if str(item).strip()}
        matched = len(required_set.intersection(available_set))
        return round(matched / len(required_set), 6)


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


__all__ = ["GoalGraph", "GoalNode"]
