# SPDX-License-Identifier: Apache-2.0
"""Agent role contracts used for deterministic orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SandboxPermission(str, Enum):
    READ_ONLY = "read_only"
    RESTRICTED_WRITE = "restricted_write"
    EXECUTION = "execution"
    GOVERNANCE = "governance"


@dataclass(frozen=True)
class AgentRoleSpec:
    name: str
    responsibilities: tuple[str, ...]
    interface: tuple[str, ...]
    input_schema: tuple[str, ...]
    output_schema: tuple[str, ...]
    error_policy: str
    sandbox_permission: SandboxPermission


def default_role_specs() -> dict[str, AgentRoleSpec]:
    return {
        "ArchitectAgent": AgentRoleSpec(
            name="ArchitectAgent",
            responsibilities=(
                "define iteration objectives",
                "compose execution graph",
                "produce dependency-aware work plans",
            ),
            interface=("plan(context)", "handoff()"),
            input_schema=("context", "constraints", "epoch_id"),
            output_schema=("milestones", "risk_register", "handoff_contract"),
            error_policy="fail_closed_on_ambiguous_scope",
            sandbox_permission=SandboxPermission.READ_ONLY,
        ),
        "ExecutorAgent": AgentRoleSpec(
            name="ExecutorAgent",
            responsibilities=(
                "execute approved tasks",
                "apply deterministic code changes",
                "emit execution telemetry",
            ),
            interface=("execute(task)", "report()"),
            input_schema=("task", "artifacts", "sandbox_profile"),
            output_schema=("execution_result", "artifacts_written", "timings_ms"),
            error_policy="stop_and_escalate_on_non_deterministic_effect",
            sandbox_permission=SandboxPermission.EXECUTION,
        ),
        "ValidatorAgent": AgentRoleSpec(
            name="ValidatorAgent",
            responsibilities=(
                "run acceptance tests",
                "verify post_conditions",
                "produce pass_fail evidence",
            ),
            interface=("validate(result)",),
            input_schema=("execution_result", "test_plan", "baseline_digest"),
            output_schema=("valid", "failed_checks", "coverage_delta"),
            error_policy="block_promotion_on_any_failed_required_check",
            sandbox_permission=SandboxPermission.RESTRICTED_WRITE,
        ),
        "MutatorAgent": AgentRoleSpec(
            name="MutatorAgent",
            responsibilities=(
                "propose mutation candidates",
                "score candidate risk_vs_reward",
                "emit mutation manifests",
            ),
            interface=("propose()", "score(candidate)"),
            input_schema=("lineage_state", "fitness_signals", "policy_constraints"),
            output_schema=("candidates", "selection_reason", "manifest_stub"),
            error_policy="dry_run_only_when_risk_uncertain",
            sandbox_permission=SandboxPermission.RESTRICTED_WRITE,
        ),
        "GovernanceAgent": AgentRoleSpec(
            name="GovernanceAgent",
            responsibilities=(
                "enforce constitutional gates",
                "certify promotion decisions",
                "append audit events",
            ),
            interface=("adjudicate(proposal)", "certify()"),
            input_schema=("proposal", "constitution", "trust_attestation"),
            output_schema=("accepted", "reason", "certificate_ref"),
            error_policy="fail_closed_and_log_rejection",
            sandbox_permission=SandboxPermission.GOVERNANCE,
        ),
    }
