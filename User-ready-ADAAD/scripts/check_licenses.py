# SPDX-License-Identifier: Apache-2.0
"""
Fail-fast license guardrail.

Checks:
- No Creative Commons licenses referenced.
- No HTTP Apache license URLs.
- All Python files contain an SPDX identifier (Apache-2.0).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APACHE_HTTP = "http://www.apache.org/licenses"
SPDX_TAG = "# SPDX-License-Identifier: Apache-2.0"
CC_TERMS = "Creative Commons"
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".pdf", ".mp4", ".mov", ".sqlite", ".db"}
ALLOW_MISSING_SPDX = {"LICENSE"}  # Non-code file, but keep here for clarity.
ALLOW_TEXT_PATHS = {Path(__file__).resolve()}


def python_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in ALLOW_MISSING_SPDX:
            continue
        paths.append(path)
    return paths


def main() -> int:
    failures: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if APACHE_HTTP in text and path.resolve() not in ALLOW_TEXT_PATHS:
                failures.append(f"HTTP Apache URL found in {path}")
            if CC_TERMS in text and path.resolve() not in ALLOW_TEXT_PATHS:
                failures.append(f"Creative Commons reference found in {path}")

    for py in python_files(REPO_ROOT):
        head = py.read_text(encoding="utf-8").splitlines()[:25]
        if not any(SPDX_TAG in line for line in head):
            failures.append(f"Missing SPDX tag in {py}")

    if failures:
        for line in failures:
            print(line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
