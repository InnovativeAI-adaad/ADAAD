# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

try:
    import fcntl  # Linux/Termux
except Exception:
    fcntl = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
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


def log_codex_stage(
    *,
    metrics_path: str,
    cycle_id: str,
    parent_agent_id: str,
    child_candidate_id: str,
    stage: str,
    result: str,  # SUCCESS|FAIL|SKIPPED
    duration_ms: int = 0,
    error_code: Optional[str] = None,
    notes: Optional[Dict[str, Any]] = None,
) -> None:
    evt: Dict[str, Any] = {
        "ts": _now_iso(),
        "event_type": "CODEX_STAGE",
        "cycle_id": cycle_id,
        "parent_agent_id": parent_agent_id,
        "child_candidate_id": child_candidate_id,
        "stage": stage,
        "result": result,
        "duration_ms": int(duration_ms),
    }
    if error_code:
        evt["error_code"] = error_code
    if notes:
        evt["notes"] = notes
    append_jsonl(metrics_path, evt)
