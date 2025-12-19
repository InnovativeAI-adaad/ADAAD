from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from runtime.interfaces.ilogger import ILogger

AUDIT_LEVEL = 25
logging.addLevelName(AUDIT_LEVEL, "AUDIT")

DEFAULT_LOG_DIR = Path("data/logs")
ROTATION_BYTES = 5_242_880
BACKUP_COUNT = 3

_LOGGER_CACHE: Dict[str, "JSONLogger"] = {}

REDACTION_KEYS = {"password", "secret", "token", "api_key", "credential", "key"}


def redact_context(data: Dict[str, Any], redactions: Optional[set[str]] = None) -> Dict[str, Any]:
    keys = redactions or REDACTION_KEYS
    return {k: ("<redacted>" if k in keys else v) for k, v in data.items()}


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class JSONFormatter(logging.Formatter):
    def __init__(self, component: str) -> None:
        super().__init__()
        self.component = component

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        context = getattr(record, "context", {}) or {}

        if record.exc_info:
            try:
                context = {**context, "exc": self.formatException(record.exc_info)}
            except Exception:
                context = {**context, "exc": "unavailable"}

        payload = {
            "ts": _iso_utc(record.created),
            "lvl": record.levelname,
            "cmp": self.component,
            "msg": record.getMessage(),
            "ctx": context,
        }
        return json.dumps(payload, ensure_ascii=False)


class JSONLogger(ILogger):
    def __init__(self, component: str = "runtime", log_file: Optional[Path] = None) -> None:
        self.component = component
        self.log_path = Path(log_file) if log_file else DEFAULT_LOG_DIR / f"{component}.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        logger_name = f"adaad.{component}"
        if log_file:
            logger_name = f"{logger_name}.{abs(hash(self.log_path))}"

        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        self._handler = self._ensure_handler(self.log_path)

    def _ensure_handler(self, log_path: Path) -> RotatingFileHandler:
        for handler in self._logger.handlers:
            if isinstance(handler, RotatingFileHandler) and Path(getattr(handler, "baseFilename", "")) == log_path:
                return handler

        handler = RotatingFileHandler(
            log_path,
            maxBytes=ROTATION_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(JSONFormatter(self.component))
        handler.adaad_json_handler = True  # type: ignore[attr-defined]
        self._logger.addHandler(handler)
        return handler

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(msg, extra={"context": redact_context(kwargs)})

    def error(self, msg: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        context = redact_context(dict(kwargs))
        exc_info = None
        if isinstance(error, BaseException):
            context["error"] = repr(error)
            exc_info = (error.__class__, error, error.__traceback__)
        self._logger.error(msg, extra={"context": context}, exc_info=exc_info)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(msg, extra={"context": kwargs})

    def audit(self, action: str, actor: str, outcome: str, **details: Any) -> None:
        context = {"action": action, "actor": actor, "outcome": outcome} | redact_context(details)
        self._logger.log(AUDIT_LEVEL, action, extra={"context": context})

    @property
    def handler(self) -> RotatingFileHandler:
        return self._handler


def get_logger(component: str = "runtime", log_file: Optional[Path] = None) -> JSONLogger:
    key = f"{component}:{Path(log_file).absolute()}" if log_file else component
    if key in _LOGGER_CACHE:
        return _LOGGER_CACHE[key]

    logger = JSONLogger(component=component, log_file=log_file)
    _LOGGER_CACHE[key] = logger
    return logger


__all__ = ["get_logger", "JSONLogger", "AUDIT_LEVEL", "ROTATION_BYTES", "BACKUP_COUNT", "redact_context"]
