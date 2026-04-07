# SPDX-License-Identifier: Apache-2.0
"""Deterministic planning utilities for strategy backlog execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.intelligence.strategy import StrategyInput
from runtime.policy.action_tier_classifier import ActionTierDecision, ApprovalBehavior, classify_action


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    goal_id: str
    action_type: str
    resource_scope: str
    milestone: str
    success_predicate: str
    completion_criteria: tuple[str, ...]
    dependency_step_ids: tuple[str, ...]
    required_governance_checks: tuple[str, ...]
    required_replay_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanArtifact:
    plan_id: str
    cycle_id: str
    backlog_snapshot: tuple[tuple[str, float], ...]
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True)
class PlanExecutionState:
    plan_id: str
    current_step_index: int
    completed_step_ids: tuple[str, ...]
    progress_notes: tuple[str, ...] = ()
    last_transition_reason: str = "not_started"
    rollback_step_index: int = 0


@dataclass(frozen=True)
class PlanVerificationResult:
    ok: bool
    reason: str
    completed_step_id: str | None = None
    rollback_step_index: int | None = None
    classifier_decision: ActionTierDecision | None = None


class StrategyPlanner:
    """Convert strategy backlog goals into deterministic multi-step plans."""

    def build_plan(self, context: StrategyInput) -> PlanArtifact:
        ranked_goals = tuple(
            sorted(
                ((goal_id, float(max(weight, 0.0))) for goal_id, weight in context.goal_backlog.items()),
                key=lambda item: (-item[1], item[0]),
            )
        )
        if not ranked_goals:
            ranked_goals = (("maintain_operational_stability", 1.0),)

        steps: list[PlanStep] = [
            PlanStep(
                step_id="step_00_taxonomy_annotation",
                goal_id="taxonomy_annotation",
                action_type="analysis",
                resource_scope="docs",
                milestone="Taxonomy mapping and annotations completed",
                success_predicate="taxonomy.annotation_complete",
                completion_criteria=("taxonomy.annotation_complete", "taxonomy.coverage_complete"),
                dependency_step_ids=(),
                required_governance_checks=("policy_alignment", "taxonomy_coverage_complete"),
                required_replay_checks=("replay_preconditions_ok",),
            ),
            PlanStep(
                step_id="step_01_duplicate_assertion_audit_merge",
                goal_id="duplicate_assertion_audit_merge",
                action_type="code_change",
                resource_scope="runtime",
                milestone="Duplicate assertion audit and merge completed",
                success_predicate="assertions.duplicate_audit_merge_complete",
                completion_criteria=("assertions.duplicate_audit_merge_complete",),
                dependency_step_ids=("step_00_taxonomy_annotation",),
                required_governance_checks=("policy_alignment", "taxonomy_coverage_complete"),
                required_replay_checks=("replay_digest_match",),
            ),
            PlanStep(
                step_id="step_02_constitutional_domain_split",
                goal_id="constitutional_domain_split",
                action_type="governance_change",
                resource_scope="governance",
                milestone="Constitutional and domain assertions split completed",
                success_predicate="assertions.constitutional_domain_split_complete",
                completion_criteria=("assertions.constitutional_domain_split_complete",),
                dependency_step_ids=("step_01_duplicate_assertion_audit_merge",),
                required_governance_checks=("policy_alignment", "taxonomy_coverage_complete"),
                required_replay_checks=("replay_digest_match",),
            ),
            PlanStep(
                step_id="step_03_endpoint_parametrization",
                goal_id="endpoint_parametrization",
                action_type="orchestrator_change",
                resource_scope="app",
                milestone="Endpoint parametrization completed",
                success_predicate="endpoints.parametrization_complete",
                completion_criteria=("endpoints.parametrization_complete",),
                dependency_step_ids=("step_02_constitutional_domain_split",),
                required_governance_checks=("policy_alignment", "taxonomy_coverage_complete"),
                required_replay_checks=("replay_digest_match",),
            ),
            PlanStep(
                step_id="step_04_full_verification",
                goal_id="full_verification",
                action_type="test_change",
                resource_scope="tests",
                milestone="Full verification summary recorded",
                success_predicate="validation.full_suite_passed",
                completion_criteria=("validation.full_suite_passed", "validation.autonomous_critical_lane_passed"),
                dependency_step_ids=("step_03_endpoint_parametrization",),
                required_governance_checks=("policy_alignment", "validation_report_complete"),
                required_replay_checks=("replay_digest_match",),
            ),
        ]
        for index, (goal_id, weight) in enumerate(ranked_goals, start=5):
            normalized_goal_id = goal_id.strip() or f"goal_{index:02d}"
            dependency = steps[-1].step_id
            criteria = (f"goal.{normalized_goal_id}.completed",)
            steps.append(
                PlanStep(
                    step_id=f"step_{index:02d}_{normalized_goal_id}",
                    goal_id=normalized_goal_id,
                    action_type="runtime_change" if weight >= 0.5 else "documentation",
                    resource_scope="runtime" if weight >= 0.5 else "docs",
                    milestone=f"Milestone {index}: advance '{normalized_goal_id}'",
                    success_predicate=criteria[0],
                    completion_criteria=criteria,
                    dependency_step_ids=(dependency,),
                    required_governance_checks=("policy_alignment", "safety_constraints" if weight >= 0.5 else "policy_alignment"),
                    required_replay_checks=("replay_digest_match",),
                )
            )

        return PlanArtifact(
            plan_id=f"plan-{context.cycle_id}",
            cycle_id=context.cycle_id,
            backlog_snapshot=ranked_goals,
            steps=tuple(steps),
        )


class PlanStepVerifier:
    """Evaluate step completion with governance checks before advancing plan state."""

    def verify_step_completion(
        self,
        *,
        step: PlanStep,
        completed_step_ids: tuple[str, ...],
        completion_signals: Mapping[str, bool],
        governance_checks: Mapping[str, bool],
        replay_checks: Mapping[str, bool],
        policy_approval: bool = False,
        human_signoff_token: str | None = None,
    ) -> PlanVerificationResult:
        classifier_decision = classify_action(action_type=step.action_type, resource_scope=step.resource_scope)
        missing_dependency = next((dependency for dependency in step.dependency_step_ids if dependency not in completed_step_ids), None)
        if missing_dependency is not None:
            return PlanVerificationResult(
                ok=False,
                reason=f"dependency_not_satisfied:{missing_dependency}",
                classifier_decision=classifier_decision,
            )
        if classifier_decision.approval_behavior == ApprovalBehavior.POLICY_APPROVAL_REQUIRED and not policy_approval:
            return PlanVerificationResult(
                ok=False,
                reason="approval_required:policy_approval_missing",
                rollback_step_index=0,
                classifier_decision=classifier_decision,
            )
        if classifier_decision.approval_behavior == ApprovalBehavior.HUMAN_SIGNOFF_REQUIRED and not str(human_signoff_token or "").strip():
            return PlanVerificationResult(
                ok=False,
                reason="approval_required:human_signoff_missing",
                rollback_step_index=0,
                classifier_decision=classifier_decision,
            )
        missing_check = next((check for check in step.required_governance_checks if not governance_checks.get(check, False)), None)
        if missing_check is not None:
            return PlanVerificationResult(
                ok=False,
                reason=f"governance_check_failed:{missing_check}",
                rollback_step_index=0,
                classifier_decision=classifier_decision,
            )
        missing_replay = next((check for check in step.required_replay_checks if not replay_checks.get(check, False)), None)
        if missing_replay is not None:
            return PlanVerificationResult(
                ok=False,
                reason=f"replay_check_failed:{missing_replay}",
                rollback_step_index=0,
                classifier_decision=classifier_decision,
            )
        missing_criteria = next((criteria for criteria in step.completion_criteria if not completion_signals.get(criteria, False)), None)
        if missing_criteria is not None:
            return PlanVerificationResult(
                ok=False,
                reason=f"criteria_not_satisfied:{missing_criteria}",
                classifier_decision=classifier_decision,
            )
        return PlanVerificationResult(
            ok=True,
            reason="step_completed",
            completed_step_id=step.step_id,
            classifier_decision=classifier_decision,
        )


def initial_execution_state(plan: PlanArtifact) -> PlanExecutionState:
    return PlanExecutionState(plan_id=plan.plan_id, current_step_index=0, completed_step_ids=(), rollback_step_index=0)


def as_ledger_metrics(*, plan: PlanArtifact, state: PlanExecutionState, decision: str, verification: PlanVerificationResult | None) -> dict[str, Any]:
    active_step = plan.steps[state.current_step_index].step_id if state.current_step_index < len(plan.steps) else "completed"
    return {
        "kind": "plan_progress",
        "plan_id": plan.plan_id,
        "cycle_id": plan.cycle_id,
        "active_step": active_step,
        "completed_steps": list(state.completed_step_ids),
        "last_transition_reason": state.last_transition_reason,
        "rollback_step_index": state.rollback_step_index,
        "decision": decision,
        "verification": verification.reason if verification is not None else "not_evaluated",
        "classifier_decision": (
            {
                "tier": verification.classifier_decision.tier.value,
                "approval_behavior": verification.classifier_decision.approval_behavior.value,
                "rationale": verification.classifier_decision.rationale,
                "rule_id": verification.classifier_decision.rule_id,
                "fail_closed": verification.classifier_decision.fail_closed,
            }
            if verification is not None and verification.classifier_decision is not None
            else None
        ),
    }


def as_transition_metrics(
    *,
    plan: PlanArtifact,
    step: PlanStep | None,
    previous_state: PlanExecutionState,
    current_state: PlanExecutionState,
    verification: PlanVerificationResult | None,
) -> dict[str, Any]:
    return {
        "kind": "plan_transition",
        "plan_id": plan.plan_id,
        "cycle_id": plan.cycle_id,
        "active_step": step.step_id if step is not None else "completed",
        "from_step_index": previous_state.current_step_index,
        "to_step_index": current_state.current_step_index,
        "completed_steps": list(current_state.completed_step_ids),
        "rationale": verification.reason if verification is not None else "not_evaluated",
        "classifier_decision": (
            {
                "tier": verification.classifier_decision.tier.value,
                "approval_behavior": verification.classifier_decision.approval_behavior.value,
                "rationale": verification.classifier_decision.rationale,
                "rule_id": verification.classifier_decision.rule_id,
                "fail_closed": verification.classifier_decision.fail_closed,
            }
            if verification is not None and verification.classifier_decision is not None
            else None
        ),
        "rollback_step_index": current_state.rollback_step_index,
    }
