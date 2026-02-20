"""Bootstrap script for initializing the He65 Nexus workspace.

This script materializes the canonical folder structure, seeds protocol
references, and drops the first ticket into the work queue. It is
idempotent: rerunning it will not overwrite existing artifacts.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

from runtime.governance.schema_validator import validate_governance_schemas

ROOT = Path(".").resolve()
CANONICAL_FOLDERS: List[str] = [
    "docs/protocols/v1",
    "runtime/interfaces",
    "app/agents/incubator",
    "app/agents/candidates",
    "app/agents/active",
    "app/agents/quarantine",
    "data/work/00_inbox",
    "data/work/01_active",
    "data/work/02_review",
    "data/work/03_done",
    "runtime/tools",
    "data/logs",
    "tests/runtime",
]
REQUIRED_ROOT_MARKERS: List[str] = [
    "app",
    "runtime",
    "security",
    "data",
    "docs",
    "tests",
    "reports",
]

LOGGER_INTERFACE_CODE = """
from abc import ABC, abstractmethod
from typing import Any, Optional

class ILogger(ABC):
# He65 canonical logger contract. All logging must pass through this interface.

# @abstractmethod
# def info(self, msg: str, **kwargs: Any) -> None:
# raise NotImplementedError

# @abstractmethod
# def error(self, msg: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
# raise NotImplementedError

# @abstractmethod
# def debug(self, msg: str, **kwargs: Any) -> None:
# raise NotImplementedError

# @abstractmethod
# def audit(self, action: str, actor: str, outcome: str, **details: Any) -> None:
        raise NotImplementedError
""".lstrip()

LOGGING_PROTOCOL_MD = """
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

""".lstrip()

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
    missing = [marker for marker in REQUIRED_ROOT_MARKERS if not (ROOT / marker).exists()]
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
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)
    return True


def _load_json_file(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    except OSError as exc:
        print(f"WARNING: Could not read {path}: {exc}")
        return None


def _validate_python_version() -> Dict[str, str]:
    supported = sys.version_info >= (3, 10)
    return {
        "name": "python_version",
        "status": "pass" if supported else "fail",
        "detail": f"Detected {sys.version.split()[0]}; requires >=3.10",
    }


def _validate_required_imports() -> Dict[str, str]:
    required_modules = ["json", "sqlite3", "runtime.governance.schema_validator"]
    missing: List[str] = []
    for module in required_modules:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)
    status = "pass" if not missing else "fail"
    detail = "All required imports available" if status == "pass" else f"Missing imports: {', '.join(missing)}"
    return {"name": "required_packages_importability", "status": status, "detail": detail}


def _validate_directory_structure() -> Dict[str, str]:
    missing = [marker for marker in REQUIRED_ROOT_MARKERS if not (ROOT / marker).exists()]
    status = "pass" if not missing else "fail"
    detail = "All required root markers present" if status == "pass" else f"Missing root markers: {missing}"
    return {"name": "directory_structure", "status": status, "detail": detail}


def _validate_governance_schema() -> Dict[str, str]:
    schema_path = ROOT / "schemas" / "governance_policy_payload.v1.json"
    if not schema_path.exists():
        return {
            "name": "governance_policy_schema_validity",
            "status": "pass",
            "detail": "Schema files not yet present (first run) — skipped",
        }

    errors = validate_governance_schemas()
    if not errors:
        return {
            "name": "governance_policy_schema_validity",
            "status": "pass",
            "detail": "Governance schemas valid",
        }

    first_key = sorted(errors)[0]
    first_error = errors[first_key][0]
    return {
        "name": "governance_policy_schema_validity",
        "status": "fail",
        "detail": f"{len(errors)} schema file(s) invalid; first error: {first_key} -> {first_error}",
    }


def _validate_sqlite() -> Dict[str, str]:
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("SELECT 1")
        connection.close()
        return {"name": "sqlite_availability", "status": "pass", "detail": "sqlite3 usable"}
    except Exception as exc:
        return {"name": "sqlite_availability", "status": "fail", "detail": f"sqlite3 unavailable: {exc}"}


def _validate_port_availability(port: int = 8000) -> Dict[str, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
        return {"name": "port_availability", "status": "pass", "detail": f"Port {port} is available"}
    except OSError as exc:
        return {"name": "port_availability", "status": "fail", "detail": f"Port {port} unavailable: {exc}"}
    finally:
        sock.close()


def _run_validation() -> Dict[str, Any]:
    required_checks = [
        _validate_python_version(),
        _validate_required_imports(),
        _validate_directory_structure(),
        _validate_governance_schema(),
        _validate_sqlite(),
    ]
    optional_checks = [_validate_port_availability()]
    required_failed = sum(1 for check in required_checks if check["status"] != "pass")
    optional_failed = sum(1 for check in optional_checks if check["status"] != "pass")
    overall = "pass" if required_failed == 0 else "fail"
    return {
        "checks": required_checks + optional_checks,
        "overall": overall,
        "required_failed": required_failed,
        "optional_failed": optional_failed,
    }


def _print_text_report(report: Dict[str, Any]) -> None:
    print("Nexus validation report")
    for check in report["checks"]:
        print(f"- {check['name']}: {check['status']} ({check['detail']})")
    print(f"overall={report['overall']}")
    print(f"required_failed={report['required_failed']}")
    print(f"optional_failed={report['optional_failed']}")


def bootstrap_he65_nexus() -> None:
    _assert_root()
    _mkdirs()
    wrote_iface = _write_if_missing(ROOT / "runtime/interfaces/ilogger.py", LOGGER_INTERFACE_CODE)
    wrote_proto = _write_if_missing(ROOT / "docs/protocols/v1/logging_standard.md", LOGGING_PROTOCOL_MD)
    ticket_path = ROOT / "data/work/00_inbox/TICKET-001_implement_logger.json"
    existing_ticket = _load_json_file(ticket_path)
    if ticket_path.exists() and existing_ticket is None:
        print(f"WARNING: Existing ticket file is invalid JSON and was left unchanged: {ticket_path}")
    wrote_ticket = _write_if_missing(ticket_path, json.dumps(TICKET_001, indent=2))

    print("He65 Nexus Bootstrap Complete.")
    print(f"Interface created: {wrote_iface}")
    print(f"Protocol created: {wrote_proto}")
    print(f"Ticket created: {wrote_ticket}")
    print("Next: Implementer will now work on TICKET-001.")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap and validate He65 Nexus workspace")
    parser.add_argument("--validate-only", action="store_true", help="Run validation checks only")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit validation report as JSON")
    args = parser.parse_args(argv)

    report = _run_validation()
    if args.validate_only:
        if args.as_json:
            print(json.dumps(report, indent=2))
        else:
            _print_text_report(report)
        return 0 if report["required_failed"] == 0 else 1

    if args.as_json:
        parser.error("--json is only supported with --validate-only")

    if report["required_failed"] != 0:
        _print_text_report(report)
        return 1

    bootstrap_he65_nexus()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
