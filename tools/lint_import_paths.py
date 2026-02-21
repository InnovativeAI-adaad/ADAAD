#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enforce canonical runtime import paths in production code."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS: tuple[str, ...] = ("app", "runtime", "security", "ui", "tools", "scripts", "governance")
ALWAYS_EXCLUDED: frozenset[str] = frozenset({"tools/lint_import_paths.py"})
ALLOWLIST_PATH_PREFIXES: frozenset[str] = frozenset({"governance/"})
VIOLATION_MESSAGE = (
    "direct governance.* import is forbidden; use runtime.* adapter paths "
    "(see docs/governance/mutation_lifecycle.md)"
)


@dataclass(frozen=True)
class LintIssue:
    path: Path
    line: int
    column: int
    message: str


def _iter_python_files(paths: Sequence[Path]) -> Iterable[Path]:
    for root in paths:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        if not root.exists() or not root.is_dir():
            continue
        for file_path in sorted(root.rglob("*.py")):
            if "__pycache__" in file_path.parts:
                continue
            yield file_path


def _relative_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _is_excluded(path: Path) -> bool:
    return _relative_path(path) in ALWAYS_EXCLUDED


def _is_allowlisted(path: Path) -> bool:
    rel = _relative_path(path)
    return any(rel.startswith(prefix) for prefix in ALLOWLIST_PATH_PREFIXES)


def _is_forbidden_import(module_name: str) -> bool:
    return module_name == "governance" or module_name.startswith("governance.")


def _iter_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    if _is_allowlisted(path):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name):
                    yield LintIssue(
                        path,
                        getattr(node, "lineno", 1),
                        getattr(node, "col_offset", 0),
                        VIOLATION_MESSAGE,
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                continue
            if _is_forbidden_import(node.module):
                yield LintIssue(
                    path,
                    getattr(node, "lineno", 1),
                    getattr(node, "col_offset", 0),
                    VIOLATION_MESSAGE,
                )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    targets = args or list(DEFAULT_TARGETS)
    candidate_paths = [REPO_ROOT / target for target in targets]

    issues: list[LintIssue] = []
    for file_path in _iter_python_files(candidate_paths):
        if _is_excluded(file_path):
            continue
        source = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            issues.append(LintIssue(file_path, exc.lineno or 1, exc.offset or 0, "syntax_error"))
            continue
        issues.extend(_iter_issues(file_path, tree))

    if not issues:
        print("import path lint passed")
        return 0

    for issue in sorted(issues, key=lambda item: (str(item.path), item.line, item.column, item.message)):
        rel = issue.path.relative_to(REPO_ROOT)
        print(f"{rel}:{issue.line}:{issue.column}: {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
