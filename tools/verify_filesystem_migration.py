#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify deterministic filesystem wrapper migration in governance-critical paths."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATHS = ["runtime/governance", "runtime/evolution"]
WRAPPER_IMPORT = "from runtime.governance.deterministic_filesystem import"
VIOLATION_PATTERN = re.compile(r"\.read_text\(|\.open\(.*[\"']r[\"']\)|os\.listdir\(|os\.walk\(|glob\.glob\(")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _python_wrapper_import_count() -> int:
    count = 0
    for target in TARGET_PATHS:
        for path in sorted((REPO_ROOT / target).rglob("*.py")):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if WRAPPER_IMPORT in content:
                count += 1
    return count


def _python_find_violations() -> list[str]:
    violations: list[str] = []
    for target in TARGET_PATHS:
        for path in sorted((REPO_ROOT / target).rglob("*.py")):
            if path.name.endswith("_test.py") or path.name.startswith("test_"):
                continue
            if path.relative_to(REPO_ROOT).as_posix() == "runtime/governance/deterministic_filesystem.py":
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if VIOLATION_PATTERN.search(line):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{line.strip()}")
    return violations


def main() -> int:
    print("=== Filesystem Wrapper Migration Verification ===\n")

    print("1. Running determinism linter...")
    lint = _run(["python", "tools/lint_determinism.py", *TARGET_PATHS])
    if lint.returncode != 0:
        print("❌ Lint failed:")
        print(lint.stdout.strip())
        if lint.stderr.strip():
            print(lint.stderr.strip())
        return 1
    print("✅ Lint passed\n")

    rg_available = shutil.which("rg") is not None

    print("2. Verifying deterministic wrapper imports...")
    if rg_available:
        wrapper_imports = _run(
            [
                "rg",
                "-t",
                "py",
                WRAPPER_IMPORT,
                *TARGET_PATHS,
                "--count-matches",
            ]
        )
        files_with_import = [line for line in wrapper_imports.stdout.splitlines() if line.strip()]
        import_count = len(files_with_import)
    else:
        print("⚠️ ripgrep not found; using Python fallback scanner for wrapper adoption count")
        import_count = _python_wrapper_import_count()

    print(f"   Found {import_count} files using deterministic wrappers")
    if import_count < 11:
        print(f"❌ Expected at least 11 files, found {import_count}")
        return 1
    print("✅ Wrapper adoption verified\n")

    print("3. Checking for non-wrapped operations...")
    if rg_available:
        violations = _run(
            [
                "rg",
                "-t",
                "py",
                VIOLATION_PATTERN.pattern,
                *TARGET_PATHS,
                "--glob",
                "!*_test.py",
                "--glob",
                "!test_*.py",
                "--glob",
                "!runtime/governance/deterministic_filesystem.py",
            ]
        )
        output = violations.stdout.strip()
        found_violations = output.splitlines() if output else []
    else:
        print("⚠️ ripgrep not found; using Python fallback scanner for violation detection")
        found_violations = _python_find_violations()

    if found_violations:
        print("❌ Found unwrapped operations:")
        print("\n".join(found_violations))
        return 1

    print("✅ No unwrapped operations found\n")
    print("=== ✅ Migration Verification Complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
