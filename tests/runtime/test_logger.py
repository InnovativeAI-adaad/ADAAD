import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.interfaces.ilogger import ILogger
from runtime.logger import CanonicalLogger, JsonFormatter, get_canonical_logger, get_logger


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class LoggerTests(unittest.TestCase):
    def test_implements_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = CanonicalLogger(name="test.logger", log_dir=tmp)
            self.assertIsInstance(logger, ILogger)

    def test_writes_valid_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = CanonicalLogger(name="test.logger", log_dir=tmp)
            logger.info("Bootstrap test", session_id="A1B2C3", mode="runloop")

            logs = read_jsonl(logger.log_file)
            self.assertEqual(len(logs), 1)
            log = logs[0]
            self.assertEqual(log["lvl"], "INFO")
            self.assertEqual(log["cmp"], "test.logger")
            self.assertEqual(log["msg"], "Bootstrap test")
            self.assertEqual(log["ctx"]["session_id"], "A1B2C3")

    def test_error_logging_includes_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = CanonicalLogger(name="test.error", log_dir=tmp)
            try:
                raise ValueError("Invalid state transition")
            except ValueError as exc:  # pragma: no cover - exercised in test
                logger.error("State failure", error=exc, component="orchestrator")

            logs = read_jsonl(logger.log_file)
            log = logs[0]
            self.assertEqual(log["lvl"], "ERROR")
            self.assertEqual(log["ctx"]["component"], "orchestrator")
            self.assertEqual(log["ctx"]["exc_type"], "ValueError")
            self.assertTrue(any("Invalid state transition" in line for line in log["ctx"]["traceback"]))

    def test_audit_logging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = CanonicalLogger(name="test.audit", log_dir=tmp)
            logger.audit("AGENT_PROMOTION", "Cryovant", "SUCCESS", agent_id="he65:101a")

            log = read_jsonl(logger.log_file)[0]
            self.assertEqual(log["lvl"], "AUDIT")
            self.assertEqual(log["msg"], "AUDIT: AGENT_PROMOTION")
            self.assertEqual(log["ctx"]["actor"], "Cryovant")
            self.assertEqual(log["ctx"]["agent_id"], "he65:101a")

    def test_rotation_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logger = CanonicalLogger(name="test.rotation", log_dir=tmp)
            handler = next(h for h in logger.logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
            self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
            self.assertEqual(handler.backupCount, 3)

    def test_json_formatter_includes_timestamp(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="component",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="message",
            args=(),
            exc_info=None,
            func=None,
            sinfo=None,
        )
        record.created = 1.0
        output = json.loads(formatter.format(record))
        self.assertTrue(output["ts"].startswith("1970-01-01T00:00:01"))

    def test_get_canonical_logger_cache_by_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = get_canonical_logger(name="ADAAD.test", log_dir=tmp)
            second = get_canonical_logger(name="ADAAD.test", log_dir=tmp)
            third = get_logger(component="another", log_dir=tmp)
            self.assertIs(first, second)
            self.assertIsNot(first, third)
            self.assertTrue(first.log_file.exists())
            self.assertTrue(third.log_file.exists())


if __name__ == "__main__":
    unittest.main()
