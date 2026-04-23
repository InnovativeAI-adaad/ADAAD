# SPDX-License-Identifier: Apache-2.0
"""Autonomy loop entrypoint that runs staged orchestration cycles."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from adaad.orchestrator.bootstrap import bootstrap_tool_registry
from adaad.orchestrator.dispatcher import dispatch
from adaad.orchestrator.evidence_orchestrator import create_default_evidence_orchestrator
from adaad.orchestrator.remediation import format_blocked_state
from adaad.orchestrator.runbook_composer import compose_runbook, export_runbook_artifacts
from adaad.orchestrator.status import build_status_report


_CONTINUOUS_FLAG = "ADAAD_AUTONOMY_CONTINUOUS_ENABLED"


@dataclass(frozen=True)
class StageTask:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CycleTelemetry:
    cycle_id: str
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    task_count: int = 0
    success_rate: float = 0.0
    mutation_count: int = 0
    failure_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "stage_timings_ms": {k: round(v, 3) for k, v in self.stage_timings_ms.items()},
            "task_count": self.task_count,
            "success_rate": round(self.success_rate, 4),
            "mutation_count": self.mutation_count,
            "failure_reasons": list(self.failure_reasons),
        }


class AutonomyLoop:
    """Coordinates governance adapters in explicit stage order."""

    def __init__(self, *, repo_root: Path, trigger_mode: str = "ADAAD", runbook_verbosity: str = "compact") -> None:
        self._repo_root = repo_root
        self._trigger_mode = trigger_mode
        self._runbook_verbosity = runbook_verbosity

    def run_cycle(self) -> CycleTelemetry:
        telemetry = CycleTelemetry(cycle_id=f"cycle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}")

        goals = self._timed("generate_goals", telemetry, self.generate_goals)
        tasks = self._timed("decompose_tasks", telemetry, self.decompose_tasks, goals)
        results = self._timed("dispatch_agents", telemetry, self.dispatch_agents, tasks)
        evaluation = self._timed("evaluate_results", telemetry, self.evaluate_results, results)
        self._timed("evolve_population", telemetry, self.evolve_population, evaluation)

        telemetry.task_count = len(tasks)
        succeeded = sum(1 for item in results if item.get("ok"))
        telemetry.success_rate = (succeeded / telemetry.task_count) if telemetry.task_count else 1.0
        telemetry.mutation_count = sum(int(item.get("mutation_count") or 0) for item in results)
        telemetry.failure_reasons = sorted({str(item.get("error")) for item in results if item.get("error")})
        return telemetry

    def generate_goals(self) -> list[str]:
        report = build_status_report(repo_root=self._repo_root, trigger_mode=self._trigger_mode)
        goals = ["bootstrap_registry", "compose_runbook", "collect_evidence"]
        if not report.dependency_readiness.ready:
            goals.insert(0, "emit_blocked_state")
        return goals

    def decompose_tasks(self, goals: list[str]) -> list[StageTask]:
        tasks: list[StageTask] = []
        for goal in goals:
            if goal == "bootstrap_registry":
                tasks.append(StageTask(name=goal, payload={}))
            elif goal == "compose_runbook":
                tasks.append(
                    StageTask(
                        name=goal,
                        payload={
                            "output_dir": (self._repo_root / "security" / "adaad_runbooks").as_posix(),
                            "verbosity_mode": self._runbook_verbosity,
                        },
                    )
                )
            elif goal == "collect_evidence":
                tasks.append(StageTask(name=goal, payload={"epoch_ids": []}))
            elif goal == "emit_blocked_state":
                tasks.append(
                    StageTask(
                        name=goal,
                        payload={
                            "status": "[ADAAD BLOCKED]",
                            "gate_id": "TIER0_SCHEMA_VALIDATION",
                            "failure_detail": "dependency_readiness_not_ready",
                        },
                    )
                )
        return tasks

    def dispatch_agents(self, tasks: list[StageTask]) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        for task in tasks:
            try:
                if task.name == "bootstrap_registry":
                    bootstrap_tool_registry()
                    outcomes.append({"task": task.name, "ok": True, "mutation_count": 0})
                elif task.name == "compose_runbook":
                    report = build_status_report(repo_root=self._repo_root, trigger_mode=self._trigger_mode)
                    runbook = compose_runbook(report=report, verbosity_mode=str(task.payload["verbosity_mode"]))
                    export_runbook_artifacts(runbook=runbook, output_dir=Path(str(task.payload["output_dir"])))
                    outcomes.append({"task": task.name, "ok": True, "mutation_count": 1})
                elif task.name == "collect_evidence":
                    create_default_evidence_orchestrator()
                    outcomes.append({"task": task.name, "ok": True, "mutation_count": 0})
                elif task.name == "emit_blocked_state":
                    message = format_blocked_state(
                        task.payload["status"],
                        task.payload["gate_id"],
                        task.payload["failure_detail"],
                    )
                    outcomes.append({"task": task.name, "ok": True, "mutation_count": 0, "message": message})
                else:
                    envelope = dispatch(task.name, task.payload)
                    outcomes.append({"task": task.name, "ok": envelope.get("status") != "error", "mutation_count": 0})
            except Exception as exc:  # pragma: no cover - fail-closed runtime path
                outcomes.append({"task": task.name, "ok": False, "mutation_count": 0, "error": str(exc)})
        return outcomes

    def evaluate_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        failures = [item for item in results if not item.get("ok")]
        return {
            "ok": not failures,
            "failure_count": len(failures),
            "failure_reasons": [str(item.get("error") or "unknown_error") for item in failures],
        }

    def evolve_population(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "stable" if evaluation.get("ok") else "degraded",
            "applied_mutations": 0 if evaluation.get("ok") else 1,
        }

    @staticmethod
    def _timed(stage_name: str, telemetry: CycleTelemetry, fn: Any, *args: Any) -> Any:
        started = perf_counter()
        result = fn(*args)
        telemetry.stage_timings_ms[stage_name] = (perf_counter() - started) * 1000.0
        return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ADAAD autonomy loop")
    parser.add_argument("--continuous", action="store_true", help="Run continuously (requires feature flag).")
    parser.add_argument("--max-cycles", type=int, default=1, help="Maximum cycles in continuous mode.")
    parser.add_argument("--trigger-mode", choices=("ADAAD", "DEVADAAD"), default="ADAAD")
    parser.add_argument("--runbook-verbosity", choices=("compact", "full_governance"), default="compact")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    loop = AutonomyLoop(repo_root=Path.cwd(), trigger_mode=args.trigger_mode, runbook_verbosity=args.runbook_verbosity)

    if args.continuous and os.getenv(_CONTINUOUS_FLAG, "0") != "1":
        raise RuntimeError(f"continuous_mode_disabled:set {_CONTINUOUS_FLAG}=1")

    cycles = args.max_cycles if args.continuous else 1
    for _ in range(max(1, cycles)):
        telemetry = loop.run_cycle()
        print(json.dumps({"event_type": "autonomy_cycle_telemetry", **telemetry.as_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
