# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

from scripts import sync_versions


def _write_repo(tmp_path: Path, version: str, pyproject_version: str) -> None:
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "adaad"\nversion = "{pyproject_version}"\n',
        encoding="utf-8",
    )
    (tmp_path / "adaad").mkdir(parents=True, exist_ok=True)
    (tmp_path / "adaad" / "__init__.py").write_text(
        '# SPDX-License-Identifier: Apache-2.0\n__version__ = "0.0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / ".adaad_agent_state.json").write_text(
        json.dumps(
            {
                "version": "0.0.1",
                "current_version": "0.0.1",
                "software_version": "0.0.1",
                "last_completed_version": "0.0.1",
                "schema_version": "1.5.0",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "governance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "governance" / "report_version.json").write_text(
        json.dumps({"report_version": "0.0.1", "version": "0.0.1", "schema_version": "report-v1"}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        '<img alt="ADAAD v0.0.1 — sample"/>\n'
        '[![Version](https://img.shields.io/badge/ADAAD-v0.0.1-000)]\n',
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

    assert "ADAAD-v9.24.1" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "ADAAD v9.24.1 Runtime" in (tmp_path / "docs/README.md").read_text(encoding="utf-8")
    assert "badge/version-9.24.1-" in (
        tmp_path / "docs/governance/ARCHITECT_SPEC_v3.1.0.md"
    ).read_text(encoding="utf-8")


def test_sync_versions_detects_pyproject_drift(tmp_path: Path) -> None:
    _write_repo(tmp_path, version="9.24.1", pyproject_version="9.24.0")
    assert sync_versions._load_pyproject_version(tmp_path) == "9.24.0"
    assert sync_versions._load_version(tmp_path) == "9.24.1"


def test_sync_versions_detects_all_product_surface_drift(tmp_path: Path) -> None:
    _write_repo(tmp_path, version="9.24.1", pyproject_version="9.24.0")

    assert sync_versions._version_drift_messages(tmp_path, "9.24.1") == [
        "VERSION_DRIFT: pyproject.toml.version=9.24.0 does not match VERSION=9.24.1",
        "VERSION_DRIFT: adaad/__init__.py.__version__=0.0.1 does not match VERSION=9.24.1",
        "VERSION_DRIFT: .adaad_agent_state.json.version=0.0.1 does not match VERSION=9.24.1",
        "VERSION_DRIFT: .adaad_agent_state.json.current_version=0.0.1 does not match VERSION=9.24.1",
        "VERSION_DRIFT: .adaad_agent_state.json.software_version=0.0.1 does not match VERSION=9.24.1",
        "VERSION_DRIFT: .adaad_agent_state.json.last_completed_version=0.0.1 does not match VERSION=9.24.1",
        "VERSION_DRIFT: governance/report_version.json.report_version=0.0.1 does not match VERSION=9.24.1",
        "VERSION_DRIFT: governance/report_version.json.version=0.0.1 does not match VERSION=9.24.1",
    ]


def test_sync_versions_repairs_product_surfaces_without_schema_version(tmp_path: Path) -> None:
    _write_repo(tmp_path, version="9.24.1", pyproject_version="9.24.1")

    assert sync_versions._sync_product_version_surfaces(tmp_path, "9.24.1", check_only=False)

    state = json.loads((tmp_path / ".adaad_agent_state.json").read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "governance" / "report_version.json").read_text(encoding="utf-8"))
    assert sync_versions._load_init_version(tmp_path) == "9.24.1"
    assert state["version"] == "9.24.1"
    assert state["current_version"] == "9.24.1"
    assert state["software_version"] == "9.24.1"
    assert state["last_completed_version"] == "9.24.1"
    assert state["schema_version"] == "1.5.0"
    assert report["report_version"] == "9.24.1"
    assert report["version"] == "9.24.1"
    assert report["schema_version"] == "report-v1"
    assert sync_versions._version_drift_messages(tmp_path, "9.24.1") == []
