"""Canonical JSONL logger implementation for ADAAD.

The logger satisfies the ILogger contract and adheres to Protocol v1.0,
producing structured JSON lines with deterministic rotation.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional
import traceback
from datetime import datetime, timezone

from runtime.interfaces.ilogger import ILogger

AUDIT_LEVEL = logging.INFO + 5
logging.addLevelName(AUDIT_LEVEL, "AUDIT")


class JsonFormatter(logging.Formatter):
    """Formats log records into the canonical JSONL schema."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: WPS463
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        log_entry: Dict[str, Any] = {
            "ts": timestamp,
            "lvl": record.levelname,
            "cmp": record.name,
            "msg": record.getMessage(),
        }

        ctx: Dict[str, Any] = {}
        if hasattr(record, "ctx") and isinstance(record.ctx, dict):
            ctx.update(record.ctx)

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            ctx.update(
                {
                    "exc_type": exc_type.__name__ if exc_type else None,
                    "exc_msg": str(exc_value) if exc_value else None,
                    "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
                }
            )

        if ctx:
            log_entry["ctx"] = ctx

        return json.dumps(log_entry, ensure_ascii=False)


class CanonicalLogger(ILogger):
    """Concrete ILogger implementation with JSONL output and rotation."""

    def __init__(self, name: str = "ADAAD.Orchestrator", log_dir: Path | str = "data/logs") -> None:
        self.log_file = Path(log_dir) / f"{name.lower().replace('.', '_')}.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self._reset_handlers()

        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        self.logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        self.logger.addHandler(stream_handler)

    def _reset_handlers(self) -> None:
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        extra = {"ctx": kwargs} if kwargs else {}
        self.logger.log(level, msg, extra=extra)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, **kwargs)

    def error(self, msg: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        exc_info = None
        if error:
            exc_info = (error.__class__, error, error.__traceback__)
        self.logger.log(logging.ERROR, msg, extra={"ctx": kwargs} if kwargs else {}, exc_info=exc_info)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, **kwargs)

    def audit(self, action: str, actor: str, outcome: str, **details: Any) -> None:
        audit_ctx = {"action": action, "actor": actor, "outcome": outcome, **details}
        self._log(AUDIT_LEVEL, f"AUDIT: {action}", **audit_ctx)


_canonical_logger: Optional[CanonicalLogger] = None


def get_canonical_logger(name: str = "ADAAD.System", log_dir: Path | str = "data/logs") -> CanonicalLogger:
    global _canonical_logger
    if _canonical_logger is None:
        _canonical_logger = CanonicalLogger(name=name, log_dir=log_dir)
    return _canonical_logger


__all__ = [
    "CanonicalLogger",
    "JsonFormatter",
    "get_canonical_logger",
    "AUDIT_LEVEL",
]
