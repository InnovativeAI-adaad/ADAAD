# SPDX-License-Identifier: Apache-2.0
"""Deterministic simulation runner for mutation/promotion canary checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from runtime.evolution.promotion_state_machine import canary_stage_definitions


@dataclass(frozen=True)
class _CanaryStage:
    stage_id: str
    cohort_ids: Sequence[str]
    rollback_threshold: int
    halt_on_fail: bool


class SimulationRunner:
    """Executes deterministic dry-run cohort simulations and emits verdicts."""

    def __init__(self, *, default_stages: Sequence[Mapping[str, Any]] | None = None) -> None:
        stage_defs = list(default_stages) if default_stages is not None else canary_stage_definitions()
        self._default_stages = tuple(self._normalize_stage(stage) for stage in stage_defs)

    @staticmethod
    def _normalize_stage(stage: Mapping[str, Any] | _CanaryStage) -> _CanaryStage:
        if isinstance(stage, _CanaryStage):
            return stage
        return _CanaryStage(
            stage_id=str(stage.get("stage_id") or "canary"),
            cohort_ids=tuple(str(cid) for cid in (stage.get("cohort_ids") or ())),
            rollback_threshold=max(1, int(stage.get("rollback_threshold") or 1)),
            halt_on_fail=bool(stage.get("halt_on_fail", True)),
        )

    @staticmethod
    def _cohort_result(*, cohort_id: str, baseline: Mapping[str, Any], observed: Mapping[str, Any], constraints: Mapping[str, Any]) -> Dict[str, Any]:
        baseline_error = float(baseline.get("error_rate", 0.0) or 0.0)
        baseline_latency = float(baseline.get("latency_ms", 0.0) or 0.0)
        baseline_success = float(baseline.get("success_rate", 0.0) or 0.0)

        observed_error = float(observed.get("error_rate", 0.0) or 0.0)
        observed_latency = float(observed.get("latency_ms", 0.0) or 0.0)
        observed_success = float(observed.get("success_rate", 0.0) or 0.0)

        error_delta = observed_error - baseline_error
        latency_delta = observed_latency - baseline_latency
        success_delta = observed_success - baseline_success

        max_error_delta = float(constraints.get("max_error_rate_delta", 0.0) or 0.0)
        max_latency_delta = float(constraints.get("max_latency_delta_ms", 0.0) or 0.0)
        min_success_delta = float(constraints.get("min_success_rate_delta", -1.0) or -1.0)

        checks = {
            "error_rate": error_delta <= max_error_delta,
            "latency_ms": latency_delta <= max_latency_delta,
            "success_rate": success_delta >= min_success_delta,
        }
        passed = all(checks.values())

        return {
            "cohort_id": cohort_id,
            "passed": passed,
            "checks": checks,
            "delta": {
                "error_rate": round(error_delta, 6),
                "latency_ms": round(latency_delta, 6),
                "success_rate": round(success_delta, 6),
            },
            "observed": {
                "error_rate": round(observed_error, 6),
                "latency_ms": round(observed_latency, 6),
                "success_rate": round(observed_success, 6),
            },
        }

    def run(self, candidate: Mapping[str, Any], *, dry_run: bool = True) -> Dict[str, Any]:
        candidate_id = str(candidate.get("candidate_id") or "candidate")
        baseline = dict(candidate.get("baseline") or {})
        constraints = dict(candidate.get("constraints") or {})
        cohorts = list(candidate.get("cohorts") or [])

        indexed_cohorts = {str(c.get("cohort_id") or ""): dict(c) for c in cohorts}
        stage_defs = tuple(self._normalize_stage(stage) for stage in (candidate.get("canary_stages") or self._default_stages))

        stages: List[Dict[str, Any]] = []
        status = "passed"
        halted = False
        rollback_triggered = False

        for stage in stage_defs:
            outcomes: List[Dict[str, Any]] = []
            for cohort_id in stage.cohort_ids:
                cohort = indexed_cohorts.get(cohort_id, {})
                observed = dict(cohort.get("observed") or {})
                outcomes.append(self._cohort_result(cohort_id=cohort_id, baseline=baseline, observed=observed, constraints=constraints))

            failures = sum(1 for outcome in outcomes if not outcome["passed"])
            stage_passed = failures == 0
            stage_rollback = failures >= stage.rollback_threshold
            stage_halted = bool(failures and stage.halt_on_fail)

            stage_result = {
                "stage_id": stage.stage_id,
                "passed": stage_passed,
                "failures": failures,
                "rollback_threshold": stage.rollback_threshold,
                "rollback_triggered": stage_rollback,
                "halted": stage_halted,
                "cohort_outcomes": outcomes,
            }
            stages.append(stage_result)

            if stage_rollback:
                rollback_triggered = True
                status = "rollback"
            elif not stage_passed and status == "passed":
                status = "failed"

            if stage_halted:
                halted = True
                break

        verdict = {
            "candidate_id": candidate_id,
            "dry_run": bool(dry_run),
            "status": status,
            "passed": status == "passed",
            "halted": halted,
            "rollback_triggered": rollback_triggered,
            "stage_results": stages,
        }
        canonical = json.dumps(verdict, ensure_ascii=False, sort_keys=True)
        verdict["verdict_digest"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return verdict


def _load_candidate(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic promotion simulation dry-run")
    parser.add_argument("--input", required=True, help="Path to candidate simulation JSON")
    parser.add_argument("--output", help="Optional path to write simulation verdict JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    verdict = SimulationRunner().run(_load_candidate(Path(args.input)), dry_run=True)
    serialized = json.dumps(verdict, ensure_ascii=False, sort_keys=True)

    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SimulationRunner", "main"]
