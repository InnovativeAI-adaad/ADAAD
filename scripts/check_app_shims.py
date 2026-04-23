#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail CI if deprecated app/ compatibility modules gain new logic."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

CHECK_PATHS = [
    ROOT / "app" / "agents",
    ROOT / "app" / "orchestration",
    ROOT / "app" / "api" / "governance.py",
    ROOT / "app" / "api" / "schemas",
]

REQUIRED_SNIPPETS = (
    "from app._deprecated_shim import warn_legacy_module",
    "warn_legacy_module(",
    "adaad.",
)


def _validate_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
    if missing:
        return [f"{path.relative_to(ROOT)} missing expected shim markers: {', '.join(missing)}"]
    if "Compatibility shim" not in text:
        return [f"{path.relative_to(ROOT)} missing compatibility shim docstring marker"]
    return []


def main() -> int:
    failures: list[str] = []
    for target in CHECK_PATHS:
        if target.is_file():
            failures.extend(_validate_file(target))
            continue
        for py_file in sorted(target.rglob("*.py")):
            failures.extend(_validate_file(py_file))

    if failures:
        print("app shim guard failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("app shim guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
