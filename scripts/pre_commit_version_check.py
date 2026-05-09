#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
pre_commit_version_check.py — ADAAD pre-commit version drift gate.
═══════════════════════════════════════════════════════════════════════════════

Blocks a git commit when any tracked surface disagrees with the VERSION file.
Designed to be called from .git/hooks/pre-commit via the install script below.

Install once per clone:
    python3 scripts/pre_commit_version_check.py --install

Run standalone:
    python3 scripts/pre_commit_version_check.py

If drift is detected, the commit is blocked and you are shown the exact
command to fix it:
    python3 scripts/version_sync.py

Exit codes:
    0   All surfaces agree with VERSION. Commit may proceed.
    1   Drift detected. Commit blocked.
"""

from __future__ import annotations

import json
import re
import sys
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _root(p: str) -> Path:
    return REPO_ROOT / p


def check() -> list[str]:
    """Return list of drift violations. Empty list = clean."""
    violations: list[str] = []

    # Canonical version
    try:
        version = _root("VERSION").read_text().strip()
    except FileNotFoundError:
        violations.append("VERSION file not found — cannot check drift")
        return violations

    # pyproject.toml
    try:
        pyproject = _root("pyproject.toml").read_text()
        m = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
        if m and m.group(1) != version:
            violations.append(
                f"pyproject.toml version={m.group(1)} ≠ VERSION={version}"
            )
    except FileNotFoundError:
        pass

    # .adaad_agent_state.json
    try:
        state = json.loads(_root(".adaad_agent_state.json").read_text())
        for field in ("version", "current_version", "software_version"):
            v = state.get(field)
            if v and v != version:
                violations.append(
                    f"agent_state[{field}]={v} ≠ VERSION={version}"
                )
                break
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # governance/report_version.json
    try:
        rv = json.loads(_root("governance/report_version.json").read_text())
        rv_ver = rv.get("version") or rv.get("report_version")
        if rv_ver and rv_ver != version:
            violations.append(
                f"report_version.json version={rv_ver} ≠ VERSION={version}"
            )
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # README.md shield badge
    try:
        readme = _root("README.md").read_text()
        m = re.search(
            r"!\[v[\d.]+\]\(https://img\.shields\.io/badge/version-(v[\d.]+)-",
            readme,
        )
        if m and m.group(1) != f"v{version}":
            violations.append(
                f"README.md version badge={m.group(1)} ≠ v{version}"
            )
    except FileNotFoundError:
        pass

    return violations


def install_hook() -> None:
    hook_path = REPO_ROOT / ".git" / "hooks" / "pre-commit"
    hook_content = f"""\
#!/bin/sh
# ADAAD version drift gate — installed by scripts/pre_commit_version_check.py
exec python3 "{Path(__file__).resolve()}"
"""
    hook_path.write_text(hook_content)
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"✓ Pre-commit hook installed at {hook_path}")


def main() -> int:
    if "--install" in sys.argv:
        install_hook()
        return 0

    violations = check()
    if not violations:
        print("✓ VSYNC-IDEM-0: version surfaces agree — commit allowed")
        return 0

    print("✗ VERSION DRIFT DETECTED — commit blocked\n", file=sys.stderr)
    for v in violations:
        print(f"  • {v}", file=sys.stderr)
    print(
        "\n  Fix: python3 scripts/version_sync.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
