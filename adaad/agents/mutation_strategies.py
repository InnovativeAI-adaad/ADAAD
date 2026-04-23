# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
_AGENT_CONTRACT_EXCLUDED = True  # infrastructure module — not a governed agent contract

"""
Concrete mutation strategies that generate actionable ops.
"""


import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Tuple

from runtime.api.app_layer import LLMProviderClient, load_provider_config, now_iso


_CANONICAL_FILE_KEYS = ("file", "filepath", "target")
_CANONICAL_CONTENT_KEYS = ("content", "source", "code", "value")
_FILE_ALIASES = ("file", "filepath", "target", "filename", "file_path", "target_file")
_CONTENT_ALIASES = ("content", "source", "code", "value", "new_code", "updated_code", "new_source")


def _first_string(mapping: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def canonicalize_generated_op(raw_op: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize generated operation payload fields into canonical preflight keys."""
    op = dict(raw_op)

    has_file_key = any(isinstance(op.get(key), str) and op.get(key).strip() for key in _CANONICAL_FILE_KEYS)
    if not has_file_key:
        resolved_target = _first_string(op, _FILE_ALIASES)
        if resolved_target:
            op["target"] = resolved_target

    has_content_key = any(key in op for key in _CANONICAL_CONTENT_KEYS)
    if not has_content_key:
        resolved_content = _first_string(op, _CONTENT_ALIASES)
        if resolved_content is not None:
            op["source"] = resolved_content

    return op


def adapt_generated_ops(raw_ops: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Apply canonical field normalization to generated mutation operations."""
    normalized: List[Dict[str, Any]] = []
    for raw_op in raw_ops:
        normalized.append(canonicalize_generated_op(raw_op))
    return normalized


def adapt_generated_request_payload(raw_payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize generated payload shape before MutationRequest construction."""
    payload = dict(raw_payload)
    payload["ops"] = adapt_generated_ops(payload.get("ops") or [])

    targets = payload.get("targets") or []
    normalized_targets: List[Dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        target_payload = dict(target)
        adapted_target_ops = adapt_generated_ops(target_payload.get("ops") or [])
        target_path = target_payload.get("path")
        if isinstance(target_path, str) and target_path.strip():
            for op in adapted_target_ops:
                if not any(isinstance(op.get(key), str) and op.get(key).strip() for key in _CANONICAL_FILE_KEYS):
                    op["target"] = target_path
        target_payload["ops"] = adapted_target_ops
        normalized_targets.append(target_payload)
    if "targets" in payload:
        payload["targets"] = normalized_targets

    return payload


def analyze_dna(agent_dir: Path) -> Dict[str, Any]:
    """Extract current state from agent DNA."""
    dna_path = agent_dir / "dna.json"
    if not dna_path.exists():
        return {}
    return json.loads(dna_path.read_text(encoding="utf-8"))


def add_capability_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Add a new capability trait to agent DNA."""
    dna = analyze_dna(agent_dir)
    current_traits = dna.get("traits", [])

    candidate_traits = [
        "type_aware",
        "test_generator",
        "complexity_reducer",
        "error_handler",
        "performance_optimizer",
    ]

    new_traits = [trait for trait in candidate_traits if trait not in current_traits]
    if not new_traits:
        return []

    return [
        {
            "op": "set",
            "path": "/traits",
            "value": current_traits + [new_traits[0]],
        }
    ]


def increment_version_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Bump the agent's internal version counter."""
    dna = analyze_dna(agent_dir)
    current_version = dna.get("version", 0)

    return [
        {
            "op": "set",
            "path": "/version",
            "value": current_version + 1,
        }
    ]


def add_metadata_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Enrich DNA with operational metadata."""
    dna = analyze_dna(agent_dir)
    mutation_count = int(dna.get("mutation_count", 0))

    return [
        {
            "op": "set",
            "path": "/last_mutation",
            "value": now_iso(),
        },
        {
            "op": "set",
            "path": "/mutation_count",
            "value": mutation_count + 1,
        },
    ]


def ai_propose_strategy(agent_dir: Path) -> List[Dict[str, Any]]:
    """Invoke configured LLM provider and return normalized mutation ops."""
    dna = analyze_dna(agent_dir)
    goal_default = os.getenv("ADAAD_AI_STRATEGY_GOAL", "Improve agent fitness while preserving stability")
    context_default = os.getenv("ADAAD_AI_STRATEGY_CONTEXT", "mutation_cycle")

    goal = dna.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        goals = dna.get("goals")
        if isinstance(goals, list):
            goal = next((entry for entry in goals if isinstance(entry, str) and entry.strip()), "")
    if not isinstance(goal, str) or not goal.strip():
        goal = goal_default

    context = dna.get("context")
    if not isinstance(context, str) or not context.strip():
        context = context_default

    config = load_provider_config()
    client = LLMProviderClient(
        config=config,
        schema_validator=lambda payload: isinstance(payload.get("ops"), list),
    )
    result = client.request_json(
        system_prompt=(
            "You are a deterministic mutation proposer. Return JSON only with an ops array. "
            "Each op must reference file/path and source content when modifying code."
        ),
        user_prompt=(
            f"Goal: {goal}\n"
            f"Context: {context}\n"
            f"Agent DNA: {json.dumps(dna, sort_keys=True)}\n"
            "Respond with JSON object: {\"ops\": [...]}"
        ),
    )

    payload = result.payload if isinstance(result.payload, dict) else {}
    raw_ops = payload.get("ops") if isinstance(payload.get("ops"), list) else []
    adapted_ops = adapt_generated_ops([op for op in raw_ops if isinstance(op, Mapping)])
    if adapted_ops:
        return adapted_ops

    persist_hints = os.getenv("ADAAD_AI_STRATEGY_PERSIST_HINTS", "").strip().lower() in {"1", "true", "yes", "on"}
    if persist_hints and not result.ok:
        return [
            {
                "op": "set",
                "path": "/ai_strategy",
                "value": {
                    "goal": goal,
                    "context": context,
                    "provider_status": result.error_code or "provider_unavailable",
                    "updated_at": now_iso(),
                },
            }
        ]

    return []


@dataclass
class MutationStrategy:
    name: str
    generator: Callable[[Path], List[Dict[str, Any]]]
    required_traits: Iterable[str] = field(default_factory=tuple)
    required_capabilities: Iterable[str] = field(default_factory=tuple)
    intent_label: str = ""
    skill_weight: float = 0.5

    def matches(self, dna: Mapping[str, Any]) -> bool:
        traits = set(dna.get("traits", []) or [])
        capabilities = set(dna.get("capabilities", []) or [])
        if not set(self.required_traits).issubset(traits):
            return False
        if not set(self.required_capabilities).issubset(capabilities):
            return False
        return True

    def generate_ops(self, agent_dir: Path) -> List[Dict[str, Any]]:
        return self.generator(agent_dir)


class StrategyRegistry:
    def __init__(self, strategies: Iterable[MutationStrategy]) -> None:
        self._strategies = {strategy.name: strategy for strategy in strategies}

    def list(self) -> List[MutationStrategy]:
        return list(self._strategies.values())

    def get(self, name: str) -> MutationStrategy | None:
        return self._strategies.get(name)

    def get_skill_weight(self, name: str) -> float | None:
        strategy = self.get(name)
        return strategy.skill_weight if strategy else None


    def matching_strategies(self, dna: Mapping[str, Any]) -> List[MutationStrategy]:
        return [strategy for strategy in self._strategies.values() if strategy.matches(dna)]

    def select(
        self,
        agent_dir: Path,
        skill_weights: Mapping[str, float] | None = None,
        pattern_scores: Mapping[str, float] | None = None,
        confidence_threshold: float = 0.35,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        dna = analyze_dna(agent_dir)
        candidates: List[Tuple[float, MutationStrategy]] = []
        for strategy in self.matching_strategies(dna):
            weight = strategy.skill_weight
            if skill_weights and strategy.name in skill_weights:
                weight = skill_weights[strategy.name]
            if pattern_scores and strategy.name in pattern_scores:
                confidence = _pattern_confidence(pattern_scores[strategy.name])
                if confidence >= confidence_threshold:
                    weight += pattern_scores[strategy.name]
            candidates.append((weight, strategy))

        for _, strategy in sorted(candidates, key=lambda item: item[0], reverse=True):
            ops = strategy.generate_ops(agent_dir)
            if ops:
                intent = strategy.intent_label or strategy.name
                return intent, ops
        return "noop", []


DEFAULT_REGISTRY = StrategyRegistry(
    [
        MutationStrategy(
            name="add_capability",
            generator=add_capability_strategy,
            required_traits=(),
            required_capabilities=(),
            intent_label="add_capability",
            skill_weight=0.6,
        ),
        MutationStrategy(
            name="increment_version",
            generator=increment_version_strategy,
            required_traits=(),
            required_capabilities=("versioning",),
            intent_label="increment_version",
            skill_weight=0.65,
        ),
        MutationStrategy(
            name="add_metadata",
            generator=add_metadata_strategy,
            required_traits=("type_aware",),
            required_capabilities=(),
            intent_label="add_metadata",
            skill_weight=0.7,
        ),
        MutationStrategy(
            name="ai_propose",
            generator=ai_propose_strategy,
            required_traits=(),
            required_capabilities=(),
            intent_label="ai_propose",
            skill_weight=0.68,
        ),
    ]
)


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pattern_confidence(score_delta: float) -> float:
    bounded = max(0.0, min(1.0, abs(score_delta) / 0.5))
    return round(bounded, 6)


def load_pattern_scores(
    patterns_path: Path,
    *,
    context: str = "global",
    min_sample_size: int = 3,
    decay_half_life_days: float = 14.0,
) -> Dict[str, float]:
    if not patterns_path.exists():
        return {}
    try:
        data = json.loads(patterns_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    now_utc = datetime.now(timezone.utc)
    patterns = data.get("patterns", []) or []
    scores: Dict[str, float] = {}
    for entry in patterns:
        if not isinstance(entry, dict):
            continue
        pattern_id = str(entry.get("pattern_id", "")).strip()
        pattern_context = str(entry.get("context", "")).strip() or "global"
        if not pattern_id or pattern_context != context:
            continue
        sample_size = int(entry.get("sample_size", 0) or 0)
        if sample_size < min_sample_size:
            continue
        success_rate = float(entry.get("success_rate", 0.5) or 0.5)
        success_rate = max(0.0, min(1.0, success_rate))
        last_used = _parse_iso8601(entry.get("last_used_at"))
        if last_used is None:
            continue
        age_days = max(0.0, (now_utc - last_used).total_seconds() / 86400.0)
        decay = math.pow(0.5, age_days / max(decay_half_life_days, 0.1))
        calibrated = 0.5 + ((success_rate - 0.5) * decay)
        scores[pattern_id] = round(calibrated - 0.5, 6)
    return scores


def load_skill_weights(state_path: Path) -> Dict[str, float]:
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    stats = data.get("stats", {}) or {}
    weights: Dict[str, float] = {}
    for name, entry in stats.items():
        if not isinstance(entry, dict):
            continue
        weight = entry.get("skill_weight")
        if isinstance(weight, (int, float)):
            weights[name] = float(weight)
    return weights


def select_strategy(
    agent_dir: Path,
    skill_weights: Mapping[str, float] | None = None,
    pattern_scores: Mapping[str, float] | None = None,
    confidence_threshold: float = 0.35,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Pick a mutation strategy and generate ops."""
    return DEFAULT_REGISTRY.select(
        agent_dir,
        skill_weights=skill_weights,
        pattern_scores=pattern_scores,
        confidence_threshold=confidence_threshold,
    )


__all__ = [
    "MutationStrategy",
    "StrategyRegistry",
    "DEFAULT_REGISTRY",
    "analyze_dna",
    "canonicalize_generated_op",
    "adapt_generated_ops",
    "adapt_generated_request_payload",
    "ai_propose_strategy",
    "load_pattern_scores",
    "load_skill_weights",
    "select_strategy",
]
