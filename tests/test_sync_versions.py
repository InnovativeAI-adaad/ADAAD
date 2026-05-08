# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from scripts import sync_versions


def _write_repo(tmp_path: Path, version: str, pyproject_version: str) -> None:
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "adaad"\nversion = "{pyproject_version}"\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        '<img alt="ADAAD v0.0.1 — sample"/>\n'
        '[![Version](https://img.shields.io/badge/ADAAD-v0.0.1-000)]\n'
        '[![v0.0.0](https://img.shields.io/badge/version-v0.0.1-a855f7)]\n'
        '| **Current version** | `0.0.1` |\n'
        '| Current version | `v0.0.1` · Phase `1` |\n',
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "README.md").write_text(
        '[![Version](https://img.shields.io/badge/ADAAD-v0.0.1-000)]\n'
        '![version](https://img.shields.io/badge/ADAAD-v0.0.1-0d1117)\n'
        '**ADAAD v0.0.1 · Phase 1**\n'
        'ADAAD v0.0.1 Runtime\n'
        '<sub><code>ADAAD v0.0.1</code></sub>\n',
        encoding="utf-8",
    )
    (tmp_path / "docs" / "governance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "governance" / "ARCHITECT_SPEC_v3.1.0.md").write_text(
        "![Version: 0.0.1](https://img.shields.io/badge/version-0.0.1-00d4ff)\n",
        encoding="utf-8",
    )


def test_sync_versions_writes_expected_markers(tmp_path: Path) -> None:
    _write_repo(tmp_path, version="9.24.1", pyproject_version="9.24.1")
    assert sync_versions._load_version(tmp_path) == "9.24.1"
    assert sync_versions._load_pyproject_version(tmp_path) == "9.24.1"

    rules = sync_versions._rules("9.24.1")
    for rel_path, file_rules in rules.items():
        changed, _changes = sync_versions._sync_file(tmp_path / rel_path, file_rules, check_only=False)
        assert changed

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "ADAAD-v9.24.1" in readme
    assert "[![v9.24.1](https://img.shields.io/badge/version-v9.24.1-" in readme
    assert "| **Current version** | `9.24.1` |" in readme
    assert "| Current version | `v9.24.1` · Phase `1` |" in readme
    assert "ADAAD v9.24.1 Runtime" in (tmp_path / "docs/README.md").read_text(encoding="utf-8")
    assert "badge/version-9.24.1-" in (
        tmp_path / "docs/governance/ARCHITECT_SPEC_v3.1.0.md"
    ).read_text(encoding="utf-8")


def test_sync_versions_detects_pyproject_drift(tmp_path: Path) -> None:
    _write_repo(tmp_path, version="9.24.1", pyproject_version="9.24.0")
    assert sync_versions._load_pyproject_version(tmp_path) == "9.24.0"
    assert sync_versions._load_version(tmp_path) == "9.24.1"
