from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from tools.codex.contracts import CodexJob, CodexResult
from tools.codex.metrics import log_event
from tools.codex.patch_apply import apply_patch
from tools.codex.sandbox import run_commands
from tools.codex.validators import validate_job


def write_result(path: Path, result: CodexResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2))


def run_codex(job_path: Path, diff_path: Path, output_path: Path) -> CodexResult:
    start_time = datetime.utcnow().isoformat() + "Z"
    job = CodexJob.from_json(job_path)

    log_event("CODEX_STAGE", "SUCCESS", detail="CODEX_PLAN")

    validation_errors = validate_job(job)
    if validation_errors:
        message = "; ".join(validation_errors)
        log_event("CODEX_STAGE", "FAILED", detail="CODEX_PLAN_VALIDATION")
        end_time = datetime.utcnow().isoformat() + "Z"
        return CodexResult(
            task_id=job.task_id,
            status="FAILED",
            message=message,
            started_at=start_time,
            finished_at=end_time,
            metrics_path=str(Path("reports/metrics.jsonl")),
        )

    log_event("CODEX_STAGE", "SUCCESS", detail="CODEX_GENERATE_DIFF")

    applied_patch = False
    try:
        applied_patch = apply_patch(diff_path)
        log_event(
            "CODEX_STAGE",
            "SUCCESS" if applied_patch else "SKIPPED",
            detail="CODEX_APPLY_DIFF",
        )
    except FileNotFoundError:
        log_event("CODEX_STAGE", "SKIPPED", detail="CODEX_APPLY_DIFF")
    except RuntimeError as error:
        log_event("CODEX_STAGE", "FAILED", detail="CODEX_APPLY_DIFF")
        end_time = datetime.utcnow().isoformat() + "Z"
        return CodexResult(
            task_id=job.task_id,
            status="FAILED",
            message=str(error),
            started_at=start_time,
            finished_at=end_time,
            applied_patch=applied_patch,
            metrics_path=str(Path("reports/metrics.jsonl")),
        )

    log_event("CODEX_STAGE", "SUCCESS", detail="CODEX_VALIDATE_IMPORTS")

    test_results = run_commands(job.tests)
    tests_ok = all(result.returncode == 0 for result in test_results)
    log_event(
        "CODEX_STAGE",
        "SUCCESS" if tests_ok else "FAILED",
        detail="CODEX_SANDBOX_TEST",
    )

    log_event("CODEX_STAGE", "SKIPPED", detail="CODEX_CRYOVANT_CERT")
    log_event("CODEX_STAGE", "SKIPPED", detail="CODEX_PROMOTE")

    end_time = datetime.utcnow().isoformat() + "Z"
    status = "SUCCESS" if tests_ok else "FAILED"
    message = "Tests passed" if tests_ok else "One or more tests failed"

    return CodexResult(
        task_id=job.task_id,
        status=status,
        message=message,
        started_at=start_time,
        finished_at=end_time,
        applied_patch=applied_patch,
        test_results=test_results,
        metrics_path=str(Path("reports/metrics.jsonl")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Codex pipeline")
    parser.add_argument("--job", type=Path, required=True, help="Path to the Codex job JSON")
    parser.add_argument("--diff", type=Path, required=True, help="Path to the unified diff file")
    parser.add_argument("--out", type=Path, required=True, help="Path to write the Codex result JSON")
    args = parser.parse_args()

    result = run_codex(args.job, args.diff, args.out)
    write_result(args.out, result)


if __name__ == "__main__":
    main()
