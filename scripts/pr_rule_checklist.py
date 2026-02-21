#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate/validate PR constitutional rule checklists from applicability output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

START = "<!-- RULE_APPLICABILITY_CHECKLIST_START -->"
END = "<!-- RULE_APPLICABILITY_CHECKLIST_END -->"


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evaluation_payload_invalid")
    return payload


def _get_matrix(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "payload" in payload and isinstance(payload["payload"], dict):
        payload = payload["payload"]
    matrix = payload.get("applicability_matrix")
    if not isinstance(matrix, list):
        raise ValueError("applicability_matrix_missing")
    return [item for item in matrix if isinstance(item, dict)]


def _normalize_rule_names(matrix: List[Dict[str, Any]]) -> List[str]:
    result: List[str] = []
    for row in matrix:
        if row.get("applicable") is not True:
            continue
        name = str(row.get("rule", "")).strip()
        if name:
            result.append(name)
    return sorted(set(result))


def _render_checklist(rule_names: List[str]) -> str:
    lines = [START]
    for name in rule_names:
        lines.append(f"- [ ] {name}")
    lines.append(END)
    return "\n".join(lines)


def _extract_between_markers(body: str) -> str:
    start = body.find(START)
    end = body.find(END)
    if start < 0 or end < 0 or end < start:
        raise ValueError("checklist_markers_missing")
    return body[start : end + len(END)]


def _extract_checked_rules(body: str) -> List[str]:
    rules: List[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [") and "] " in stripped:
            rules.append(stripped.split("] ", 1)[1].strip())
    return rules


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/validate PR rule checklist.")
    parser.add_argument("--evaluation-json", required=True)
    parser.add_argument("--pr-body-file")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    payload = _load_json(Path(args.evaluation_json))
    matrix = _get_matrix(payload)
    rule_names = _normalize_rule_names(matrix)

    if not args.validate:
        print(_render_checklist(rule_names))
        return 0

    if not args.pr_body_file:
        raise SystemExit("--pr-body-file is required when --validate is set")

    body = Path(args.pr_body_file).read_text(encoding="utf-8")
    block = _extract_between_markers(body)
    found = sorted(set(_extract_checked_rules(block)))
    expected = sorted(set(rule_names))
    if found != expected:
        print(json.dumps({"ok": False, "expected": expected, "found": found}, indent=2))
        return 1
    print(json.dumps({"ok": True, "rules": expected}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
