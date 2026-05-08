# SPDX-License-Identifier: Apache-2.0

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


def test_update_agent_state_preserves_canonical_schema_version(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / ".adaad_agent_state.json"
    state_path.write_text(
        '{\n'
        '  "schema_version": "1.5.0",\n'
        '  "active_phase": "v9.92.0 RELEASED · post-merge doc sync",\n'
        '  "last_invocation": "2026-03-06",\n'
        '  "last_sync_sha": "oldsha"\n'
        '}\n',
        encoding="utf-8",
    )
    plan = sync.SyncPlan(
        version="9.93.0",
        prev_version="9.92.0",
        date_str="2026-03-07",
        changelog_entry="",
        new_capabilities=[],
        new_modules=[],
        shipped_phases=[],
        git_sha="deadbee",
        git_branch="main",
        git_tag="v9.93.0",
        merged_files=[],
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)

    changes = sync._update_agent_state(plan)

    updated = state_path.read_text(encoding="utf-8")
    assert '"schema_version": "1.5.0"' in updated
    assert all(change["rule"] != "schema_version" for change in changes)
    assert {change["rule"] for change in changes} == {
        "active_phase",
        "last_invocation",
        "last_sync_sha",
    }
