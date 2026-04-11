# SPDX-License-Identifier: Apache-2.0
"""Governance-facing adapter over the canonical evolution change classifier."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from runtime.evolution.change_classifier import is_doc_change, is_functional_change


class ChangeType(Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    UNKNOWN = "unknown"


_DOCUMENTATION_EXTENSIONS = {".md", ".txt", ".comment"}


@dataclass(frozen=True)
class RepositoryChangeDecision:
    change_type: ChangeType
    reason: str
    changed_files: tuple[str, ...]


def _run_git_text(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=cwd)
    return result.stdout


def _get_changed_files() -> set[str]:
    """Return files changed in the working tree compared with HEAD."""
    try:
        output = _run_git_text("diff", "HEAD", "--name-only")
    except subprocess.CalledProcessError:
        return set()
    return {line.strip() for line in output.splitlines() if line.strip()}


def _is_documentation_path(path_str: str) -> bool:
    path = Path(path_str)
    if path.suffix.lower() in _DOCUMENTATION_EXTENSIONS:
        return True
    if "docs" in path.parts:
        return True
    if path.name.startswith("#"):
        return True
    return False


def _old_file_contents(path: str) -> str:
    try:
        return _run_git_text("show", f"HEAD:{path}")
    except subprocess.CalledProcessError:
        return ""


def _new_file_contents(path: str) -> str:
    candidate = Path(path)
    if not candidate.exists():
        return ""
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return ""


def _python_change_type(path: str) -> ChangeType:
    old_src = _old_file_contents(path)
    new_src = _new_file_contents(path)
    if is_doc_change(old_src, new_src):
        return ChangeType.NON_FUNCTIONAL

    old_ast = _try_parse(old_src)
    new_ast = _try_parse(new_src)
    if old_ast is not None and new_ast is not None and not is_functional_change(old_ast, new_ast):
        return ChangeType.NON_FUNCTIONAL
    return ChangeType.FUNCTIONAL


def _try_parse(source: str):
    import ast

    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _iter_change_types(files: Iterable[str]) -> Iterable[ChangeType]:
    for file_path in files:
        if _is_documentation_path(file_path):
            yield ChangeType.NON_FUNCTIONAL
            continue
        if Path(file_path).suffix.lower() == ".py":
            yield _python_change_type(file_path)
            continue
        yield ChangeType.FUNCTIONAL


def classify_current_changes_decision() -> RepositoryChangeDecision:
    changed_files = sorted(_get_changed_files())
    if not changed_files:
        return RepositoryChangeDecision(ChangeType.NON_FUNCTIONAL, "no_changes", tuple())

    for decision in _iter_change_types(changed_files):
        if decision == ChangeType.FUNCTIONAL:
            return RepositoryChangeDecision(ChangeType.FUNCTIONAL, "ast_or_code_change", tuple(changed_files))
    return RepositoryChangeDecision(ChangeType.NON_FUNCTIONAL, "documentation_comment_or_whitespace_only", tuple(changed_files))


def classify_current_changes() -> ChangeType:
    """Analyze current repository changes and return a global ChangeType."""
    return classify_current_changes_decision().change_type


__all__ = ["ChangeType", "RepositoryChangeDecision", "classify_current_changes", "classify_current_changes_decision"]
