from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from tools.codex.contracts import MetricEvent


def _metrics_path(path: Optional[Path] = None) -> Path:
    if path:
        return Path(path)
    return Path("reports/metrics.jsonl")


def log_event(event_type: str, status: str, detail: Optional[str] = None, *, path: Optional[Path] = None) -> MetricEvent:
    event = MetricEvent(
        event_type=event_type,
        status=status,
        detail=detail,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )
    metrics_file = _metrics_path(path)
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    with metrics_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict()))
        handle.write("\n")
    return event
