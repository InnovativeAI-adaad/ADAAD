# SPDX-License-Identifier: Apache-2.0
"""Economic fitness evaluator with deterministic weighted composite scoring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

from runtime.evolution.metrics_schema import METRICS_STATE_DIR

DEFAULT_WEIGHTS = {
    "correctness_score": 0.3,
    "efficiency_score": 0.2,
    "policy_compliance_score": 0.2,
    "goal_alignment_score": 0.15,
    "simulated_market_score": 0.15,
}
DEFAULT_FITNESS_THRESHOLD = 0.7
ALLOWED_WEIGHT_KEYS = tuple(DEFAULT_WEIGHTS.keys())


@dataclass(frozen=True)
class EconomicFitnessResult:
    score: float
    correctness_score: float
    efficiency_score: float
    policy_compliance_score: float
    goal_alignment_score: float
    simulated_market_score: float
    breakdown: Dict[str, float]
    weights: Dict[str, float]
    passed_syntax: bool
    passed_tests: bool
    passed_constitution: bool
    performance_delta: float
    weighted_contributions: Dict[str, float]
    fitness_threshold: float
    config_version: int
    config_hash: str

    def is_viable(self) -> bool:
        return self.score >= self.fitness_threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "correctness_score": self.correctness_score,
            "efficiency_score": self.efficiency_score,
            "policy_compliance_score": self.policy_compliance_score,
            "goal_alignment_score": self.goal_alignment_score,
            "simulated_market_score": self.simulated_market_score,
            "breakdown": dict(self.breakdown),
            "weights": dict(self.weights),
            # backward-compatible fields
            "passed_syntax": self.passed_syntax,
            "passed_tests": self.passed_tests,
            "passed_constitution": self.passed_constitution,
            "performance_delta": self.performance_delta,
            "weighted_contributions": dict(self.weighted_contributions),
            "fitness_threshold": self.fitness_threshold,
            "config_version": self.config_version,
            "config_hash": self.config_hash,
        }


class EconomicFitnessEvaluator:
    def __init__(self, config_path: Path | None = None, *, rebalance_interval: int = 25):
        self.config_path = config_path or Path(__file__).resolve().parent / "config" / "fitness_weights.json"
        config_payload = self._read_config_payload(self.config_path)
        self.weights = self._load_weights(config_payload)
        self.config_version = self._read_config_version(config_payload)
        self.config_hash = self._compute_config_hash(config_payload)
        self.fitness_threshold = DEFAULT_FITNESS_THRESHOLD
        self.rebalance_interval = max(1, int(rebalance_interval))
        self._eval_count = 0

    @staticmethod
    def _read_config_payload(config_path: Path) -> Dict[str, Any]:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("fitness_config_invalid_payload")
        return payload

    @staticmethod
    def _read_config_version(payload: Mapping[str, Any]) -> int:
        version = int(payload.get("version", 1))
        return max(1, version)

    @staticmethod
    def _compute_config_hash(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _load_weights(payload: Mapping[str, Any]) -> Dict[str, float]:
        configured = payload.get("weights")
        if not isinstance(configured, Mapping):
            raise ValueError("fitness_config_missing_weights")

        unexpected = sorted(key for key in configured.keys() if key not in ALLOWED_WEIGHT_KEYS)
        if unexpected:
            raise ValueError(f"fitness_config_unexpected_weight_keys:{','.join(unexpected)}")

        missing = sorted(key for key in ALLOWED_WEIGHT_KEYS if key not in configured)
        if missing:
            raise ValueError(f"fitness_config_missing_weight_keys:{','.join(missing)}")

        weights = {key: max(0.0, float(configured[key])) for key in ALLOWED_WEIGHT_KEYS}
        total = sum(weights.values())
        if total <= 0.0:
            raise ValueError("fitness_config_zero_total_weight")
        return {key: value / total for key, value in weights.items()}

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _bool_from(payload: Mapping[str, Any], *keys: str) -> bool:
        for key in keys:
            if key in payload:
                return bool(payload.get(key))
        return False

    @staticmethod
    def _float_from(payload: Mapping[str, Any], *keys: str, default: float = 0.0) -> float:
        for key in keys:
            if key in payload:
                try:
                    return float(payload.get(key) or 0.0)
                except (TypeError, ValueError):
                    return default
        return default

    def rebalance_from_history(self, history_entries: List[Mapping[str, Any]]) -> Dict[str, float]:
        """Gradient-free signal amplification using goal-score contribution hints."""
        if not history_entries:
            return dict(self.weights)

        contributions = {key: 0.0 for key in DEFAULT_WEIGHTS}
        counts = {key: 0 for key in DEFAULT_WEIGHTS}
        for row in history_entries:
            goal_delta = float(row.get("goal_score_delta", 0.0) or 0.0)
            comps = row.get("fitness_component_scores")
            if not isinstance(comps, Mapping):
                continue
            for key in DEFAULT_WEIGHTS:
                if key not in comps:
                    continue
                comp = self._clamp(comps.get(key))
                contributions[key] += goal_delta * comp
                counts[key] += 1

        tuned = dict(self.weights)
        for key in DEFAULT_WEIGHTS:
            if counts[key] <= 0:
                continue
            avg = contributions[key] / float(counts[key])
            if avg > 0:
                tuned[key] = tuned[key] * 1.05
            elif avg < 0:
                tuned[key] = tuned[key] * 0.95

        total = sum(max(0.0, float(v)) for v in tuned.values())
        if total <= 0:
            return dict(self.weights)
        self.weights = {k: max(0.0, float(v)) / total for k, v in tuned.items()}
        return dict(self.weights)

    def maybe_rebalance_from_metrics(self) -> None:
        self._eval_count += 1
        if self._eval_count % self.rebalance_interval != 0:
            return
        history_path = METRICS_STATE_DIR / "history.json"
        if not history_path.exists():
            return
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            return
        entries = payload.get("entries") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            return
        self.rebalance_from_history([item for item in entries if isinstance(item, Mapping)])

    def evaluate(self, mutation_payload: Mapping[str, Any]) -> EconomicFitnessResult:
        self.maybe_rebalance_from_metrics()
        correctness = self._correctness_score(mutation_payload)
        efficiency = self._efficiency_score(mutation_payload)
        policy = self._policy_compliance_score(mutation_payload)
        goal_alignment = self._goal_alignment_score(mutation_payload)
        market = self._simulated_market_score(mutation_payload)

        breakdown = {
            "correctness_score": correctness,
            "efficiency_score": efficiency,
            "policy_compliance_score": policy,
            "goal_alignment_score": goal_alignment,
            "simulated_market_score": market,
        }
        score = sum(breakdown[name] * self.weights[name] for name in breakdown)
        weighted_contributions = {
            name: self._clamp(breakdown[name] * self.weights[name])
            for name in breakdown
        }

        passed_syntax = self._bool_from(mutation_payload, "passed_syntax", "syntax_ok")
        if not passed_syntax:
            content = str(mutation_payload.get("content", ""))
            passed_syntax = bool(content and "mutation" in content)

        passed_tests = self._bool_from(mutation_payload, "passed_tests", "tests_ok")
        passed_constitution = self._bool_from(
            mutation_payload,
            "passed_constitution",
            "constitution_ok",
            "policy_ok",
            "governance_ok",
        )
        performance_delta = self._float_from(
            mutation_payload,
            "performance_delta",
            "runtime_improvement",
            default=0.0,
        )

        return EconomicFitnessResult(
            score=self._clamp(score),
            correctness_score=correctness,
            efficiency_score=efficiency,
            policy_compliance_score=policy,
            goal_alignment_score=goal_alignment,
            simulated_market_score=market,
            breakdown=breakdown,
            weights=dict(self.weights),
            passed_syntax=passed_syntax,
            passed_tests=passed_tests,
            passed_constitution=passed_constitution,
            performance_delta=performance_delta,
            weighted_contributions=weighted_contributions,
            fitness_threshold=self.fitness_threshold,
            config_version=self.config_version,
            config_hash=self.config_hash,
        )

    def evaluate_content(self, mutation_content: str, *, constitution_ok: bool = True) -> EconomicFitnessResult:
        payload = {
            "content": mutation_content,
            "passed_syntax": bool(mutation_content and "mutation" in mutation_content),
            "tests_ok": bool(mutation_content),
            "constitution_ok": bool(constitution_ok),
            "simulated_market_score": 0.5,
        }
        return self.evaluate(payload)

    def _correctness_score(self, payload: Mapping[str, Any]) -> float:
        if "correctness_score" in payload:
            return self._clamp(payload.get("correctness_score"))
        tests_ok = self._bool_from(payload, "tests_ok", "passed_tests")
        sandbox_ok = self._bool_from(payload, "sandbox_ok", "sandbox_passed", "sandbox_valid")
        return 0.7 * (1.0 if tests_ok else 0.0) + 0.3 * (1.0 if sandbox_ok else 0.0)

    def _efficiency_score(self, payload: Mapping[str, Any]) -> float:
        if "efficiency_score" in payload:
            return self._clamp(payload.get("efficiency_score"))
        platform = payload.get("platform")
        platform_payload = platform if isinstance(platform, Mapping) else payload

        memory_mb = max(0.0, self._float_from(platform_payload, "memory_mb", default=2048.0))
        cpu_percent = max(0.0, self._float_from(platform_payload, "cpu_percent", "cpu_pct", default=0.0))
        runtime_ms = max(0.0, self._float_from(platform_payload, "runtime_ms", "duration_ms", default=0.0))

        memory_score = self._clamp(min(memory_mb, 4096.0) / 4096.0)
        cpu_score = self._clamp(1.0 - (min(cpu_percent, 100.0) / 100.0))
        runtime_score = self._clamp(1.0 - (min(runtime_ms, 120000.0) / 120000.0))
        return self._clamp((memory_score + cpu_score + runtime_score) / 3.0)

    def _policy_compliance_score(self, payload: Mapping[str, Any]) -> float:
        if "policy_compliance_score" in payload:
            return self._clamp(payload.get("policy_compliance_score"))

        if self._bool_from(payload, "policy_violation", "governance_violation"):
            return 0.0

        constitution_ok = self._bool_from(payload, "constitution_ok", "passed_constitution", "policy_ok")
        policy_valid = self._bool_from(payload, "policy_valid", "governance_ok")
        if constitution_ok and policy_valid:
            return 1.0
        if constitution_ok:
            return 0.7
        return 0.0

    def _goal_alignment_score(self, payload: Mapping[str, Any]) -> float:
        if "goal_alignment_score" in payload:
            return self._clamp(payload.get("goal_alignment_score"))

        goal_graph = payload.get("goal_graph")
        if isinstance(goal_graph, Mapping):
            for key in ("alignment_score", "score"):
                if key in goal_graph:
                    return self._clamp(goal_graph.get(key))
            completed = self._float_from(goal_graph, "completed_goals", default=0.0)
            total = max(1.0, self._float_from(goal_graph, "total_goals", default=1.0))
            return self._clamp(completed / total)
        return 0.0

    def _simulated_market_score(self, payload: Mapping[str, Any]) -> float:
        if "simulated_market_score" in payload:
            return self._clamp(payload.get("simulated_market_score"))

        market = payload.get("task_value_proxy")
        if isinstance(market, Mapping):
            value = self._float_from(market, "value_score", "score", default=0.0)
            return self._clamp(value)

        return self._clamp(self._float_from(payload, "market_score", default=0.0))


__all__ = ["EconomicFitnessResult", "EconomicFitnessEvaluator"]
