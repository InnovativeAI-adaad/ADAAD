"""Structured mutation metrics helpers.

This module standardizes metrics appended to ``reports/metrics.jsonl`` so
stages can be triaged with stable error codes.
"""
from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict

METRICS_PATH = Path("reports/metrics.jsonl")
METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)


class MutationStage(str, Enum):
    MUTATE_AST = "MUTATE_AST"
    BUILD_CHILD = "BUILD_CHILD"
    SANDBOX_RUN = "SANDBOX_RUN"
    FITNESS_EVAL = "FITNESS_EVAL"
    CRYOVANT_CERT = "CRYOVANT_CERT"
    PROMOTE = "PROMOTE"


class StageResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class ErrorCode(str, Enum):
    AST_SYNTAX_ERROR = "AST_SYNTAX_ERROR"
    AST_SEMANTIC_BREAK = "AST_SEMANTIC_BREAK"
    IMPORT_CANONICAL_VIOLATION = "IMPORT_CANONICAL_VIOLATION"
    SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
    SANDBOX_PERMISSION_DENIED = "SANDBOX_PERMISSION_DENIED"
    TEST_FAIL = "TEST_FAIL"
    FITNESS_BELOW_THRESHOLD = "FITNESS_BELOW_THRESHOLD"
    CRYOVANT_ANCESTRY_REJECTED = "CRYOVANT_ANCESTRY_REJECTED"
    CRYOVANT_SIGNING_FAILED = "CRYOVANT_SIGNING_FAILED"
    PROMOTION_WRITE_FAILED = "PROMOTION_WRITE_FAILED"


def _hash_message(message: str | None) -> str | None:
    if not message:
        return None
    return hashlib.sha256(message.encode("utf-8", errors="ignore")).hexdigest()


def record_stage_metric(
    *,
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
    stage: MutationStage,
    result: StageResult,
    duration_ms: int,
    error_code: ErrorCode | None = None,
    exception_type: str | None = None,
    exception_message: str | None = None,
    sandbox_exit_code: int | None = None,
    extra: Dict[str, Any] | None = None,
) -> None:
    """Append a structured metric line with failure taxonomy data."""

    payload: Dict[str, Any] = {
        "ts": time.time(),
        "cycle_id": cycle_id,
        "parent_agent_id": parent_agent_id,
        "child_candidate_id": child_candidate_id,
        "stage": stage.value,
        "result": result.value,
        "duration_ms": duration_ms,
        "error_code": error_code.value if error_code else None,
        "exception_type": exception_type,
        "exception_msg_hash": _hash_message(exception_message),
        "sandbox_exit_code": sandbox_exit_code,
    }
    if extra:
        payload.update(extra)

    with METRICS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def exception_fields(exc: BaseException | None) -> tuple[str | None, str | None]:
    if exc is None:
        return None, None
    return exc.__class__.__name__, str(exc)


__all__ = [
    "MutationStage",
    "StageResult",
    "ErrorCode",
    "record_stage_metric",
    "exception_fields",
    "METRICS_PATH",
]
