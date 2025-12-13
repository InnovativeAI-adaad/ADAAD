from __future__ import annotations

from pathlib import Path
from typing import List

from tools.codex.contracts import CodexJob


def validate_job(job: CodexJob) -> List[str]:
    errors: List[str] = []
    if job.patch_format not in {"unified_diff", "git"}:
        errors.append(f"Unsupported patch format: {job.patch_format}")
    if not job.allowed_paths:
        errors.append("allowed_paths must not be empty")
    for path in job.forbidden_paths:
        if not path.endswith("/"):
            errors.append(f"forbidden path should end with '/': {path}")
    if not job.tests:
        errors.append("tests list must not be empty")
    if job.diff and not Path(job.diff).exists():
        errors.append(f"Diff file referenced in job is missing: {job.diff}")
    return errors
