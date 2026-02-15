# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from runtime.evolution.simulation_runner import SimulationRunner, main


def _candidate() -> dict:
    return {
        "candidate_id": "m-1",
        "baseline": {"error_rate": 0.01, "latency_ms": 100.0, "success_rate": 0.99},
        "constraints": {
            "max_error_rate_delta": 0.01,
            "max_latency_delta_ms": 20.0,
            "min_success_rate_delta": -0.02,
        },
        "cohorts": [
            {"cohort_id": "cohort_a", "observed": {"error_rate": 0.015, "latency_ms": 110.0, "success_rate": 0.98}},
            {"cohort_id": "cohort_b", "observed": {"error_rate": 0.018, "latency_ms": 112.0, "success_rate": 0.981}},
            {"cohort_id": "cohort_c", "observed": {"error_rate": 0.016, "latency_ms": 118.0, "success_rate": 0.979}},
            {"cohort_id": "cohort_d", "observed": {"error_rate": 0.019, "latency_ms": 119.0, "success_rate": 0.978}},
        ],
    }


def test_simulation_runner_passes_deterministically() -> None:
    runner = SimulationRunner()
    verdict_one = runner.run(_candidate(), dry_run=True)
    verdict_two = runner.run(_candidate(), dry_run=True)
    assert verdict_one["passed"] is True
    assert verdict_one["status"] == "passed"
    assert verdict_one == verdict_two


def test_simulation_runner_fails_without_rollback() -> None:
    candidate = _candidate()
    candidate["canary_stages"] = [{"stage_id": "single", "cohort_ids": ["cohort_a"], "rollback_threshold": 2, "halt_on_fail": True}]
    candidate["cohorts"][0]["observed"]["latency_ms"] = 150.0

    verdict = SimulationRunner().run(candidate, dry_run=True)
    assert verdict["passed"] is False
    assert verdict["status"] == "failed"
    assert verdict["rollback_triggered"] is False


def test_simulation_runner_rolls_back_when_threshold_hit() -> None:
    candidate = _candidate()
    candidate["cohorts"][0]["observed"]["latency_ms"] = 150.0
    candidate["cohorts"][1]["observed"]["latency_ms"] = 151.0

    verdict = SimulationRunner().run(candidate, dry_run=True)
    assert verdict["passed"] is False
    assert verdict["status"] == "rollback"
    assert verdict["rollback_triggered"] is True


def test_simulation_runner_cli_entrypoint(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "verdict.json"
    candidate_path.write_text(json.dumps(_candidate()), encoding="utf-8")

    code = main(["--input", str(candidate_path), "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["candidate_id"] == "m-1"
    assert payload["dry_run"] is True
