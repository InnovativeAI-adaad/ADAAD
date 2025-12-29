from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

DEFAULT_APONI_URL = os.environ.get("APONI_API_URL", "http://localhost:5000/api/v1/events")
ERROR_LOG = Path("logs/aponi_sync_errors.log")


def push_to_dashboard(event_type: str, data: Dict[str, object]) -> bool:
    payload = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, "payload": data}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        DEFAULT_APONI_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception as exc:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": payload["ts"], "type": event_type, "error": str(exc), "payload": data}
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return False


__all__ = ["push_to_dashboard"]
