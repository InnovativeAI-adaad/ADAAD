# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "VERSION").write_text("9.17.0\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "## [9.17.0] — 2026-03-21 — Phase 85 · KMS/HSM + Governance Sync\n",
        encoding="utf-8",
    )
    state = {
        "schema_version": "1.5.0",
        "current_version": "9.12.1",
        "software_version": "9.12.1",
        "active_phase": "old",
        "last_invocation": "2026-01-01",
        "last_sync_sha": "abc1234",
        "last_completed_phase": "old phase",
        "last_agent_state_sync_digest": "gsync-old",
        "open_findings": [],
        "value_checkpoints_reached": [],
    }
    (tmp_path / ".adaad_agent_state.json").write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _import_sync(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "sync_agent_state_on_merge",
        ROOT / "scripts" / "sync_agent_state_on_merge.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.ROOT = tmp_path
    mod.STATE_PATH = tmp_path / ".adaad_agent_state.json"
    mod.VERSION_PATH = tmp_path / "VERSION"
    mod.CHANGELOG_PATH = tmp_path / "CHANGELOG.md"
    return mod


def test_git_sha_failure_exits_and_emits_event_without_writing(
    tmp_repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _import_sync(tmp_repo)
    original = mod.STATE_PATH.read_text(encoding="utf-8")

    def _raise_called_process_error(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=128, cmd=["git", "rev-parse"])

    monkeypatch.setattr(mod.subprocess, "check_output", _raise_called_process_error)

    with pytest.raises(SystemExit) as exc:
        mod.sync_agent_state(dry_run=False)

    assert exc.value.code == 1
    event = json.loads(capsys.readouterr().out.strip())
    assert event["event"] == "AGENT_STATE_SYNC_ERROR_GIT_SHA"
    assert "exit=128" in event["message"]
    assert mod.STATE_PATH.read_text(encoding="utf-8") == original


def test_success_path_writes_sha_and_deterministic_digest(tmp_repo: Path) -> None:
    mod = _import_sync(tmp_repo)
    mod._git_sha = lambda: "deadbee"

    mod.sync_agent_state(dry_run=False)

    state = json.loads(mod.STATE_PATH.read_text(encoding="utf-8"))
    expected_phase = "Phase 85 · KMS/HSM + Governance Sync"
    expected_digest = mod._compute_sync_digest("9.17.0", expected_phase, "deadbee")

    assert state["last_sync_sha"] == "deadbee"
    assert state["last_agent_state_sync_digest"] == expected_digest
