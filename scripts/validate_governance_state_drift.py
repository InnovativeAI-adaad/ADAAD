#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""validate_governance_state_drift.py — Phase 85 Track B: pre-merge drift gate.

Checks that .adaad_agent_state.json version/phase fields are in sync with
their canonical sources. Designed to run as a merge-blocking CI check.

EXIT CODES
  0 — all checks pass (no drift)
  1 — GOVERNANCE_DRIFT_* violations detected
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".adaad_agent_state.json"
VERSION_PATH = ROOT / "VERSION"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
INIT_PATH = ROOT / "adaad" / "__init__.py"
REPORT_VERSION_PATH = ROOT / "governance" / "report_version.json"
AGENT_STATE_SCHEMA_VERSION = "1.5.0"


@dataclass
class DriftViolation:
    code: str
    field: str
    expected: str
    found: str
    invariant: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "expected": self.expected,
            "found": self.found,
            "invariant": self.invariant,
        }


def _read_version() -> str:
    if not VERSION_PATH.exists():
        return "__MISSING__"
    return VERSION_PATH.read_text(encoding="utf-8").strip()


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _read_state() -> dict[str, Any] | None:
    return _read_json_object(STATE_PATH)


def _read_init_version() -> str | None:
    if not INIT_PATH.exists():
        return None
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"\s*$',
        INIT_PATH.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return match.group(1) if match else None


def _append_version_violation(
    violations: list[DriftViolation],
    *,
    code: str,
    field: str,
    expected: str,
    found: Any,
) -> None:
    if str(found) != expected:
        violations.append(DriftViolation(
            code=code,
            field=field,
            expected=expected,
            found=str(found),
            invariant="GSYNC-0",
        ))


def validate() -> list[DriftViolation]:
    violations: list[DriftViolation] = []
    version = _read_version()
    state = _read_state()

    if state is None:
        violations.append(DriftViolation(
            code="GOVERNANCE_DRIFT_STATE_UNREADABLE",
            field=".adaad_agent_state.json",
            expected="readable JSON object",
            found="missing or malformed",
            invariant="GSYNC-0",
        ))
        return violations

    init_version = _read_init_version()
    _append_version_violation(
        violations,
        code="GOVERNANCE_DRIFT_INIT_VERSION",
        field="adaad/__init__.py.__version__",
        expected=version,
        found=init_version if init_version is not None else "missing",
    )

    for field, code in (
        ("version", "GOVERNANCE_DRIFT_STATE_VERSION"),
        ("current_version", "GOVERNANCE_DRIFT_CURRENT_VERSION"),
        ("software_version", "GOVERNANCE_DRIFT_SOFTWARE_VERSION"),
        ("last_completed_version", "GOVERNANCE_DRIFT_LAST_COMPLETED_VERSION"),
    ):
        _append_version_violation(
            violations,
            code=code,
            field=f".adaad_agent_state.json.{field}",
            expected=version,
            found=state.get(field, "missing"),
        )

    report_version = _read_json_object(REPORT_VERSION_PATH)
    if report_version is None:
        violations.append(DriftViolation(
            code="GOVERNANCE_DRIFT_REPORT_VERSION_UNREADABLE",
            field="governance/report_version.json",
            expected="readable JSON object",
            found="missing or malformed",
            invariant="GSYNC-0",
        ))
    else:
        for field, code in (
            ("report_version", "GOVERNANCE_DRIFT_REPORT_VERSION"),
            ("version", "GOVERNANCE_DRIFT_REPORT_RELEASE_VERSION"),
        ):
            _append_version_violation(
                violations,
                code=code,
                field=f"governance/report_version.json.{field}",
                expected=version,
                found=report_version.get(field, "missing"),
            )

    schema_ver = str(state.get("schema_version", ""))
    if schema_ver != AGENT_STATE_SCHEMA_VERSION:
        violations.append(DriftViolation(
            code="GOVERNANCE_DRIFT_SCHEMA_VERSION",
            field="schema_version",
            expected=AGENT_STATE_SCHEMA_VERSION,
            found=schema_ver,
            invariant="GSYNC-SCHEMA-0",
        ))

    lcp = str(state.get("last_completed_phase", "")).strip()
    if not lcp:
        violations.append(DriftViolation(
            code="GOVERNANCE_DRIFT_LAST_COMPLETED_PHASE",
            field="last_completed_phase",
            expected="non-empty string",
            found="empty or missing",
            invariant="GSYNC-PHASE-0",
        ))

    return violations


def main() -> int:
    violations = validate()
    result = {
        "drift_check": "PASS" if not violations else "FAIL",
        "violation_count": len(violations),
        "violations": [v.to_dict() for v in violations],
    }
    print(json.dumps(result, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
