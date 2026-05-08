#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enforce exact Apache-2.0 SPDX headers on Python source files.

Usage:
    python scripts/check_spdx_headers.py [--fix] [paths...]

Exits non-zero if any file is missing the exact required header line
``# SPDX-License-Identifier: Apache-2.0`` within the allowed header window.
Other SPDX identifiers, including MIT or proprietary LicenseRef values, are
rejected for Python source files even when the repository-level distribution
license is proprietary. With --fix, writes or replaces the required header.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SPDX_LINE = "# SPDX-License-Identifier: Apache-2.0"
HEADER_WINDOW_LINES = 6

EXCLUDE_PATTERNS = (
    ".git",
    "__pycache__",
    "*.egg-info",
    "node_modules",
    ".venv",
    "venv",
    "archives/",
    "brand/",
)

DEFAULT_SCAN_DIRS = (
    ".codex",
    "app",
    "adaad",
    "core",
    "dorkllm",
    "evolution",
    "examples",
    "runtime",
    "sandbox",
    "scripts",
    "security",
    "tests",
    "tools",
    "governance",
    "ui",
    "server.py",
    "nexus_setup.py",
    "onboard_phone.py",
    "patch_dork.py",
)


def _excluded(path: Path) -> bool:
    parts = path.parts
    return any(excl.rstrip("/") in parts or path.match(excl) for excl in EXCLUDE_PATTERNS)


def _has_spdx(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= HEADER_WINDOW_LINES:
                    break
                if line.rstrip("\r\n") == SPDX_LINE:
                    return True
    except OSError:
        pass
    return False


def _fix_file(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines[:HEADER_WINDOW_LINES]):
        if "SPDX-License-Identifier" in line:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines[i] = SPDX_LINE + newline
            path.write_text("".join(lines), encoding="utf-8")
            return
    content = "".join(lines)
    path.write_text(SPDX_LINE + "\n" + content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SPDX headers on Python files.")
    parser.add_argument("paths", nargs="*", help="Paths to scan (default: repo source dirs)")
    parser.add_argument("--fix", action="store_true", help="Add missing headers automatically")
    args = parser.parse_args()

    scan_roots = [REPO_ROOT / p for p in (args.paths or DEFAULT_SCAN_DIRS)]
    violations: list[Path] = []

    for root in scan_roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in candidates:
            if path.suffix != ".py" or _excluded(path):
                continue
            if not _has_spdx(path):
                violations.append(path)

    if not violations:
        print(f"✅ SPDX check passed — all Python files have exact Apache-2.0 license headers.")
        return 0

    for v in violations:
        try:
            rel = v.relative_to(REPO_ROOT)
        except ValueError:
            rel = v
        if args.fix:
            _fix_file(v)
            print(f"  fixed: {rel}")
        else:
            print(f"  MISSING: {rel}")

    if args.fix:
        print(f"✅ Fixed {len(violations)} file(s).")
        return 0

    print(f"\n❌ {len(violations)} file(s) missing exact Apache-2.0 SPDX-License-Identifier header.")
    print("Run with --fix to add or replace headers automatically.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
