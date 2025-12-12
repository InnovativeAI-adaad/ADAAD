from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

try:
    import fcntl  # not on Windows, ok on Linux/Termux
except Exception:
    fcntl = None


def _now_iso() -> str:
    # seconds precision is enough for jsonl
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    _ensure_dir(path)
    line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        if fcntl:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
        if fcntl:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def log_mutation_stage(
    *,
    metrics_path: str = "reports/metrics.jsonl",
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
    stage: str,
    result: str,
    error_code: Optional[str] = None,
    exception_type: Optional[str] = None,
    exception_msg_hash: Optional[str] = None,
    duration_ms: Optional[int] = None,
    sandbox_exit_code: Optional[int] = None,
    notes: Optional[Dict[str, Any]] = None,
) -> None:
    event = {
        "ts": _now_iso(),
        "event_type": "MUTATION_STAGE",
        "cycle_id": cycle_id,
        "parent_agent_id": parent_agent_id,
        "child_candidate_id": child_candidate_id,
        "stage": stage,
        "result": result,  # SUCCESS|FAIL
    }
    if error_code:
        event["error_code"] = error_code
    if exception_type:
        event["exception_type"] = exception_type
    if exception_msg_hash:
        event["exception_msg_hash"] = exception_msg_hash
    if duration_ms is not None:
        event["duration_ms"] = int(duration_ms)
    if sandbox_exit_code is not None:
        event["sandbox_exit_code"] = int(sandbox_exit_code)
    if notes:
        event["notes"] = notes

    _append_jsonl(metrics_path, event)


def log_mutation_cycle(
    *,
    metrics_path: str = "reports/metrics.jsonl",
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
    final_result: str,  # SUCCESS|FAIL
    dominant_stage: Optional[str] = None,
    dominant_error_code: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    event = {
        "ts": _now_iso(),
        "event_type": "MUTATION_CYCLE",
        "cycle_id": cycle_id,
        "parent_agent_id": parent_agent_id,
        "child_candidate_id": child_candidate_id,
        "final_result": final_result,
    }
    if dominant_stage:
        event["dominant_stage"] = dominant_stage
    if dominant_error_code:
        event["dominant_error_code"] = dominant_error_code
    if duration_ms is not None:
        event["duration_ms"] = int(duration_ms)

    _append_jsonl(metrics_path, event)
