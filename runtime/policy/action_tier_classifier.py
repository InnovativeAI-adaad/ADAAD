# SPDX-License-Identifier: Apache-2.0
"""Deterministic classifier for plan action governance tiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

try:  # Python 3.11+
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python <= 3.10 compatibility
    class StrEnum(str, Enum):
        pass


class GovernanceTier(StrEnum):
    TIER_0 = "tier_0"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"


class ApprovalBehavior(StrEnum):
    AUTONOMOUS_ALLOWED = "autonomous_allowed"
    POLICY_APPROVAL_REQUIRED = "policy_approval_required"
    HUMAN_SIGNOFF_REQUIRED = "human_signoff_required"


@dataclass(frozen=True)
class ActionTierDecision:
    tier: GovernanceTier
    approval_behavior: ApprovalBehavior
    rationale: str
    rule_id: str
    fail_closed: bool = False


_ACTION_RULES: dict[str, tuple[GovernanceTier, str]] = {
    "constitutional_change": (GovernanceTier.TIER_0, "constitution mutation is always high-control"),
    "governance_change": (GovernanceTier.TIER_0, "governance mutation requires highest scrutiny"),
    "security_control_change": (GovernanceTier.TIER_0, "security control mutations are fail-closed"),
    "runtime_change": (GovernanceTier.TIER_1, "runtime changes require policy review"),
    "orchestrator_change": (GovernanceTier.TIER_1, "orchestration logic affects execution gates"),
    "code_change": (GovernanceTier.TIER_1, "code change may alter behavior"),
    "test_change": (GovernanceTier.TIER_1, "test suites influence release gates"),
    "documentation": (GovernanceTier.TIER_2, "docs updates are autonomy-safe by default"),
    "evidence_update": (GovernanceTier.TIER_2, "evidence updates are record-only"),
    "analysis": (GovernanceTier.TIER_2, "analysis-only action is non-mutating"),
}

_SCOPE_RULES: dict[str, tuple[GovernanceTier, str]] = {
    "constitution": (GovernanceTier.TIER_0, "resource scope touches constitution"),
    "governance": (GovernanceTier.TIER_0, "resource scope touches governance policies"),
    "security": (GovernanceTier.TIER_0, "resource scope touches security controls"),
    "runtime": (GovernanceTier.TIER_1, "resource scope touches runtime execution code"),
    "app": (GovernanceTier.TIER_1, "resource scope touches app behavior"),
    "tests": (GovernanceTier.TIER_1, "resource scope touches quality gates"),
    "docs": (GovernanceTier.TIER_2, "resource scope is documentation-only"),
    "evidence": (GovernanceTier.TIER_2, "resource scope is evidence-only"),
}


def _normalize(value: str) -> str:
    return value.strip().lower()


def _approval_for_tier(tier: GovernanceTier) -> ApprovalBehavior:
    if tier == GovernanceTier.TIER_0:
        return ApprovalBehavior.HUMAN_SIGNOFF_REQUIRED
    if tier == GovernanceTier.TIER_1:
        return ApprovalBehavior.POLICY_APPROVAL_REQUIRED
    return ApprovalBehavior.AUTONOMOUS_ALLOWED


def _tier_rank(tier: GovernanceTier) -> int:
    if tier == GovernanceTier.TIER_0:
        return 0
    if tier == GovernanceTier.TIER_1:
        return 1
    return 2


def classify_action(*, action_type: str, resource_scope: str) -> ActionTierDecision:
    normalized_action = _normalize(action_type)
    normalized_scope = _normalize(resource_scope)
    if not normalized_action or not normalized_scope:
        return ActionTierDecision(
            tier=GovernanceTier.TIER_0,
            approval_behavior=ApprovalBehavior.HUMAN_SIGNOFF_REQUIRED,
            rationale="missing action_type/resource_scope; fail-closed",
            rule_id="FAIL_CLOSED_MISSING_FIELDS",
            fail_closed=True,
        )

    action_rule = _ACTION_RULES.get(normalized_action)
    scope_rule = _SCOPE_RULES.get(normalized_scope)

    if action_rule is None and scope_rule is None:
        return ActionTierDecision(
            tier=GovernanceTier.TIER_0,
            approval_behavior=ApprovalBehavior.HUMAN_SIGNOFF_REQUIRED,
            rationale=(
                f"unmapped action_type='{normalized_action}' and resource_scope='{normalized_scope}'; fail-closed"
            ),
            rule_id="FAIL_CLOSED_UNMAPPED",
            fail_closed=True,
        )

    candidates: list[tuple[GovernanceTier, str, str]] = []
    if action_rule is not None:
        candidates.append((action_rule[0], action_rule[1], "ACTION_RULE"))
    if scope_rule is not None:
        candidates.append((scope_rule[0], scope_rule[1], "SCOPE_RULE"))

    selected = min(candidates, key=lambda item: (_tier_rank(item[0]), item[2]))
    return ActionTierDecision(
        tier=selected[0],
        approval_behavior=_approval_for_tier(selected[0]),
        rationale=selected[1],
        rule_id=selected[2],
        fail_closed=False,
    )


__all__ = [
    "ActionTierDecision",
    "ApprovalBehavior",
    "GovernanceTier",
    "classify_action",
]
