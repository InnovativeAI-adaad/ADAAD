import json
import subprocess

import pytest

from scripts import sync_docs_and_assets as syncer

pytestmark = pytest.mark.regression_standard


def test_run_git_failure_exits_non_zero_with_structured_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def _raise_called_process_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "log", "--format=%s"],
            stderr="fatal: not a git repository",
        )

    monkeypatch.setattr(syncer.subprocess, "run", _raise_called_process_error)

    with pytest.raises(SystemExit) as exc:
        syncer._run_git(["log", "--format=%s"])

    assert exc.value.code == 1
    err = capsys.readouterr().err.strip()
    payload = json.loads(err)
    assert payload["event"] == "DOCSYNC_ERROR"

    detail = json.loads(payload["msg"])
    assert detail["kind"] == "git_command_failed"
    assert detail["error_type"] == "non_zero_exit"
    assert detail["args"] == ["log", "--format=%s"]
    assert "fatal:" in detail["stderr_snippet"]


def test_load_state_fails_when_git_log_content_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(syncer, "_run_git", lambda args: "")

    with pytest.raises(SystemExit) as exc:
        syncer._load_state()

    assert exc.value.code == 1


def test_load_state_is_deterministic_for_stable_git_and_files(monkeypatch: pytest.MonkeyPatch) -> None:
    subject_log = "\n".join(
        [
            "feat(phase65): INNOV-30 The Mirror Test — v9.0.0",
            "feat(phase64): INNOV-29 Curiosity-Driven Exploration — v8.7.0",
        ],
    )
    body_log = "Phase 65\nINNOV-30\nCumulative: 121\n"

    def _fake_run_git(args: list[str]) -> str:
        if args == ["log", "--format=%s", "--max-count=80"]:
            return subject_log
        if args == ["log", "--format=%B", "--max-count=30"]:
            return body_log
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(syncer, "_run_git", _fake_run_git)

    first = syncer._load_state()
    second = syncer._load_state()

    assert first == second
    assert first.phase == 65
    assert first.innov_num == 30
    assert first.hard >= 121
