# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Runtime event logging helpers for ADAAD."""
import json
import pathlib
import time
from typing import Any, Dict

LOG_DIR = pathlib.Path("runtime/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def event(name: str, **data: Any) -> None:
    record: Dict[str, Any] = {"ts": time.time(), "event": name} | data
    (LOG_DIR / "events.jsonl").open("a", encoding="utf-8").write(json.dumps(record) + "\n")


__all__ = ["event", "LOG_DIR"]
