# SPDX-License-Identifier: Apache-2.0
"""Deterministic promotion policy evaluation with explicit priority ordering."""

from __future__ import annotations

from typing import Any, Dict, List

from runtime.evolution.promotion_state_machine import PromotionState
from runtime.evolution.simulation_runner import SimulationRunner


class PromotionPolicyError(ValueError):
    """Invalid promotion policy definition."""


class PromotionPolicyEngine:
    def __init__(self, policy: Dict[str, Any]) -> None:
        self.policy = dict(policy)
        self.policy_version = str(policy.get("version") or policy.get("policy_id") or "v1.0.0")
        self.rules = self._normalize_rules(self.policy)
        self._validate_priorities()
        self.simulation_runner = SimulationRunner()

    @staticmethod
    def _normalize_rules(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Backward compatible fallback to existing simple schema.
        if isinstance(policy.get("rules"), list):
            return [dict(rule) for rule in policy["rules"]]

        minimum_score = float(policy.get("minimum_score", 0.0) or 0.0)
        risk_ceiling = policy.get("risk_ceiling")
        blocked = list(policy.get("blocked_conditions", []) or [])
        reject_conditions: Dict[str, Any] = {}
        if blocked:
            reject_conditions["blocked_conditions"] = blocked

        rules: List[Dict[str, Any]] = [
            {
                "name": "legacy_approve",
                "priority": 100,
                "from_state": PromotionState.CERTIFIED.value,
                "to_state": PromotionState.ACTIVATED.value,
                "conditions": {"min_score": minimum_score, "max_risk_score": risk_ceiling},
            }
        ]
        if reject_conditions:
            rules.append(
                {
                    "name": "legacy_reject_blocked",
                    "priority": 90,
                    "from_state": PromotionState.CERTIFIED.value,
                    "to_state": PromotionState.REJECTED.value,
                    "conditions": reject_conditions,
                }
            )
        return rules

    def _validate_priorities(self) -> None:
        seen: set[tuple[str, int]] = set()
        for rule in self.rules:
            from_state = str(rule.get("from_state", ""))
            priority = int(rule.get("priority", 0) or 0)
            key = (from_state, priority)
            if key in seen:
                raise PromotionPolicyError(f"duplicate_priority:{from_state}:{priority}")
            seen.add(key)

    def _sorted_rules(self, from_state: PromotionState) -> List[Dict[str, Any]]:
        relevant = [r for r in self.rules if str(r.get("from_state")) == from_state.value]
        return sorted(relevant, key=lambda r: int(r.get("priority", 0) or 0), reverse=True)

    @staticmethod
    def _rule_matches(conditions: Dict[str, Any], mutation_data: Dict[str, Any]) -> bool:
        score = float(mutation_data.get("score", 0.0) or 0.0)
        if "min_score" in conditions and score < float(conditions["min_score"]):
            return False

        if "max_risk_score" in conditions and conditions["max_risk_score"] is not None:
            risk_score = float(mutation_data.get("risk_score", 0.0) or 0.0)
            if risk_score > float(conditions["max_risk_score"]):
                return False

        if "blocked_conditions" in conditions:
            observed = set(mutation_data.get("blocked_conditions", []) or [])
            expected = set(conditions.get("blocked_conditions", []) or [])
            if observed.intersection(expected):
                return True
            return False

        if "risk_tiers" in conditions:
            if str(mutation_data.get("risk_tier", "")) not in set(conditions.get("risk_tiers", []) or []):
                return False

        if "max_entropy_bits" in conditions:
            if int(mutation_data.get("entropy_bits", 0) or 0) > int(conditions["max_entropy_bits"]):
                return False

        if conditions.get("require_simulation_pass"):
            verdict = dict(mutation_data.get("simulation_verdict") or {})
            if not verdict or not bool(verdict.get("passed")):
                return False

        required_statuses = list(conditions.get("simulation_status_in") or [])
        if required_statuses:
            verdict_status = str((mutation_data.get("simulation_verdict") or {}).get("status") or "")
            if verdict_status not in set(str(item) for item in required_statuses):
                return False

        return True

    def evaluate_transition(self, current_state: PromotionState, mutation_data: Dict[str, Any]) -> PromotionState:
        if "simulation_verdict" not in mutation_data and "simulation_candidate" in mutation_data:
            mutation_data["simulation_verdict"] = self.simulation_runner.run(dict(mutation_data["simulation_candidate"]), dry_run=True)

        for rule in self._sorted_rules(current_state):
            conditions = dict(rule.get("conditions") or {})
            if self._rule_matches(conditions, mutation_data):
                target = str(rule.get("to_state") or "REJECTED")
                return PromotionState(target.lower()) if target.islower() else PromotionState[target]
        return PromotionState.REJECTED


__all__ = ["PromotionPolicyEngine", "PromotionPolicyError"]
