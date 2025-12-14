from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(".").resolve()

REQUIRED_ROOT_MARKERS: List[str] = [
    "app",
    "runtime",
    "security",
    "data",
    "docs",
    "tests",
    "reports",
]

CANONICAL_FOLDERS: List[str] = [
    "docs/protocols/v1",
    "runtime/interfaces",
    "runtime/tools",
    "tests/runtime",
    "app/agents/incubator",
    "app/agents/candidates",
    "app/agents/active",
    "app/agents/quarantine",
    "data/work/00_inbox",
    "data/work/01_active",
    "data/work/02_review",
    "data/work/03_done",
    "data/logs",
]

LOGGER_INTERFACE_CODE = textwrap.dedent(
    '''
    from abc import ABC, abstractmethod
    from typing import Any, Optional

    class ILogger(ABC):
        """He65 canonical logger contract. All logging must pass through this interface."""

        @abstractmethod
        def info(self, msg: str, **kwargs: Any) -> None:
            raise NotImplementedError

        @abstractmethod
        def error(self, msg: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
            raise NotImplementedError

        @abstractmethod
        def debug(self, msg: str, **kwargs: Any) -> None:
            raise NotImplementedError

        @abstractmethod
        def audit(self, action: str, actor: str, outcome: str, **details: Any) -> None:
            """High-value security/transaction logging."""
            raise NotImplementedError
    '''
).lstrip()

LOGGING_PROTOCOL_MD = textwrap.dedent(
    '''
    # Protocol v1.0: Structured Logging Standard

    ## Mandate (Stability-First)
    1. No direct use of `print()` in `runtime/` or `app/`.
    2. All logs must be structured JSON lines (JSONL).
    3. Rotation occurs at 5MB.
    4. Callers must redact secrets before logging.

    ## Canonical Schema
    ```json
    {
      "ts": "ISO-8601 Timestamp",
      "lvl": "INFO|ERROR|DEBUG|AUDIT",
      "cmp": "Component Name",
      "msg": "Human readable message",
      "ctx": { "any": "extra fields" }
    }
    ```

    '''
).lstrip()

TICKET_001: Dict[str, Any] = {
    "id": "TICKET-001",
    "type": "feature",
    "priority": "critical",
    "title": "Implement Canonical ILogger (runtime/logger.py)",
    "description": "Create a concrete implementation of ILogger that adheres to Protocol v1.0 for unified system observability.",
    "inputs": [
        "runtime/interfaces/ilogger.py",
        "docs/protocols/v1/logging_standard.md",
    ],
    "deliverables": [
        "runtime/logger.py",
        "tests/runtime/test_logger.py",
    ],
    "acceptance_criteria": [
        "runtime/logger.py exists",
        "Implements ILogger",
        "Writes valid JSONL",
        "Rotates at 5MB (5242880 bytes), backupCount=3",
        "tests/runtime/test_logger.py passes with python -m unittest",
    ],
    "agent_handoff": "Implementer",
}


def _assert_root() -> None:
    missing = [p for p in REQUIRED_ROOT_MARKERS if not (ROOT / p).exists()]
    if missing:
        raise SystemExit(f"ERROR: Not at He65 repo root. Missing: {missing}")


def _mkdirs() -> None:
    for folder in CANONICAL_FOLDERS:
        path = ROOT / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / ".keep").touch(exist_ok=True)


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def bootstrap_he65_nexus() -> None:
    _assert_root()
    _mkdirs()

    wrote_iface = _write_if_missing(ROOT / "runtime/interfaces/ilogger.py", LOGGER_INTERFACE_CODE)
    wrote_proto = _write_if_missing(ROOT / "docs/protocols/v1/logging_standard.md", LOGGING_PROTOCOL_MD)

    ticket_path = ROOT / "data/work/00_inbox/TICKET-001_implement_logger.json"
    wrote_ticket = False
    if not ticket_path.exists():
        ticket_path.write_text(json.dumps(TICKET_001, indent=2), encoding="utf-8")
        wrote_ticket = True

    print("He65 Nexus bootstrap complete.")
    print(f"Interface created: {wrote_iface}")
    print(f"Protocol created: {wrote_proto}")
    print(f"Ticket created: {wrote_ticket}")


if __name__ == "__main__":
    bootstrap_he65_nexus()
