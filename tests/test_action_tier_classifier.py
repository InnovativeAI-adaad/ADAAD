# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from runtime.intelligence.planning import PlanStep, PlanStepVerifier
from runtime.policy.action_tier_classifier import ApprovalBehavior, GovernanceTier, classify_action

pytestmark = pytest.mark.regression_standard


def test_classifier_uses_highest_control_tier_for_ambiguous_action_scope_pair() -> None:
    decision = classify_action(action_type="documentation", resource_scope="security")
    assert decision.tier == GovernanceTier.TIER_0
    assert decision.approval_behavior == ApprovalBehavior.HUMAN_SIGNOFF_REQUIRED
    assert decision.rule_id == "SCOPE_RULE"


def test_classifier_is_fail_closed_for_unknown_unmapped_inputs() -> None:
    decision = classify_action(action_type="custom_experimental", resource_scope="sandbox_unknown")
    assert decision.fail_closed is True
    assert decision.tier == GovernanceTier.TIER_0
    assert decision.approval_behavior == ApprovalBehavior.HUMAN_SIGNOFF_REQUIRED


def test_plan_step_verifier_enforces_policy_approval_for_tier_1() -> None:
    verifier = PlanStepVerifier()
    step = PlanStep(
        step_id="step-1",
        goal_id="runtime_goal",
        action_type="runtime_change",
        resource_scope="runtime",
        milestone="runtime update",
        success_predicate="runtime.updated",
        completion_criteria=("runtime.updated",),
        dependency_step_ids=(),
        required_governance_checks=("policy_alignment",),
    )

    blocked = verifier.verify_step_completion(
        step=step,
        completed_step_ids=(),
        completion_signals={"runtime.updated": True},
        governance_checks={"policy_alignment": True},
        replay_checks={},
        policy_approval=False,
    )
    assert blocked.ok is False
    assert blocked.reason == "approval_required:policy_approval_missing"


def test_plan_step_verifier_requires_human_signoff_for_tier_0() -> None:
    verifier = PlanStepVerifier()
    step = PlanStep(
        step_id="step-0",
        goal_id="constitution_goal",
        action_type="governance_change",
        resource_scope="governance",
        milestone="governance update",
        success_predicate="governance.updated",
        completion_criteria=("governance.updated",),
        dependency_step_ids=(),
        required_governance_checks=("policy_alignment",),
    )

    blocked = verifier.verify_step_completion(
        step=step,
        completed_step_ids=(),
        completion_signals={"governance.updated": True},
        governance_checks={"policy_alignment": True},
        replay_checks={},
        policy_approval=True,
        human_signoff_token=None,
    )
    assert blocked.ok is False
    assert blocked.reason == "approval_required:human_signoff_missing"


def test_plan_step_verifier_allows_tier_2_autonomous_execution() -> None:
    verifier = PlanStepVerifier()
    step = PlanStep(
        step_id="step-2",
        goal_id="docs_goal",
        action_type="documentation",
        resource_scope="docs",
        milestone="docs update",
        success_predicate="docs.updated",
        completion_criteria=("docs.updated",),
        dependency_step_ids=(),
        required_governance_checks=("policy_alignment",),
    )

    passed = verifier.verify_step_completion(
        step=step,
        completed_step_ids=(),
        completion_signals={"docs.updated": True},
        governance_checks={"policy_alignment": True},
        replay_checks={},
    )
    assert passed.ok is True
    assert passed.classifier_decision is not None
    assert passed.classifier_decision.tier == GovernanceTier.TIER_2
