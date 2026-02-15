# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from runtime.evolution.promotion_policy import PromotionPolicyEngine, PromotionPolicyError
from runtime.evolution.promotion_state_machine import PromotionState


def test_priority_rule_ordering_highest_wins() -> None:
    policy = {
        "version": "v1.0.0",
        "rules": [
            {
                "name": "to_rejected",
                "priority": 10,
                "from_state": "certified",
                "to_state": "rejected",
                "conditions": {"min_score": 0.5},
            },
            {
                "name": "to_activated",
                "priority": 20,
                "from_state": "certified",
                "to_state": "activated",
                "conditions": {"min_score": 0.5},
            },
        ],
    }
    engine = PromotionPolicyEngine(policy)
    result = engine.evaluate_transition(PromotionState.CERTIFIED, {"score": 0.8})
    assert result == PromotionState.ACTIVATED


def test_duplicate_priority_rejected() -> None:
    policy = {
        "version": "v1.0.0",
        "rules": [
            {"name": "r1", "priority": 10, "from_state": "certified", "to_state": "activated", "conditions": {}},
            {"name": "r2", "priority": 10, "from_state": "certified", "to_state": "rejected", "conditions": {}},
        ],
    }
    with pytest.raises(PromotionPolicyError):
        PromotionPolicyEngine(policy)


def test_legacy_policy_shape_still_supported() -> None:
    policy = {
        "schema_version": "1.0",
        "policy_id": "default",
        "minimum_score": 0.7,
        "blocked_conditions": [],
        "risk_ceiling": 0.8,
    }
    engine = PromotionPolicyEngine(policy)
    assert engine.evaluate_transition(PromotionState.CERTIFIED, {"score": 0.75, "risk_score": 0.5}) == PromotionState.ACTIVATED
    assert engine.evaluate_transition(PromotionState.CERTIFIED, {"score": 0.5, "risk_score": 0.5}) == PromotionState.REJECTED


def test_simulation_gate_blocks_activation() -> None:
    policy = {
        "version": "v1.0.0",
        "rules": [
            {
                "name": "activated_if_simulation_passes",
                "priority": 20,
                "from_state": "certified",
                "to_state": "activated",
                "conditions": {"min_score": 0.5, "require_simulation_pass": True},
            },
            {
                "name": "fallback_reject",
                "priority": 10,
                "from_state": "certified",
                "to_state": "rejected",
                "conditions": {},
            },
        ],
    }
    engine = PromotionPolicyEngine(policy)
    result = engine.evaluate_transition(PromotionState.CERTIFIED, {"score": 0.8, "simulation_verdict": {"passed": False, "status": "failed"}})
    assert result == PromotionState.REJECTED


def test_simulation_candidate_is_evaluated_for_policy() -> None:
    policy = {
        "version": "v1.0.0",
        "rules": [
            {
                "name": "activated_if_simulation_passes",
                "priority": 20,
                "from_state": "certified",
                "to_state": "activated",
                "conditions": {"min_score": 0.5, "require_simulation_pass": True},
            }
        ],
    }
    candidate = {
        "candidate_id": "m-2",
        "baseline": {"error_rate": 0.01, "latency_ms": 100.0, "success_rate": 0.99},
        "constraints": {"max_error_rate_delta": 0.02, "max_latency_delta_ms": 30.0, "min_success_rate_delta": -0.05},
        "cohorts": [
            {"cohort_id": "cohort_a", "observed": {"error_rate": 0.011, "latency_ms": 101.0, "success_rate": 0.99}},
            {"cohort_id": "cohort_b", "observed": {"error_rate": 0.011, "latency_ms": 102.0, "success_rate": 0.99}},
            {"cohort_id": "cohort_c", "observed": {"error_rate": 0.011, "latency_ms": 101.0, "success_rate": 0.99}},
            {"cohort_id": "cohort_d", "observed": {"error_rate": 0.011, "latency_ms": 102.0, "success_rate": 0.99}},
        ],
    }
    mutation_data = {"score": 0.8, "simulation_candidate": candidate}
    engine = PromotionPolicyEngine(policy)
    assert engine.evaluate_transition(PromotionState.CERTIFIED, mutation_data) == PromotionState.ACTIVATED
    assert mutation_data["simulation_verdict"]["passed"] is True
