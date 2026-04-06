# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
import pytest
pytestmark = pytest.mark.regression_standard

from runtime.intelligence.planning import PlanStepVerifier, StrategyPlanner
from runtime.intelligence.strategy import StrategyInput


def test_strategy_planner_uses_mandatory_order_and_keeps_backlog_after_verification() -> None:
    planner = StrategyPlanner()
    plan = planner.build_plan(
        StrategyInput(
            cycle_id="cycle-42",
            mutation_score=0.2,
            governance_debt_score=0.1,
            goal_backlog={"reduce_latency": 0.2, "stabilize_replay": 0.9, "improve_coverage": 0.6},
        )
    )

    assert [step.step_id for step in plan.steps[:5]] == [
        "step_00_taxonomy_annotation",
        "step_01_duplicate_assertion_audit_merge",
        "step_02_constitutional_domain_split",
        "step_03_endpoint_parametrization",
        "step_04_full_verification",
    ]
    assert plan.steps[4].completion_criteria == (
        "validation.full_suite_passed",
        "validation.autonomous_critical_lane_passed",
    )
    assert plan.steps[5].goal_id == "stabilize_replay"
    assert plan.steps[5].dependency_step_ids == ("step_04_full_verification",)


def test_plan_step_verifier_blocks_steps_b_to_d_without_taxonomy_coverage_check() -> None:
    planner = StrategyPlanner()
    verifier = PlanStepVerifier()
    plan = planner.build_plan(
        StrategyInput(
            cycle_id="cycle-verify",
            mutation_score=0.3,
            governance_debt_score=0.1,
            goal_backlog={"secure_merge": 0.8},
        )
    )

    completed_by_step = {
        1: ("step_00_taxonomy_annotation",),
        2: ("step_00_taxonomy_annotation", "step_01_duplicate_assertion_audit_merge"),
        3: (
            "step_00_taxonomy_annotation",
            "step_01_duplicate_assertion_audit_merge",
            "step_02_constitutional_domain_split",
        ),
    }
    for step_index in (1, 2, 3):
        step = plan.steps[step_index]
        blocked = verifier.verify_step_completion(
            step=step,
            completed_step_ids=completed_by_step[step_index],
            completion_signals={step.success_predicate: True},
            governance_checks={"policy_alignment": True, "taxonomy_coverage_complete": False},
            replay_checks={"replay_digest_match": True},
            policy_approval=True,
            human_signoff_token="token-1",
        )
        assert blocked.ok is False
        assert blocked.reason == "governance_check_failed:taxonomy_coverage_complete"


def test_plan_step_verifier_requires_autonomous_critical_and_full_suite_validation_summaries() -> None:
    planner = StrategyPlanner()
    verifier = PlanStepVerifier()
    plan = planner.build_plan(
        StrategyInput(
            cycle_id="cycle-validation",
            mutation_score=0.3,
            governance_debt_score=0.1,
            goal_backlog={"secure_merge": 0.8},
        )
    )
    final_step = plan.steps[4]
    completed = tuple(step.step_id for step in plan.steps[:4])

    blocked = verifier.verify_step_completion(
        step=final_step,
        completed_step_ids=completed,
        completion_signals={"validation.full_suite_passed": True},
        governance_checks={"policy_alignment": True, "validation_report_complete": True},
        replay_checks={"replay_digest_match": True},
        policy_approval=True,
        human_signoff_token="token-1",
    )
    assert blocked.ok is False
    assert blocked.reason == "criteria_not_satisfied:validation.autonomous_critical_lane_passed"

    passed = verifier.verify_step_completion(
        step=final_step,
        completed_step_ids=completed,
        completion_signals={
            "validation.full_suite_passed": True,
            "validation.autonomous_critical_lane_passed": True,
        },
        governance_checks={"policy_alignment": True, "validation_report_complete": True},
        replay_checks={"replay_digest_match": True},
        policy_approval=True,
        human_signoff_token="token-1",
    )
    assert passed.ok is True
