#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sync_versions.py — ADAAD Version Sync API Module
══════════════════════════════════════════════════════════════════════════════
Invariant codes: SVER-TRUTH-0 · SVER-ATOM-0 · SVER-IDEM-0 · SVER-DRIFT-0

PURPOSE
───────
Programmatic API for version synchronisation across the four-file atomic sync
surfaces. Designed to be imported by tests and CI scripts, as well as invoked
directly.  The underlying sync engine is version_sync.py; this module provides
a stable, testable API surface on top of it.

CONSTITUTIONAL INVARIANTS
──────────────────────────
  SVER-TRUTH-0   VERSION file is the sole canonical version source.
  SVER-ATOM-0    All file mutations are atomic (temp-write + os.replace).
  SVER-IDEM-0    Re-running on an already-synced repo produces no changes.
  SVER-DRIFT-0   Any surface mismatch is reported as a structured drift message.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# SVER-TRUTH-0: Canonical source readers
# ─────────────────────────────────────────────────────────────────────────────

def _load_version(root: Path) -> str:
    """Read the canonical version string from VERSION file."""
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def _load_pyproject_version(root: Path) -> str:
    """Read the version from pyproject.toml [project].version."""
    content = (root / "pyproject.toml").read_text(encoding="utf-8")
    # Try tomllib first (Python 3.11+), then regex fallback
    try:
        data = tomllib.loads(content)
        return data["project"]["version"]
    except Exception:
        m = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if m:
            return m.group(1)
        raise ValueError("Cannot parse version from pyproject.toml")


def _load_init_version(root: Path) -> str:
    """Read __version__ from adaad/__init__.py."""
    content = (root / "adaad" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if m:
        return m.group(1)
    raise ValueError("Cannot parse __version__ from adaad/__init__.py")


# ─────────────────────────────────────────────────────────────────────────────
# SVER-DRIFT-0: Drift detection
# ─────────────────────────────────────────────────────────────────────────────

def _version_drift_messages(root: Path, expected: str) -> list[str]:
    """Return a list of drift messages for any surface that deviates from expected."""
    msgs: list[str] = []

    # pyproject.toml
    try:
        pv = _load_pyproject_version(root)
        if pv != expected:
            msgs.append(f"VERSION_DRIFT: pyproject.toml.version={pv} does not match VERSION={expected}")
    except Exception as e:
        msgs.append(f"VERSION_DRIFT: pyproject.toml.version=UNREADABLE ({e}) does not match VERSION={expected}")

    # adaad/__init__.py
    try:
        iv = _load_init_version(root)
        if iv != expected:
            msgs.append(f"VERSION_DRIFT: adaad/__init__.py.__version__={iv} does not match VERSION={expected}")
    except Exception as e:
        msgs.append(f"VERSION_DRIFT: adaad/__init__.py.__version__=UNREADABLE ({e}) does not match VERSION={expected}")

    # .adaad_agent_state.json — multiple fields
    state_path = root / ".adaad_agent_state.json"
    if state_path.exists():
        try:
            state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            msgs.append(f"VERSION_DRIFT: .adaad_agent_state.json=UNREADABLE ({e})")
            state = {}
        for field in ("version", "current_version", "software_version", "last_completed_version"):
            val = state.get(field)
            if val is not None and val != expected:
                msgs.append(
                    f"VERSION_DRIFT: .adaad_agent_state.json.{field}={val} does not match VERSION={expected}"
                )

    # governance/report_version.json
    report_path = root / "governance" / "report_version.json"
    if report_path.exists():
        try:
            report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as e:
            msgs.append(f"VERSION_DRIFT: governance/report_version.json=UNREADABLE ({e})")
            report = {}
        for field in ("report_version", "version"):
            val = report.get(field)
            if val is not None and val != expected:
                msgs.append(
                    f"VERSION_DRIFT: governance/report_version.json.{field}={val} does not match VERSION={expected}"
                )

    return msgs


# ─────────────────────────────────────────────────────────────────────────────
# SVER-ATOM-0: Sync rules + file sync engine
# ─────────────────────────────────────────────────────────────────────────────

def _rules(version: str) -> dict[str, list[dict[str, Any]]]:
    """
    Return the set of regex-replace rules for each file surface.
    Each rule is: {"pattern": regex_str, "replacement": str}.
    """
    v = version
    return {
        "README.md": [
            {
                "pattern": r"(ADAAD-)v\d+\.\d+\.\d+(-)",
                "replacement": rf"\g<1>v{v}\2",
            },
            {
                "pattern": r"(\[!\[v)\d+\.\d+\.\d+(\])",
                "replacement": rf"\g<1>{v}\2",
            },
            {
                "pattern": r"(badge/version-v)\d+\.\d+\.\d+(-)",
                "replacement": rf"\g<1>{v}\2",
            },
            {
                "pattern": r"(\| \*\*Current version\*\* \| `)\d+\.\d+\.\d+(`)",
                "replacement": rf"\g<1>{v}\2",
            },
            {
                "pattern": r"(\| Current version \| `v)\d+\.\d+\.\d+(`)",
                "replacement": rf"\g<1>{v}\2",
            },
        ],
        "docs/README.md": [
            {
                "pattern": r"(ADAAD-)v\d+\.\d+\.\d+(-)",
                "replacement": rf"\g<1>v{v}\2",
            },
            {
                "pattern": r"(badge/ADAAD-v)\d+\.\d+\.\d+(-)",
                "replacement": rf"\g<1>{v}\2",
            },
            {
                "pattern": r"(\*\*ADAAD v)\d+\.\d+\.\d+( · Phase)",
                "replacement": rf"\g<1>{v}\2",
            },
            {
                "pattern": r"(ADAAD v)\d+\.\d+\.\d+( Runtime)",
                "replacement": rf"\g<1>{v}\2",
            },
            {
                "pattern": r"(<sub><code>ADAAD v)\d+\.\d+\.\d+(</code></sub>)",
                "replacement": rf"\g<1>{v}\2",
            },
        ],
        "docs/governance/ARCHITECT_SPEC_v3.1.0.md": [
            {
                "pattern": r"(badge/version-)\d+\.\d+\.\d+(-)",
                "replacement": rf"\g<1>{v}\2",
            },
        ],
    }


def _sync_file(
    path: Path,
    rules: list[dict[str, Any]],
    check_only: bool = False,
) -> tuple[bool, list[str]]:
    """
    Apply regex rules to a file. Returns (changed, list_of_change_descriptions).
    If check_only=True, no writes are performed.
    SVER-ATOM-0: writes use os.replace for atomicity.
    """
    if not path.exists():
        return False, []

    original = path.read_text(encoding="utf-8")
    current = original
    changes: list[str] = []

    for rule in rules:
        pattern = rule["pattern"]
        replacement = rule["replacement"]
        new = re.sub(pattern, replacement, current)
        if new != current:
            changes.append(f"{path.name}: applied pattern '{pattern[:40]}…'")
            current = new

    if current == original:
        return False, []

    if not check_only:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(current, encoding="utf-8")
        os.replace(tmp, path)

    return True, changes


# ─────────────────────────────────────────────────────────────────────────────
# Product surface sync (agent state + report_version + init)
# ─────────────────────────────────────────────────────────────────────────────

def _sync_product_version_surfaces(root: Path, version: str, check_only: bool = False) -> bool:
    """
    Sync .adaad_agent_state.json, governance/report_version.json, and
    adaad/__init__.py to the given version.
    Returns True if any changes were made (or would be made in check_only mode).
    SVER-ATOM-0: uses os.replace for all writes.
    """
    changed = False

    # ── .adaad_agent_state.json ──
    state_path = root / ".adaad_agent_state.json"
    if state_path.exists():
        state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
        version_fields = (
            "version", "current_version", "software_version", "last_completed_version"
        )
        state_changed = any(state.get(f) != version for f in version_fields)
        if state_changed:
            changed = True
            if not check_only:
                for f in version_fields:
                    if f in state:
                        state[f] = version
                # Ensure schema_version is preserved
                if "schema_version" not in state:
                    state["schema_version"] = "1.5.0"
                new_text = json.dumps(state, indent=2) + "\n"
                tmp = state_path.with_suffix(".tmp")
                tmp.write_text(new_text, encoding="utf-8")
                os.replace(tmp, state_path)

    # ── governance/report_version.json ──
    report_path = root / "governance" / "report_version.json"
    if report_path.exists():
        report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
        report_changed = report.get("version") != version or report.get("report_version") != version
        if report_changed:
            changed = True
            if not check_only:
                report["version"] = version
                report["report_version"] = version
                if "schema_version" not in report:
                    report["schema_version"] = "report-v1"
                new_text = json.dumps(report, indent=2) + "\n"
                tmp = report_path.with_suffix(".tmp")
                tmp.write_text(new_text, encoding="utf-8")
                os.replace(tmp, report_path)

    # ── adaad/__init__.py ──
    init_path = root / "adaad" / "__init__.py"
    if init_path.exists():
        content = init_path.read_text(encoding="utf-8")
        new_content = re.sub(
            r'^(__version__\s*=\s*["\'])\d+\.\d+\.\d+(["\'])',
            rf'\g<1>{version}\2',
            content,
            flags=re.MULTILINE,
        )
        if new_content != content:
            changed = True
            if not check_only:
                tmp = init_path.with_suffix(".tmp")
                tmp.write_text(new_content, encoding="utf-8")
                os.replace(tmp, init_path)

    return changed


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:  # pragma: no cover
    """Sync all version surfaces from VERSION file in CWD."""
    root = Path.cwd()
    version = _load_version(root)
    print(f"[sync_versions] canonical version: {version}")

    rules = _rules(version)
    total_changes: list[str] = []
    for rel_path, file_rules in rules.items():
        path = root / rel_path
        changed, ch = _sync_file(path, file_rules, check_only=False)
        if changed:
            total_changes.extend(ch)
            print(f"  [synced] {rel_path}")

    if _sync_product_version_surfaces(root, version, check_only=False):
        total_changes.append("product_surfaces synced")
        print("  [synced] product version surfaces")

    drift = _version_drift_messages(root, version)
    if drift:
        for msg in drift:
            print(f"  [DRIFT] {msg}", flush=True)
        return 1

    print(f"[sync_versions] complete — {len(total_changes)} changes applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
