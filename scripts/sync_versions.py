#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synchronize repository documentation and product version markers to VERSION.

Policy:
- Canonical runtime release version is stored in VERSION.
- pyproject.toml [project].version and product-version surfaces must match VERSION.
- Selected docs/release badge markers must match VERSION.
- schema_version fields describe JSON schema compatibility and are never mutated.

Use --check in CI to fail when drift is detected.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class SyncRule:
    pattern: re.Pattern[str]
    replacement: str
    description: str


@dataclass(frozen=True)
class VersionSurface:
    """A product-version surface that must mirror the canonical VERSION value.

    Rationale: release gates consume these fields independently, so every
    surface listed here is checked for drift; write mode repairs only these
    product-version fields and intentionally excludes schema_version.
    """

    rel_path: str
    field: str
    description: str


PRODUCT_VERSION_SURFACES: tuple[VersionSurface, ...] = (
    VersionSurface("adaad/__init__.py", "__version__", "adaad package version"),
    VersionSurface(".adaad_agent_state.json", "version", "agent state release version"),
    VersionSurface(".adaad_agent_state.json", "current_version", "agent state current version"),
    VersionSurface(".adaad_agent_state.json", "software_version", "agent state software version"),
    VersionSurface(
        ".adaad_agent_state.json",
        "last_completed_version",
        "agent state last completed release version",
    ),
    VersionSurface("governance/report_version.json", "report_version", "governance report version"),
    VersionSurface("governance/report_version.json", "version", "governance report release version"),
)


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


def _load_init_version(root: Path) -> str:
    content = (root / "adaad" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
    if not match:
        raise SystemExit("Unable to parse adaad/__init__.py::__version__")
    return match.group(1)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Unable to parse JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected JSON object in {path}")
    return value


def _load_json_field(root: Path, rel_path: str, field: str) -> str:
    data = _read_json_object(root / rel_path)
    if field not in data:
        raise SystemExit(f"Unable to parse {rel_path}.{field}")
    return str(data[field])


def _load_agent_state_version(root: Path, field: str) -> str:
    return _load_json_field(root, ".adaad_agent_state.json", field)


def _load_report_version(root: Path, field: str) -> str:
    return _load_json_field(root, "governance/report_version.json", field)


def _surface_value(root: Path, surface: VersionSurface) -> str:
    if surface.rel_path == "adaad/__init__.py" and surface.field == "__version__":
        return _load_init_version(root)
    if surface.rel_path == ".adaad_agent_state.json":
        return _load_agent_state_version(root, surface.field)
    if surface.rel_path == "governance/report_version.json":
        return _load_report_version(root, surface.field)
    raise SystemExit(f"Unsupported version surface: {surface.rel_path}.{surface.field}")


def _version_drift_messages(root: Path, version: str) -> list[str]:
    messages: list[str] = []
    pyproject_version = _load_pyproject_version(root)
    if pyproject_version != version:
        messages.append(
            f"VERSION_DRIFT: pyproject.toml.version={pyproject_version} does not match VERSION={version}"
        )

    for surface in PRODUCT_VERSION_SURFACES:
        found = _surface_value(root, surface)
        if found != version:
            messages.append(
                f"VERSION_DRIFT: {surface.rel_path}.{surface.field}={found} does not match VERSION={version}"
            )
    return messages


def _write_init_version(root: Path, version: str) -> bool:
    path = root / "adaad" / "__init__.py"
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^__version__\s*=\s*"([^"]+)"\s*$',
        f'__version__ = "{version}"',
        original,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit("Unable to update adaad/__init__.py::__version__")
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _write_json_versions(root: Path, rel_path: str, fields: tuple[str, ...], version: str) -> bool:
    path = root / rel_path
    data = _read_json_object(path)
    changed = False
    for field in fields:
        if field not in data:
            raise SystemExit(f"Unable to update {rel_path}.{field}")
        if str(data[field]) != version:
            data[field] = version
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return changed


def _sync_product_version_surfaces(root: Path, version: str, check_only: bool) -> bool:
    if check_only:
        return bool(_version_drift_messages(root, version))

    changed = False
    changed = _write_init_version(root, version) or changed
    changed = _write_json_versions(
        root,
        ".adaad_agent_state.json",
        ("version", "current_version", "software_version", "last_completed_version"),
        version,
    ) or changed
    changed = _write_json_versions(
        root,
        "governance/report_version.json",
        ("report_version", "version"),
        version,
    ) or changed
    return changed


def _rules(version: str) -> dict[str, list[SyncRule]]:
    return {
        "README.md": [
            SyncRule(
                pattern=re.compile(r"(img\.shields\.io/badge/ADAAD-v)(\d+\.\d+\.\d+)(-)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="README ADAAD badge",
            ),
            SyncRule(
                pattern=re.compile(r"(alt=\"ADAAD v)(\d+\.\d+\.\d+)( —)"),
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
                pattern=re.compile(r"(img\.shields\.io/badge/ADAAD-v)(\d+\.\d+\.\d+)(-)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README ADAAD badges",
            ),
            SyncRule(
                pattern=re.compile(r"(\*\*ADAAD v)(\d+\.\d+\.\d+)( · Phase)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README intro version",
            ),
            SyncRule(
                pattern=re.compile(r"(ADAAD v)(\d+\.\d+\.\d+)( Runtime)"),
                replacement=rf"\g<1>{version}\g<3>",
                description="docs README runtime map title",
            ),
            SyncRule(
                pattern=re.compile(r"(<sub><code>ADAAD v)(\d+\.\d+\.\d+)(</code>)"),
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
                pattern=re.compile(r"(img\.shields\.io/badge/version-)(\d+\.\d+\.\d+)(-)"),
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

    drift_messages = _version_drift_messages(root, version)
    for message in drift_messages:
        print(message)

    any_changes = _sync_product_version_surfaces(root, version, check_only=args.check)
    for rel_path, rules in _rules(version).items():
        file_path = root / rel_path
        changed, changes = _sync_file(file_path, rules, check_only=args.check)
        any_changes = any_changes or changed
        if changed:
            print(f"VERSION_DRIFT: {rel_path} :: {', '.join(changes)}")

    if args.check and any_changes:
        print("VERSION_SYNC_CHECK_FAILED")
        return 1

    if not args.check and _version_drift_messages(root, version):
        print("VERSION_SYNC_REPAIR_INCOMPLETE")
        return 1

    print("VERSION_SYNC_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
