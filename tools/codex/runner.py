# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

from tools.codex import metrics
from tools.codex.contracts import CodexErrorCode, CodexJob, CodexResult, CodexStageMetric, load_job
from tools.codex.patch_apply import apply_unified_diff_to_repo, clone_repo_subset, promote_changes
from tools.codex.sandbox import py_compile_files, run_cmd
from tools.codex.validators import normalize_rel_path, scan_python_files_for_import_violations, validate_paths

ROOT = Path(__file__).resolve().parents[2]
SCRATCH_ROOT = ROOT / "runtime" / "tmp" / "codex"
DEFAULT_METRICS = ROOT / "reports" / "metrics.jsonl"

STAGES = [
    "CODEX_PLAN",
    "CODEX_GENERATE_DIFF",
    "CODEX_APPLY_DIFF",
    "CODEX_VALIDATE_IMPORTS",
    "CODEX_SANDBOX_TEST",
    "CODEX_CRYOVANT_CERT",
    "CODEX_PROMOTE",
]


def _metric(stage: str, result: str, duration_ms: int = 0, error_code: str | None = None, notes: dict | None = None) -> CodexStageMetric:
    return CodexStageMetric(stage=stage, result=result, duration_ms=duration_ms, error_code=error_code, notes=notes or {})


def run_pipeline(job: CodexJob, *, metrics_path: Path = DEFAULT_METRICS) -> CodexResult:
    metrics_out: List[CodexStageMetric] = []
    files_touched: List[str] = []
    status = "FAIL"
    error_code: str | None = None
    notes = ""

    def record(stage: str, result: str, duration_ms: int = 0, err: str | None = None, note: dict | None = None) -> None:
        metrics_out.append(_metric(stage, result, duration_ms, err, note))
        metrics.log_codex_stage(
            metrics_path=str(metrics_path),
            cycle_id=job.cycle_id,
            parent_agent_id=job.parent_agent_id,
            child_candidate_id=job.child_candidate_id,
            stage=stage,
            result=result,
            duration_ms=duration_ms,
            error_code=err,
            notes=note,
        )

    # CODEX_PLAN
    start = time.time()
    validation_err = job.validate()
    duration_ms = int((time.time() - start) * 1000)
    if validation_err:
        error_code = CodexErrorCode.INVALID_JOB
        notes = validation_err
        record("CODEX_PLAN", "FAIL", duration_ms, error_code, {"reason": validation_err})
        return CodexResult(
            task_id=job.task_id,
            status=status,
            diff=job.diff,
            files_touched=files_touched,
            metrics=metrics_out,
            error_code=error_code,
            notes=notes,
        )
    record("CODEX_PLAN", "SUCCESS", duration_ms)

    # CODEX_GENERATE_DIFF (here we expect diff provided)
    start = time.time()
    if not job.diff:
        error_code = CodexErrorCode.NO_DIFF
        notes = "diff is required"
        duration_ms = int((time.time() - start) * 1000)
        record("CODEX_GENERATE_DIFF", "FAIL", duration_ms, error_code, {"reason": notes})
        return CodexResult(
            task_id=job.task_id,
            status=status,
            diff=job.diff,
            files_touched=files_touched,
            metrics=metrics_out,
            error_code=error_code,
            notes=notes,
        )
    duration_ms = int((time.time() - start) * 1000)
    record("CODEX_GENERATE_DIFF", "SUCCESS", duration_ms)

    scratch_repo = SCRATCH_ROOT / job.task_id / "repo"
    clone_repo_subset(src_root=ROOT, dst_root=scratch_repo)

    # CODEX_APPLY_DIFF
    start = time.time()
    try:
        files_touched = apply_unified_diff_to_repo(repo_root=scratch_repo, diff_text=job.diff)
    except Exception as exc:  # noqa: BLE001
        error_code = CodexErrorCode.PATCH_APPLY_FAILED
        notes = str(exc)
        duration_ms = int((time.time() - start) * 1000)
        record("CODEX_APPLY_DIFF", "FAIL", duration_ms, error_code, {"exception": notes})
        return CodexResult(
            task_id=job.task_id,
            status=status,
            diff=job.diff,
            files_touched=files_touched,
            metrics=metrics_out,
            error_code=error_code,
            notes=notes,
        )
    duration_ms = int((time.time() - start) * 1000)
    record("CODEX_APPLY_DIFF", "SUCCESS", duration_ms, notes={"files": files_touched})

    # CODEX_VALIDATE_IMPORTS
    start = time.time()
    path_issues = validate_paths(files_touched, job.allowed_paths, job.forbidden_paths)
    import_issues = scan_python_files_for_import_violations(scratch_repo, files_touched)
    duration_ms = int((time.time() - start) * 1000)
    if path_issues or import_issues:
        error_code = CodexErrorCode.PATH_VIOLATION if path_issues else CodexErrorCode.IMPORT_VALIDATION_FAILED
        notes = "; ".join([f"{i.path}: {i.reason}" for i in (path_issues + import_issues)])
        record("CODEX_VALIDATE_IMPORTS", "FAIL", duration_ms, error_code, {"issues": notes})
        return CodexResult(
            task_id=job.task_id,
            status=status,
            diff=job.diff,
            files_touched=files_touched,
            metrics=metrics_out,
            error_code=error_code,
            notes=notes,
        )
    record("CODEX_VALIDATE_IMPORTS", "SUCCESS", duration_ms)

    # CODEX_SANDBOX_TEST
    start = time.time()
    compile_result = py_compile_files(scratch_repo, files_touched)
    duration_ms = int((time.time() - start) * 1000)
    if not compile_result.ok:
        error_code = CodexErrorCode.SANDBOX_TEST_FAILED
        notes = compile_result.stderr_tail or compile_result.stdout_tail
        record(
            "CODEX_SANDBOX_TEST",
            "FAIL",
            duration_ms,
            error_code,
            {"returncode": compile_result.returncode, "stderr": compile_result.stderr_tail, "stdout": compile_result.stdout_tail},
        )
        return CodexResult(
            task_id=job.task_id,
            status=status,
            diff=job.diff,
            files_touched=files_touched,
            metrics=metrics_out,
            error_code=error_code,
            notes=notes,
        )

    test_results = []
    for t in job.tests:
        cmd = t.split() if isinstance(t, str) else list(t)
        res = run_cmd(cmd=cmd, cwd=scratch_repo)
        test_results.append({"cmd": cmd, "ok": res.ok, "returncode": res.returncode, "stdout": res.stdout_tail, "stderr": res.stderr_tail})
        if not res.ok:
            error_code = CodexErrorCode.SANDBOX_TEST_FAILED
            notes = f"command failed: {' '.join(cmd)}"
            duration_ms = int((time.time() - start) * 1000)
            record(
                "CODEX_SANDBOX_TEST",
                "FAIL",
                duration_ms,
                error_code,
                {"returncode": res.returncode, "stderr": res.stderr_tail, "stdout": res.stdout_tail, "cmd": cmd},
            )
            return CodexResult(
                task_id=job.task_id,
                status=status,
                diff=job.diff,
                files_touched=files_touched,
                metrics=metrics_out,
                error_code=error_code,
                notes=notes,
            )
    duration_ms = int((time.time() - start) * 1000)
    record("CODEX_SANDBOX_TEST", "SUCCESS", duration_ms, notes={"tests": test_results})

    # CODEX_CRYOVANT_CERT placeholder
    record("CODEX_CRYOVANT_CERT", "SKIPPED", 0, None, {"reason": "orchestrator-owned"})

    # CODEX_PROMOTE
    start = time.time()
    promote_changes(scratch_root=scratch_repo, repo_root=ROOT, touched=files_touched)
    duration_ms = int((time.time() - start) * 1000)
    record("CODEX_PROMOTE", "SUCCESS", duration_ms)

    status = "SUCCESS"
    return CodexResult(
        task_id=job.task_id,
        status=status,
        diff=job.diff,
        files_touched=[normalize_rel_path(f) for f in files_touched],
        metrics=metrics_out,
        error_code=error_code,
        notes=notes,
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex pipeline runner")
    parser.add_argument("--job", required=True, type=Path, help="Path to CodexJob JSON file")
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS, help="metrics.jsonl path")
    args = parser.parse_args(argv)

    job = load_job(args.job)
    result = run_pipeline(job, metrics_path=args.metrics)
    sys.stdout.write(result.to_json() + "\n")
    return 0 if result.status == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
