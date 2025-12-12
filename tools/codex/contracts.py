# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class CodexErrorCode:
    INVALID_JOB = "CODEX_INVALID_JOB"
    NO_DIFF = "CODEX_NO_DIFF"
    DIFF_PARSE_FAILED = "CODEX_DIFF_PARSE_FAILED"
    PATH_VIOLATION = "CODEX_PATH_VIOLATION"
    PATCH_APPLY_FAILED = "CODEX_PATCH_APPLY_FAILED"
    IMPORT_VALIDATION_FAILED = "CODEX_IMPORT_VALIDATION_FAILED"
    SANDBOX_TEST_FAILED = "CODEX_SANDBOX_TEST_FAILED"
    INTERNAL_ERROR = "CODEX_INTERNAL_ERROR"


@dataclass
class CodexJob:
    task_id: str
    objective: str
    allowed_paths: List[str]
    forbidden_paths: List[str]
    patch_format: str = "unified_diff"
    tests: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    cycle_id: str = ""
    parent_agent_id: str = ""
    child_candidate_id: str = ""
    diff: str = ""

    @staticmethod
    def from_json(obj: Dict[str, Any]) -> "CodexJob":
        return CodexJob(
            task_id=str(obj.get("task_id", "")).strip(),
            objective=str(obj.get("objective", "")).strip(),
            allowed_paths=list(obj.get("allowed_paths", []) or []),
            forbidden_paths=list(obj.get("forbidden_paths", []) or []),
            patch_format=str(obj.get("patch_format", "unified_diff")).strip(),
            tests=list(obj.get("tests", []) or []),
            success_criteria=list(obj.get("success_criteria", []) or []),
            cycle_id=str(obj.get("cycle_id", "")).strip(),
            parent_agent_id=str(obj.get("parent_agent_id", "")).strip(),
            child_candidate_id=str(obj.get("child_candidate_id", "")).strip(),
            diff=str(obj.get("diff", "") or ""),
        )

    def validate(self) -> Optional[str]:
        if not self.task_id:
            return "missing task_id"
        if not self.objective:
            return "missing objective"
        if self.patch_format != "unified_diff":
            return "patch_format must be unified_diff"
        if not isinstance(self.allowed_paths, list) or not self.allowed_paths:
            return "allowed_paths must be a non-empty list"
        if not isinstance(self.forbidden_paths, list):
            return "forbidden_paths must be a list"
        if not self.cycle_id:
            return "missing cycle_id"
        if not self.parent_agent_id:
            return "missing parent_agent_id"
        if not self.child_candidate_id:
            return "missing child_candidate_id"
        return None


@dataclass
class CodexStageMetric:
    stage: str
    result: str  # SUCCESS|FAIL|SKIPPED
    duration_ms: int = 0
    error_code: Optional[str] = None
    notes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodexResult:
    task_id: str
    status: str  # SUCCESS|FAIL
    diff: str
    files_touched: List[str] = field(default_factory=list)
    metrics: List[CodexStageMetric] = field(default_factory=list)
    error_code: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "diff": self.diff,
            "files_touched": self.files_touched,
            "metrics": [
                {
                    "stage": m.stage,
                    "result": m.result,
                    "duration_ms": m.duration_ms,
                    "error_code": m.error_code,
                    "notes": m.notes,
                }
                for m in self.metrics
            ],
            "error_code": self.error_code,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def load_job(path: Path) -> CodexJob:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    obj = json.loads(raw)
    return CodexJob.from_json(obj)
