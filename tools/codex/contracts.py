from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CodexJob:
    task_id: str
    objective: str
    allowed_paths: List[str]
    forbidden_paths: List[str]
    patch_format: str
    tests: List[str]
    success_criteria: List[str]
    cycle_id: str
    parent_agent_id: str
    child_candidate_id: str
    diff: str = ""

    @classmethod
    def from_json(cls, path: Path) -> "CodexJob":
        payload = json.loads(Path(path).read_text())
        return cls(
            task_id=payload.get("task_id", "unknown-task"),
            objective=payload.get("objective", ""),
            allowed_paths=list(payload.get("allowed_paths", [])),
            forbidden_paths=list(payload.get("forbidden_paths", [])),
            patch_format=payload.get("patch_format", "unified_diff"),
            tests=list(payload.get("tests", [])),
            success_criteria=list(payload.get("success_criteria", [])),
            cycle_id=payload.get("cycle_id", ""),
            parent_agent_id=payload.get("parent_agent_id", ""),
            child_candidate_id=payload.get("child_candidate_id", ""),
            diff=payload.get("diff", ""),
        )


@dataclass
class TestResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass
class CodexResult:
    task_id: str
    status: str
    message: str
    started_at: str
    finished_at: str
    applied_patch: bool = False
    test_results: List[TestResult] = field(default_factory=list)
    metrics_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "applied_patch": self.applied_patch,
            "test_results": [result.to_dict() for result in self.test_results],
            "metrics_path": self.metrics_path,
        }


@dataclass
class MetricEvent:
    event_type: str
    status: str
    detail: Optional[str] = None
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "status": self.status,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }
