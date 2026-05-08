#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synchronize repository documentation version markers to canonical VERSION.

Policy:
- Canonical runtime release version is stored in VERSION.
- pyproject.toml [project].version must match VERSION.
- Selected docs/release badge markers must match VERSION.

Use --check in CI to fail when drift is detected.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class SyncRule:
    pattern: re.Pattern[str]
    replacement: str
    description: str


def _load_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER_RE.fullmatch(version):
        raise SystemExit(f"VERSION must be strict semver X.Y.Z, found: {version!r}")
    return version


def _load_pyproject_version(root: Path) -> str:
    content = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
    if not match:
        raise SystemExit("Unable to parse [project].version from pyproject.toml")
    return match.group(1)


def _rules(version: str) -> dict[str, list[SyncRule]]:
    return {
        "README.md": [
            SyncRule(
                pattern=re.compile(r"(img\.shields\.io/badge/ADAAD-v)(\d+\.\d+\.\d+)(-)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="README ADAAD badge",
            ),
            SyncRule(
                pattern=re.compile(r"(alt=\"ADAAD v)(\d+\.\d+\.\d+)( —)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="README hero alt version",
            ),
            SyncRule(
                pattern=re.compile(r"(\[!\[v)(\d+\.\d+\.\d+)(\]\(https://img\.shields\.io/badge/version-v)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="README visible version badge label",
            ),
            SyncRule(
                pattern=re.compile(r"(img\.shields\.io/badge/version-v)(\d+\.\d+\.\d+)(-)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="README version badge",
            ),
            SyncRule(
                pattern=re.compile(r"(\| \*\*Current version\*\* \| `)(\d+\.\d+\.\d+)(` \|)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="README generated version infobox",
            ),
            SyncRule(
                pattern=re.compile(r"(\| Current version \| `v)(\d+\.\d+\.\d+)(` · Phase `\d+` \|)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="README by-the-numbers version",
            ),
        ],
        "docs/README.md": [
            SyncRule(
                pattern=re.compile(r"(img\.shields\.io/badge/ADAAD-v)(\d+\.\d+\.\d+)(-)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README ADAAD badges",
            ),
            SyncRule(
                pattern=re.compile(r"(\*\*ADAAD v)(\d+\.\d+\.\d+)( · Phase)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README intro version",
            ),
            SyncRule(
                pattern=re.compile(r"(ADAAD v)(\d+\.\d+\.\d+)( Runtime)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README runtime map title",
            ),
            SyncRule(
                pattern=re.compile(r"(<sub><code>ADAAD v)(\d+\.\d+\.\d+)(</code>)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README footer version",
            ),
        ],
        "docs/governance/ARCHITECT_SPEC_v3.1.0.md": [
            SyncRule(
                pattern=re.compile(r"(!\[Version:\s*)(\d+\.\d+\.\d+)(\])"),
                replacement=rf"\g<1>{version}\g<3>",
                description="Architect spec version label",
            ),
            SyncRule(
                pattern=re.compile(r"(img\.shields\.io/badge/version-)(\d+\.\d+\.\d+)(-)") ,
                replacement=rf"\g<1>{version}\g<3>",
                description="Architect spec version badge",
            ),
        ],
    }


def _sync_file(path: Path, rules: list[SyncRule], check_only: bool) -> tuple[bool, list[str]]:
    original = path.read_text(encoding="utf-8")
    updated = original
    changes: list[str] = []
    for rule in rules:
        next_updated, count = rule.pattern.subn(rule.replacement, updated)
        if count > 0 and next_updated != updated:
            changes.append(f"{rule.description}: {count}")
        updated = next_updated

    changed = updated != original
    if changed and not check_only:
        path.write_text(updated, encoding="utf-8")
    return changed, changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync docs version markers to VERSION")
    parser.add_argument("--check", action="store_true", help="Fail on drift without writing files")
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    version = _load_version(root)
    pyproject_version = _load_pyproject_version(root)

    if pyproject_version != version:
        print(
            f"VERSION_DRIFT: pyproject.toml version={pyproject_version} does not match VERSION={version}"
        )
        return 1

    any_changes = False
    for rel_path, rules in _rules(version).items():
        file_path = root / rel_path
        changed, changes = _sync_file(file_path, rules, check_only=args.check)
        any_changes = any_changes or changed
        if changed:
            print(f"VERSION_DRIFT: {rel_path} :: {', '.join(changes)}")

    if args.check and any_changes:
        print("VERSION_SYNC_CHECK_FAILED")
        return 1

    print("VERSION_SYNC_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
