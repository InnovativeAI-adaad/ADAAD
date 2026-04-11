# SPDX-License-Identifier: Apache-2.0
"""Self-validation autonomy loop utilities."""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Mapping

from runtime import metrics
from runtime.autonomy.adaptive_budget import AutonomyBudgetEngine
from runtime.evolution.agm_event import ScoringEvent
from runtime.evolution.scoring_ledger import ScoringLedger
from runtime.governance.foundation.determinism import RuntimeDeterminismProvider, default_provider
from runtime.intelligence.planning import (
    PlanArtifact,
    PlanExecutionState,
    PlanStep,
    PlanStepVerifier,
    as_ledger_metrics,
    as_transition_metrics,
    initial_execution_state,
)
from runtime.intelligence.router import IntelligenceRouter
from runtime.intelligence.strategy import StrategyInput

_PLAN_LEDGER_DEFAULT_PATH = Path("security/ledger/scoring.jsonl")


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
    # Phase 19: intelligence layer output fields — all optional, default None
    intelligence_strategy_id: str | None = None
    intelligence_outcome: str | None = None
    intelligence_composite: float | None = None


class AGMStep(IntEnum):
    STEP_1 = 1
    STEP_2 = 2
    STEP_3 = 3
    STEP_4 = 4
    STEP_5 = 5
    STEP_6 = 6
    STEP_7 = 7
    STEP_8 = 8
    STEP_9 = 9
    STEP_10 = 10
    STEP_11 = 11
    STEP_12 = 12


@dataclass(frozen=True)
class AGMStepInput:
    cycle_id: str
    step: AGMStep
    revision_iteration: int
    max_revision_iterations: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class AGMStepOutput:
    ok: bool
    payload: Mapping[str, Any]
    requires_revision: bool = False
    preflight_passed: bool | None = None
    signature_commit_succeeded: bool | None = None
    fault_reason: str | None = None


@dataclass(frozen=True)
class AGMCycleResult:
    loop_result: AutonomyLoopResult
    completed_steps: tuple[AGMStep, ...]
    revision_iterations: int
    preflight_passed: bool
    signature_commit_succeeded: bool
    recovery_executed: bool
    plan_state: PlanExecutionState | None = None
    plan_artifact: PlanArtifact | None = None


AGMStepHandler = Callable[[AGMStepInput], AGMStepOutput]


def _build_strategy_input(payload: Mapping[str, Any], cycle_id: str) -> StrategyInput:
    context = dict(payload.get("strategy_input") or {})
    return StrategyInput(
        cycle_id=str(context.get("cycle_id") or cycle_id),
        mutation_score=float(context.get("mutation_score", payload.get("mutation_score", 0.0)) or 0.0),
        governance_debt_score=float(context.get("governance_debt_score", 0.0) or 0.0),
        horizon_cycles=int(context.get("horizon_cycles", 1) or 1),
        resource_budget=float(context.get("resource_budget", 1.0) or 1.0),
        goal_backlog=dict(context.get("goal_backlog") or {}),
        lineage_health=float(context.get("lineage_health", 1.0) or 1.0),
        signals=dict(context.get("signals") or {}),
    )


def _deserialize_plan_step(payload: Mapping[str, Any]) -> PlanStep:
    return PlanStep(
        step_id=str(payload.get("step_id", "")),
        goal_id=str(payload.get("goal_id", "")),
        action_type=str(payload.get("action_type", "")),
        resource_scope=str(payload.get("resource_scope", "")),
        milestone=str(payload.get("milestone", "")),
        success_predicate=str(payload.get("success_predicate", "")),
        completion_criteria=tuple(str(item) for item in payload.get("completion_criteria", [str(payload.get("success_predicate", ""))])),
        dependency_step_ids=tuple(str(item) for item in payload.get("dependency_step_ids", [])),
        required_governance_checks=tuple(str(item) for item in payload.get("required_governance_checks", [])),
        required_replay_checks=tuple(str(item) for item in payload.get("required_replay_checks", [])),
    )


def _deserialize_plan(payload: Mapping[str, Any]) -> PlanArtifact | None:
    raw = payload.get("plan_artifact")
    if not isinstance(raw, Mapping):
        return None
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list):
        return None
    return PlanArtifact(
        plan_id=str(raw.get("plan_id", "")),
        cycle_id=str(raw.get("cycle_id", payload.get("cycle_id", ""))),
        backlog_snapshot=tuple((str(goal), float(weight)) for goal, weight in raw.get("backlog_snapshot", [])),
        steps=tuple(_deserialize_plan_step(step) for step in raw_steps if isinstance(step, Mapping)),
    )


def _deserialize_state(payload: Mapping[str, Any], plan: PlanArtifact) -> PlanExecutionState:
    raw = payload.get("plan_state")
    if not isinstance(raw, Mapping):
        return initial_execution_state(plan)
    return PlanExecutionState(
        plan_id=str(raw.get("plan_id", plan.plan_id)),
        current_step_index=int(raw.get("current_step_index", 0)),
        completed_step_ids=tuple(str(step_id) for step_id in raw.get("completed_step_ids", [])),
        progress_notes=tuple(str(note) for note in raw.get("progress_notes", [])),
        last_transition_reason=str(raw.get("last_transition_reason", "resumed")),
        rollback_step_index=int(raw.get("rollback_step_index", 0)),
    )


def _to_payload_plan(plan: PlanArtifact) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "cycle_id": plan.cycle_id,
        "backlog_snapshot": [[goal_id, weight] for goal_id, weight in plan.backlog_snapshot],
        "steps": [
            {
                "step_id": step.step_id,
                "goal_id": step.goal_id,
                "action_type": step.action_type,
                "resource_scope": step.resource_scope,
                "milestone": step.milestone,
                "success_predicate": step.success_predicate,
                "completion_criteria": list(step.completion_criteria),
                "dependency_step_ids": list(step.dependency_step_ids),
                "required_governance_checks": list(step.required_governance_checks),
                "required_replay_checks": list(step.required_replay_checks),
            }
            for step in plan.steps
        ],
    }


def _to_payload_state(state: PlanExecutionState) -> dict[str, Any]:
    return {
        "plan_id": state.plan_id,
        "current_step_index": state.current_step_index,
        "completed_step_ids": list(state.completed_step_ids),
        "progress_notes": list(state.progress_notes),
        "last_transition_reason": state.last_transition_reason,
        "rollback_step_index": state.rollback_step_index,
    }


def run_agm_cycle(
    *,
    cycle_id: str,
    initial_payload: Mapping[str, Any] | None = None,
    step_handlers: Mapping[AGMStep, AGMStepHandler] | None = None,
    preflight_passed: bool = True,
    signature_commit_succeeded: bool = True,
    max_revision_iterations: int = 3,
    recovery_action: Callable[[str, AGMStep, str], None] | None = None,
    plan_ledger_path: Path | None = None,
) -> AGMCycleResult:
    if max_revision_iterations < 1:
        raise ValueError("max_revision_iterations_must_be_positive")

    payload: dict[str, Any] = dict(initial_payload or {})
    handlers = dict(step_handlers or {})
    completed_steps: list[AGMStep] = []
    revision_iteration = 0
    recovery_executed = False

    strategy_input = _build_strategy_input(payload, cycle_id)
    from runtime.intelligence.planning import StrategyPlanner

    plan_builder = StrategyPlanner()
    plan_artifact = _deserialize_plan(payload)
    if plan_artifact is None:
        plan_artifact = plan_builder.build_plan(strategy_input)

    plan_state = _deserialize_state(payload, plan_artifact)
    verifier = PlanStepVerifier()

    for step in AGMStep:
        handler = handlers.get(step)
        if handler is not None:
            output = handler(
                AGMStepInput(
                    cycle_id=cycle_id,
                    step=step,
                    revision_iteration=revision_iteration,
                    max_revision_iterations=max_revision_iterations,
                    payload=payload,
                )
            )
            payload.update(dict(output.payload))
            if output.preflight_passed is not None:
                preflight_passed = output.preflight_passed
            if output.signature_commit_succeeded is not None:
                signature_commit_succeeded = output.signature_commit_succeeded
            if not output.ok:
                reason = output.fault_reason or f"step_{int(step)}_failed"
                metrics.log(
                    event_type="STEP_FAULT",
                    payload={"cycle_id": cycle_id, "step": int(step), "reason": reason},
                    level="ERROR",
                )
                if recovery_action is not None:
                    recovery_action(cycle_id, step, reason)
                    recovery_executed = True
                break

        completed_steps.append(step)

        if step == AGMStep.STEP_5 and not preflight_passed:
            metrics.log(
                event_type="STEP_FAULT",
                payload={"cycle_id": cycle_id, "step": 5, "reason": "preflight_gate_blocked"},
                level="ERROR",
            )
            if recovery_action is not None:
                recovery_action(cycle_id, AGMStep.STEP_5, "preflight_gate_blocked")
                recovery_executed = True
            break

        if step == AGMStep.STEP_8 and handler is not None:
            while output.requires_revision:
                if revision_iteration >= max_revision_iterations:
                    reason = "step_8_revision_limit_reached"
                    metrics.log(
                        event_type="STEP_FAULT",
                        payload={"cycle_id": cycle_id, "step": 8, "reason": reason},
                        level="ERROR",
                    )
                    if recovery_action is not None:
                        recovery_action(cycle_id, AGMStep.STEP_8, reason)
                        recovery_executed = True
                    return AGMCycleResult(
                        loop_result=AutonomyLoopResult(
                            ok=False,
                            post_conditions_passed=False,
                            total_duration_ms=int(payload.get("total_duration_ms", 0)),
                            mutation_score=float(payload.get("mutation_score", 0.0)),
                            decision="escalate",
                        ),
                        completed_steps=tuple(completed_steps),
                        revision_iterations=revision_iteration,
                        preflight_passed=preflight_passed,
                        signature_commit_succeeded=signature_commit_succeeded,
                        recovery_executed=recovery_executed,
                        plan_state=plan_state,
                        plan_artifact=plan_artifact,
                    )
                revision_iteration += 1
                output = handler(
                    AGMStepInput(
                        cycle_id=cycle_id,
                        step=step,
                        revision_iteration=revision_iteration,
                        max_revision_iterations=max_revision_iterations,
                        payload=payload,
                    )
                )
                payload.update(dict(output.payload))

        if step == AGMStep.STEP_11 and not signature_commit_succeeded:
            metrics.log(
                event_type="STEP_FAULT",
                payload={"cycle_id": cycle_id, "step": 11, "reason": "signature_commit_gate_blocked"},
                level="ERROR",
            )
            if recovery_action is not None:
                recovery_action(cycle_id, AGMStep.STEP_11, "signature_commit_gate_blocked")
                recovery_executed = True
            break

    completion_signals = dict(payload.get("plan_completion_signals") or {})
    governance_checks = dict(payload.get("plan_governance_checks") or {})
    replay_checks = dict(payload.get("plan_replay_checks") or {})
    policy_approval = bool(payload.get("plan_policy_approval", False))
    human_signoff_token = payload.get("human_signoff_token")
    verification = None
    previous_state = plan_state
    active_step = None
    if plan_artifact.steps and plan_state.current_step_index < len(plan_artifact.steps):
        active_step = plan_artifact.steps[plan_state.current_step_index]
        verification = verifier.verify_step_completion(
            step=active_step,
            completed_step_ids=plan_state.completed_step_ids,
            completion_signals=completion_signals,
            governance_checks=governance_checks,
            replay_checks=replay_checks,
            policy_approval=policy_approval,
            human_signoff_token=str(human_signoff_token) if human_signoff_token is not None else None,
        )
        if verification.ok:
            plan_state = PlanExecutionState(
                plan_id=plan_state.plan_id,
                current_step_index=plan_state.current_step_index + 1,
                completed_step_ids=plan_state.completed_step_ids + (active_step.step_id,),
                progress_notes=plan_state.progress_notes + (f"{cycle_id}:{verification.reason}",),
                last_transition_reason=verification.reason,
                rollback_step_index=plan_state.rollback_step_index,
            )
        else:
            rollback_index = verification.rollback_step_index
            if rollback_index is None:
                rollback_index = plan_state.rollback_step_index
            plan_state = PlanExecutionState(
                plan_id=plan_state.plan_id,
                current_step_index=plan_state.current_step_index,
                completed_step_ids=plan_state.completed_step_ids,
                progress_notes=plan_state.progress_notes + (f"{cycle_id}:{verification.reason}",),
                last_transition_reason=verification.reason,
                rollback_step_index=int(rollback_index),
            )

    payload["plan_artifact"] = _to_payload_plan(plan_artifact)
    payload["plan_state"] = _to_payload_state(plan_state)

    decision = str(payload.get("decision", "hold"))
    ledger = ScoringLedger(path=plan_ledger_path or _PLAN_LEDGER_DEFAULT_PATH)
    ledger.append(
        ScoringEvent(
            mutation_id=f"{cycle_id}:{plan_state.current_step_index}",
            score=float(payload.get("mutation_score", 0.0)),
            metrics=as_ledger_metrics(
                plan=plan_artifact,
                state=plan_state,
                decision=decision,
                verification=verification,
            ),
        )
    )

    ledger.append(
        ScoringEvent(
            mutation_id=f"{cycle_id}:transition",
            score=float(payload.get("mutation_score", 0.0)),
            metrics=as_transition_metrics(
                plan=plan_artifact,
                step=active_step,
                previous_state=previous_state,
                current_state=plan_state,
                verification=verification,
            ),
        )
    )

    return AGMCycleResult(
        loop_result=AutonomyLoopResult(
            ok=bool(payload.get("all_actions_ok", True)),
            post_conditions_passed=bool(payload.get("post_conditions_passed", True)),
            total_duration_ms=int(payload.get("total_duration_ms", 0)),
            mutation_score=float(payload.get("mutation_score", 0.0)),
            decision=decision,
        ),
        completed_steps=tuple(completed_steps),
        revision_iterations=revision_iteration,
        preflight_passed=preflight_passed,
        signature_commit_succeeded=signature_commit_succeeded,
        recovery_executed=recovery_executed,
        plan_state=plan_state,
        plan_artifact=plan_artifact,
    )


def run_self_check_loop(
    *,
    cycle_id: str,
    actions: list[AgentAction],
    post_condition_checks: dict[str, Callable[[], bool]],
    mutation_score: float,
    mutate_threshold: float | None = None,
    budget_engine: AutonomyBudgetEngine | None = None,
    governance_debt_score: float = 0.0,
    fitness_trend_delta: float = 0.0,
    epoch_pass_rate: float = 1.0,
    lineage_health: float | None = None,  # Phase 19: structural_refactor / conservative_hold triggers
    replay_mode: str = "off",
    recovery_tier: str | None = None,
    provider: RuntimeDeterminismProvider | None = None,
    duration_ms: int | None = None,
    elapsed_duration_ms: int | None = None,
) -> AutonomyLoopResult:
    warnings.warn(
        "run_self_check_loop is deprecated; use run_agm_cycle instead",
        DeprecationWarning,
        stacklevel=2,
    )
    effective_provider = provider or (budget_engine.provider if budget_engine is not None else None) or default_provider()

    mode = replay_mode.strip().lower()
    tier = (recovery_tier or "").strip().lower()
    strict_or_audit = mode in {"strict", "audit"} or tier == "audit"

    duration_override_ms = duration_ms if duration_ms is not None else elapsed_duration_ms

    started_ts: float | None = None
    if duration_override_ms is None:
        if strict_or_audit:
            if not getattr(effective_provider, "deterministic", False):
                raise RuntimeError("deterministic_timestamp_required")
            started_ts = effective_provider.now_utc().timestamp()
        else:
            started_ts = time.time()
    budget_snapshot = None
    active_threshold = 0.7 if mutate_threshold is None else float(mutate_threshold)
    if budget_engine is not None:
        budget_snapshot = budget_engine.record_snapshot(
            cycle_id=cycle_id,
            governance_debt_score=governance_debt_score or 0.0,
            fitness_trend_delta=fitness_trend_delta or 0.0,
            epoch_pass_rate=epoch_pass_rate or 1.0,
        )
        active_threshold = budget_snapshot.threshold

    routed_intelligence = IntelligenceRouter().route(
        StrategyInput(
            cycle_id=cycle_id,
            mutation_score=mutation_score,
            governance_debt_score=governance_debt_score,
            lineage_health=lineage_health if lineage_health is not None else 1.0,
            signals={"epoch_pass_rate": epoch_pass_rate},
        )
    )

    all_actions_ok = all(a.ok for a in actions) if actions else True
    post_conditions_passed = all(fn() for fn in post_condition_checks.values()) if post_condition_checks else True

    if not all_actions_ok or not post_conditions_passed:
        decision = "escalate"
    elif mutation_score >= active_threshold:
        decision = "self_mutate"
    else:
        decision = "hold"

    if duration_override_ms is not None:
        total_duration_ms = int(duration_override_ms)
    elif strict_or_audit:
        finished_ts = effective_provider.now_utc().timestamp()
        total_duration_ms = int((finished_ts - (started_ts or finished_ts)) * 1000)
    else:
        total_duration_ms = int((time.time() - (started_ts or time.time())) * 1000)
    metrics.log(
        event_type="autonomy_cycle_summary",
        payload={
            "cycle_id": cycle_id,
            "all_actions_ok": all_actions_ok,
            "post_conditions_passed": post_conditions_passed,
            "mutation_score": mutation_score,
            "mutate_threshold": active_threshold,
            "threshold_source": "adaptive_budget" if budget_snapshot else "static",
            "budget_snapshot_hash": budget_snapshot.snapshot_hash if budget_snapshot else None,
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
        intelligence_strategy_id=routed_intelligence.strategy.strategy_id,
        intelligence_outcome=routed_intelligence.outcome,
        intelligence_composite=routed_intelligence.critique.weighted_aggregate,
    )


# ---------------------------------------------------------------------------
# Phase 19 — AutonomyLoop: stateful wrapper with persistent IntelligenceRouter
# ---------------------------------------------------------------------------

class AutonomyLoop:
    """Stateful autonomy loop that holds a persistent IntelligenceRouter.

    Phase 19: Resolves the ephemeral-router gap — `IntelligenceRouter()` was
    previously instantiated fresh on every `run_self_check_loop()` call, making
    Phase 18's `CritiqueSignalBuffer` accumulation permanently ineffective.

    This class holds one `IntelligenceRouter` instance across all `run()` calls,
    so breach-rate penalties accumulate within an epoch as intended. Call
    `reset_epoch()` explicitly at epoch boundaries to clear the buffer.

    The existing `run_self_check_loop()` function remains unchanged for backward
    compatibility — it continues to instantiate a fresh router per call.

    Phase 21: Adds `telemetry_ledger_path` kwarg for persistent chain-verified
    telemetry. When `None` (default), uses `InMemoryTelemetrySink` — behaviour
    is identical to v4.5.0. When a path is provided, uses `FileTelemetrySink`
    so routing decisions survive process restarts and are chain-verifiable.
    The environment variable `ADAAD_TELEMETRY_LEDGER_PATH` is also checked at
    construction; an explicit kwarg takes precedence over the env var.
    """

    def __init__(
        self,
        *,
        budget_engine: "AutonomyBudgetEngine | None" = None,
        router: "IntelligenceRouter | None" = None,
        telemetry_ledger_path: "Path | str | None" = None,
    ) -> None:
        import os as _os
        from runtime.intelligence.router import IntelligenceRouter as _Router
        from runtime.intelligence.routed_decision_telemetry import RoutedDecisionTelemetry as _RDT

        self._budget_engine = budget_engine

        # Phase 21: resolve telemetry sink
        _ledger_path: "Path | None" = None
        if telemetry_ledger_path is not None:
            _ledger_path = Path(telemetry_ledger_path)
        else:
            _env_path = _os.environ.get("ADAAD_TELEMETRY_LEDGER_PATH", "").strip()
            if _env_path:
                _ledger_path = Path(_env_path)

        if _ledger_path is not None:
            from runtime.intelligence.file_telemetry_sink import FileTelemetrySink as _FTS
            self._file_sink: "_FTS | None" = _FTS(_ledger_path)
            _telemetry = _RDT(sink=self._file_sink.emit)
        else:
            self._file_sink = None
            _telemetry = _RDT()  # InMemoryTelemetrySink default

        self._router: IntelligenceRouter = router if router is not None else _Router(telemetry=_telemetry)

    def run(
        self,
        *,
        cycle_id: str,
        actions: "list[AgentAction]",
        post_condition_checks: "dict[str, Callable[[], bool]]",
        mutation_score: float,
        mutate_threshold: float | None = None,
        governance_debt_score: float = 0.0,
        fitness_trend_delta: float = 0.0,
        epoch_pass_rate: float = 1.0,
        lineage_health: float | None = None,
        replay_mode: str = "off",
        recovery_tier: str | None = None,
        provider: "RuntimeDeterminismProvider | None" = None,
        duration_ms: int | None = None,
        elapsed_duration_ms: int | None = None,
    ) -> AutonomyLoopResult:
        """Run one autonomy loop cycle using the persistent IntelligenceRouter.

        Equivalent to `run_self_check_loop()` except the router (and its
        CritiqueSignalBuffer) persists across calls, enabling Phase 18 feedback.
        """
        import time as _time
        import warnings as _warnings
        from runtime.intelligence.strategy import StrategyInput

        effective_provider = (
            provider
            or (self._budget_engine.provider if self._budget_engine is not None else None)
            or default_provider()
        )

        mode = replay_mode.strip().lower()
        tier = (recovery_tier or "").strip().lower()
        strict_or_audit = mode in {"strict", "audit"} or tier == "audit"
        duration_override_ms = duration_ms if duration_ms is not None else elapsed_duration_ms

        started_ts: float | None = None
        if duration_override_ms is None:
            if strict_or_audit:
                if not getattr(effective_provider, "deterministic", False):
                    raise RuntimeError("deterministic_timestamp_required")
                started_ts = effective_provider.now_utc().timestamp()
            else:
                started_ts = _time.time()

        budget_snapshot = None
        active_threshold = 0.7 if mutate_threshold is None else float(mutate_threshold)
        if self._budget_engine is not None:
            budget_snapshot = self._budget_engine.record_snapshot(
                cycle_id=cycle_id,
                governance_debt_score=governance_debt_score or 0.0,
                fitness_trend_delta=fitness_trend_delta or 0.0,
                epoch_pass_rate=epoch_pass_rate or 1.0,
            )
            active_threshold = budget_snapshot.threshold

        # Phase 19: use persistent router so CritiqueSignalBuffer accumulates.
        routed_intelligence = self._router.route(
            StrategyInput(
                cycle_id=cycle_id,
                mutation_score=mutation_score,
                governance_debt_score=governance_debt_score,
                lineage_health=lineage_health if lineage_health is not None else 1.0,
                signals={"epoch_pass_rate": epoch_pass_rate},
            )
        )

        all_actions_ok = all(a.ok for a in actions) if actions else True
        post_conditions_passed = (
            all(fn() for fn in post_condition_checks.values())
            if post_condition_checks
            else True
        )

        if not all_actions_ok or not post_conditions_passed:
            decision = "escalate"
        elif mutation_score >= active_threshold:
            decision = "self_mutate"
        else:
            decision = "hold"

        if duration_override_ms is not None:
            total_duration_ms = int(duration_override_ms)
        elif strict_or_audit:
            finished_ts = effective_provider.now_utc().timestamp()
            total_duration_ms = int((finished_ts - (started_ts or finished_ts)) * 1000)
        else:
            total_duration_ms = int((_time.time() - (started_ts or _time.time())) * 1000)

        return AutonomyLoopResult(
            ok=all_actions_ok,
            post_conditions_passed=post_conditions_passed,
            total_duration_ms=total_duration_ms,
            mutation_score=mutation_score,
            decision=decision,
            intelligence_strategy_id=routed_intelligence.strategy.strategy_id,
            intelligence_outcome=routed_intelligence.outcome,
            intelligence_composite=routed_intelligence.critique.weighted_aggregate,
        )

    def reset_epoch(self) -> None:
        """Clear the CritiqueSignalBuffer at epoch boundary.

        Call this explicitly when a new epoch begins to prevent breach-rate
        penalties from prior epochs carrying over into the next.
        """
        self._router.reset_epoch()

    @property
    def router(self) -> "IntelligenceRouter":
        """Expose the persistent router for inspection and testing."""
        return self._router

    @property
    def file_sink(self):
        """Return the active FileTelemetrySink, or None when using InMemoryTelemetrySink."""
        return self._file_sink

    @property
    def telemetry_ledger_path(self) -> "Path | None":
        """Return the configured ledger path, or None if in-memory sink is active."""
        return self._file_sink._path if self._file_sink is not None else None
