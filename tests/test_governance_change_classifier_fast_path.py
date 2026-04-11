# SPDX-License-Identifier: Apache-2.0
import subprocess
from pathlib import Path

from runtime.governance.change_classifier import ChangeType, classify_current_changes_decision
from runtime.governance.fast_path_policy import OperatingMode, get_required_gate_tiers


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "tests@example.com"], repo)
    _run(["git", "config", "user.name", "tests"], repo)


def _commit_file(repo: Path, rel_path: str, content: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _run(["git", "add", rel_path], repo)
    _run(["git", "commit", "-m", f"add {rel_path}"], repo)


def test_docstring_only_python_change_is_non_functional_for_fast_tier(monkeypatch, tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "agent.py", "def run():\n    return 1\n")
    (tmp_path / "agent.py").write_text('def run():\n    """updated docs"""\n    return 1\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    decision = classify_current_changes_decision()
    assert decision.change_type == ChangeType.NON_FUNCTIONAL
    assert get_required_gate_tiers(OperatingMode.DEV_FAST, decision.change_type) == {0}


def test_comment_only_python_change_is_non_functional_for_fast_tier(monkeypatch, tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "agent.py", "def run():\n    return 1\n")
    (tmp_path / "agent.py").write_text("# comment only\n\ndef run():\n    return 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    decision = classify_current_changes_decision()
    assert decision.change_type == ChangeType.NON_FUNCTIONAL
    assert get_required_gate_tiers(OperatingMode.DEV_FAST, decision.change_type) == {0}


def test_logic_change_python_is_functional_for_fast_tier(monkeypatch, tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_file(tmp_path, "agent.py", "def run():\n    return 1\n")
    (tmp_path / "agent.py").write_text("def run():\n    return 2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    decision = classify_current_changes_decision()
    assert decision.change_type == ChangeType.FUNCTIONAL
    assert get_required_gate_tiers(OperatingMode.DEV_FAST, decision.change_type) == {0, 1}
