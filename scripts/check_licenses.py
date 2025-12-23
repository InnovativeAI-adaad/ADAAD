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
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".pdf", ".mp4", ".mov", ".sqlite", ".db"}
ALLOW_MISSING_SPDX = {"LICENSE"}  # Non-code file, but keep here for clarity.


def python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def main() -> int:
    failures: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Creative Commons" in text or "CC0" in text:
            failures.append(f"CC reference found in {path}")
        if APACHE_HTTP in text:
            failures.append(f"HTTP Apache URL found in {path}")

    for py in python_files(REPO_ROOT):
        if py.name in ALLOW_MISSING_SPDX:
            continue
        head = py.read_text(encoding="utf-8").splitlines()[:25]
        if not any(SPDX_TAG in line for line in head):
            failures.append(f"Missing SPDX tag in {py}")

    if failures:
        for line in failures:
            print(line)
        return 1
    print("License checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
