# SPDX-License-Identifier: Apache-2.0

import ast
from pathlib import Path

from tools import lint_import_paths


def _parse(source: str) -> ast.AST:
    return ast.parse(source)


def test_iter_issues_allowlists_governance_direct_imports() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "__init__.py"
    tree = _parse("from governance.foundation import canonical\n")

    issues = list(lint_import_paths._iter_issues(path, tree))

    assert issues == []


def test_governance_impl_detection_flags_module_level_function() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "utils.py"
    tree = _parse("def helper():\n    return 1\n")

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert any(issue.message == lint_import_paths.GOVERNANCE_IMPL_VIOLATION_MESSAGE for issue in issues)


def test_governance_impl_detection_flags_module_level_class() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "utils.py"
    tree = _parse("class Adapter:\n    pass\n")

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert any(issue.message == lint_import_paths.GOVERNANCE_IMPL_VIOLATION_MESSAGE for issue in issues)


def test_governance_impl_detection_allows_all_assignment_only() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "utils.py"
    tree = _parse('__all__ = ["X"]\n')

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert issues == []


def test_governance_impl_detection_flags_nonstandard_assignment() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "utils.py"
    tree = _parse('VERSION = "1.0"\n')

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert any(issue.message == lint_import_paths.GOVERNANCE_IMPL_VIOLATION_MESSAGE for issue in issues)


def test_governance_impl_detection_ignores_runtime_governance_files() -> None:
    path = lint_import_paths.REPO_ROOT / "runtime" / "governance" / "foundation.py"
    tree = _parse("def helper():\n    return 1\n")

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert issues == []


def test_main_skips_always_excluded_before_governance_impl_check(tmp_path: Path, monkeypatch) -> None:
    excluded = tmp_path / "tools" / "lint_import_paths.py"
    excluded.parent.mkdir(parents=True, exist_ok=True)
    excluded.write_text("def forbidden():\n    return 1\n", encoding="utf-8")

    monkeypatch.setattr(lint_import_paths, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(lint_import_paths, "ALWAYS_EXCLUDED", frozenset({"tools/lint_import_paths.py"}))

    exit_code = lint_import_paths.main(["tools"])

    assert exit_code == 0


def test_governance_impl_detection_flags_nonstandard_annotated_assignment() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "utils.py"
    tree = _parse('VERSION: str = "1.0"\n')

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert any(issue.message == lint_import_paths.GOVERNANCE_IMPL_VIOLATION_MESSAGE for issue in issues)


def test_governance_impl_detection_allows_standard_annotated_assignment() -> None:
    path = lint_import_paths.REPO_ROOT / "governance" / "utils.py"
    tree = _parse('__version__: str = "1.0"\n')

    issues = list(lint_import_paths._iter_governance_impl_issues(path, tree))

    assert issues == []
