# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytestmark = pytest.mark.regression_standard

from scripts import sync_docs_on_merge as sync


def test_update_arch_snapshot_includes_tag_row() -> None:
    content = (
        "# Title\n\n"
        "<!-- ARCH_SNAPSHOT_METADATA:START -->\n"
        "old\n"
        "<!-- ARCH_SNAPSHOT_METADATA:END -->\n"
    )
    plan = sync.SyncPlan(
        version="3.0.0",
        prev_version="2.9.0",
        date_str="2026-03-07",
        changelog_entry="",
        new_capabilities=[],
        new_modules=[],
        shipped_phases=[],
        git_sha="deadbee",
        git_branch="main",
        git_tag="(none)",
        merged_files=[],
    )

    updated, changes = sync._update_arch_snapshot(content, plan)

    assert "| Tag | `(none)` |" in updated
    assert "| Branch | `main` |" in updated
    assert "| Short SHA | `deadbee` |" in updated
    assert changes == ["ARCH_SNAPSHOT→v3.0.0/deadbee"]



def test_report_version_sync_updates_release_alias() -> None:
    plan = sync.SyncPlan(
        version="9.106.0",
        prev_version="9.105.0",
        date_str="2026-05-07",
        changelog_entry="",
        new_capabilities=[],
        new_modules=[],
        shipped_phases=[],
        git_sha="deadbee",
        git_branch="main",
        git_tag="(none)",
        merged_files=[],
    )
    old_root = sync.ROOT
    try:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "governance").mkdir()
            report = root / "governance" / "report_version.json"
            report.write_text(
                json.dumps({"report_version": "9.105.0", "version": "9.105.0", "last_sync_sha": "old"}),
                encoding="utf-8",
            )
            sync.ROOT = root
            changes = sync._update_governance_report_version(plan)
            updated = json.loads(report.read_text(encoding="utf-8"))
    finally:
        sync.ROOT = old_root

    assert changes
    assert updated["report_version"] == "9.106.0"
    assert updated["version"] == "9.106.0"


def test_agent_state_sync_preserves_schema_version_and_sets_release_aliases(tmp_path) -> None:
    plan = sync.SyncPlan(
        version="9.106.0",
        prev_version="9.105.0",
        date_str="2026-05-07",
        changelog_entry="",
        new_capabilities=[],
        new_modules=[],
        shipped_phases=[],
        git_sha="deadbee",
        git_branch="main",
        git_tag="(none)",
        merged_files=[],
    )
    state_path = tmp_path / ".adaad_agent_state.json"
    state_path.write_text(
        '{"schema_version":"1.5.0","version":"9.105.0","last_completed_version":"9.105.0"}',
        encoding="utf-8",
    )
    old_root = sync.ROOT
    try:
        sync.ROOT = tmp_path
        changes = sync._update_agent_state(plan)
        updated = json.loads(state_path.read_text(encoding="utf-8"))
    finally:
        sync.ROOT = old_root

    assert changes
    assert updated["schema_version"] == "1.5.0"
    assert updated["version"] == "9.106.0"
    assert updated["last_completed_version"] == "9.106.0"
    assert updated["current_version"] == "9.106.0"
    assert updated["software_version"] == "9.106.0"
