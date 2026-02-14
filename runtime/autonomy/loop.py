# SPDX-License-Identifier: Apache-2.0
"""Self-validation autonomy loop utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from runtime import metrics


@dataclass(frozen=True)
class AgentAction:
    agent: str
    action: str
    duration_ms: int
    ok: bool


@dataclass(frozen=True)
class AutonomyLoopResult:
    ok: bool
    post_conditions_passed: bool
    total_duration_ms: int
    mutation_score: float
    decision: str


def run_self_check_loop(
    *,
    cycle_id: str,
    actions: list[AgentAction],
    post_condition_checks: dict[str, Callable[[], bool]],
    mutation_score: float,
    mutate_threshold: float = 0.7,
) -> AutonomyLoopResult:
    started = time.time()
    all_actions_ok = True
    for action in actions:
        metrics.log(
            event_type="autonomy_action",
            payload={
                "cycle_id": cycle_id,
                "agent": action.agent,
                "action": action.action,
                "duration_ms": action.duration_ms,
                "ok": action.ok,
            },
            level="INFO" if action.ok else "ERROR",
            element_id=action.agent,
        )
        if not action.ok:
            all_actions_ok = False

    check_results: dict[str, bool] = {}
    for check_name, checker in sorted(post_condition_checks.items()):
        result = bool(checker())
        check_results[check_name] = result
        metrics.log(
            event_type="autonomy_post_condition",
            payload={"cycle_id": cycle_id, "check": check_name, "passed": result},
            level="INFO" if result else "ERROR",
        )

    post_conditions_passed = all(check_results.values()) if check_results else True

    if not all_actions_ok or not post_conditions_passed:
        decision = "escalate"
    elif mutation_score >= mutate_threshold:
        decision = "self_mutate"
    else:
        decision = "hold"

    total_duration_ms = int((time.time() - started) * 1000)
    metrics.log(
        event_type="autonomy_cycle_summary",
        payload={
            "cycle_id": cycle_id,
            "all_actions_ok": all_actions_ok,
            "post_conditions_passed": post_conditions_passed,
            "mutation_score": mutation_score,
            "mutate_threshold": mutate_threshold,
            "decision": decision,
            "total_duration_ms": total_duration_ms,
        },
        level="INFO" if decision != "escalate" else "ERROR",
    )
    return AutonomyLoopResult(
        ok=all_actions_ok,
        post_conditions_passed=post_conditions_passed,
        total_duration_ms=total_duration_ms,
        mutation_score=mutation_score,
        decision=decision,
    )
