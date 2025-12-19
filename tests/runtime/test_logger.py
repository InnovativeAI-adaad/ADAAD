from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from runtime.interfaces.ilogger import ILogger
from runtime.logger import BACKUP_COUNT, ROTATION_BYTES, get_logger


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class LoggerTests(unittest.TestCase):
    def test_logger_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "logger.jsonl"
            logger = get_logger(component="testcmp", log_file=log_file)

            self.assertIsInstance(logger, ILogger)
            logger.info("hello", foo="bar")

            entries = read_jsonl(log_file)
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["lvl"], "INFO")
            self.assertEqual(entry["cmp"], "testcmp")
            self.assertEqual(entry["msg"], "hello")
            self.assertEqual(entry["ctx"]["foo"], "bar")
            datetime.fromisoformat(entry["ts"])  # raises if not ISO-8601

    def test_audit_logs_include_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "audit.jsonl"
            logger = get_logger(component="auditcmp", log_file=log_file)

            logger.audit("boot", actor="system", outcome="ok", detail="ready")

            entry = read_jsonl(log_file)[0]
            self.assertEqual(entry["lvl"], "AUDIT")
            ctx = entry["ctx"]
            self.assertEqual(ctx["action"], "boot")
            self.assertEqual(ctx["actor"], "system")
            self.assertEqual(ctx["outcome"], "ok")
            self.assertEqual(ctx["detail"], "ready")

    def test_rotation_config_and_no_duplicate_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "rotate.jsonl"
            logger = get_logger(component="rotator", log_file=log_file)

            handler = logger.handler
            self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
            self.assertEqual(handler.maxBytes, ROTATION_BYTES)
            self.assertEqual(handler.backupCount, BACKUP_COUNT)

            logger.info("first")
            logger_again = get_logger(component="rotator", log_file=log_file)
            logger_again.info("second")

            entries = read_jsonl(log_file)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["msg"], "first")
            self.assertEqual(entries[1]["msg"], "second")


if __name__ == "__main__":
    unittest.main()
