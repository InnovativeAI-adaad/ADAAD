import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.interfaces.ilogger import ILogger
from runtime.logger import CanonicalLogger, JsonFormatter, get_canonical_logger


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_implements_interface(tmp_path: Path) -> None:
    logger = CanonicalLogger(name="test.logger", log_dir=tmp_path)
    assert isinstance(logger, ILogger)


def test_writes_valid_jsonl(tmp_path: Path) -> None:
    logger = CanonicalLogger(name="test.logger", log_dir=tmp_path)
    logger.info("Bootstrap test", session_id="A1B2C3", mode="runloop")

    logs = read_jsonl(logger.log_file)
    assert len(logs) == 1
    log = logs[0]
    assert log["lvl"] == "INFO"
    assert log["cmp"] == "test.logger"
    assert log["msg"] == "Bootstrap test"
    assert log["ctx"]["session_id"] == "A1B2C3"


def test_error_logging_includes_traceback(tmp_path: Path) -> None:
    logger = CanonicalLogger(name="test.error", log_dir=tmp_path)
    try:
        raise ValueError("Invalid state transition")
    except ValueError as exc:  # pragma: no cover - exercised in test
        logger.error("State failure", error=exc, component="orchestrator")

    logs = read_jsonl(logger.log_file)
    log = logs[0]
    assert log["lvl"] == "ERROR"
    assert log["ctx"]["component"] == "orchestrator"
    assert log["ctx"]["exc_type"] == "ValueError"
    assert any("Invalid state transition" in line for line in log["ctx"]["traceback"])


def test_audit_logging(tmp_path: Path) -> None:
    logger = CanonicalLogger(name="test.audit", log_dir=tmp_path)
    logger.audit("AGENT_PROMOTION", "Cryovant", "SUCCESS", agent_id="he65:101a")

    log = read_jsonl(logger.log_file)[0]
    assert log["lvl"] == "AUDIT"
    assert log["msg"] == "AUDIT: AGENT_PROMOTION"
    assert log["ctx"]["actor"] == "Cryovant"
    assert log["ctx"]["agent_id"] == "he65:101a"


def test_rotation_configured(tmp_path: Path) -> None:
    logger = CanonicalLogger(name="test.rotation", log_dir=tmp_path)
    handler = next(h for h in logger.logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3


def test_json_formatter_includes_timestamp(tmp_path: Path) -> None:
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
    assert output["ts"].startswith("1970-01-01T00:00:01")


def test_get_canonical_logger_reuses_instance(tmp_path: Path) -> None:
    first = get_canonical_logger(name="test.singleton", log_dir=tmp_path)
    second = get_canonical_logger(name="another", log_dir=tmp_path)
    assert first is second
    assert first.log_file.exists()
    assert second.log_file == first.log_file
    assert any(handler.level == logging.INFO for handler in first.logger.handlers if isinstance(handler, logging.StreamHandler))
