# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

import pytest

from runtime.governance.branch_manager import BranchManager


def setup_branch(tmp_path: Path) -> BranchManager:
    repo = tmp_path / "repo"
    repo.mkdir()
    # mimic minimal repo structure
    for root in ["app", "runtime", "security", "ui", "tools", "experiments/branches"]:
        (repo / root).mkdir(parents=True, exist_ok=True)
    manager = BranchManager(repo_root=repo, branches_dir=repo / "experiments" / "branches")
    # create source file to copy
    src = repo / "app" / "sample.txt"
    src.write_text("hello", encoding="utf-8")
    manager.create_branch("b1")
    return manager


def test_promote_requires_explicit_targets(tmp_path: Path) -> None:
    manager = setup_branch(tmp_path)
    with pytest.raises(ValueError):
        manager.promote("b1", [])


def test_promote_blocks_forbidden_paths(tmp_path: Path) -> None:
    manager = setup_branch(tmp_path)
    branch_path = manager.branches_dir / "b1"
    forbidden = branch_path / "security" / "keys" / "secret.txt"
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError):
        manager.promote("b1", ["security/keys/secret.txt"])


def test_promote_blocks_non_allowlisted_root(tmp_path: Path) -> None:
    manager = setup_branch(tmp_path)
    branch_path = manager.branches_dir / "b1"
    other = branch_path / "outside.txt"
    other.write_text("data", encoding="utf-8")
    with pytest.raises(PermissionError):
        manager.promote("b1", ["outside.txt"])
