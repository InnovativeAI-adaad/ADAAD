#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""AST-based determinism lint for governance-critical runtime paths."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS: tuple[str, ...] = (
    "runtime/governance",
    "runtime/evolution",
    "runtime/autonomy",
    "security",
)

# Direct dynamic execution primitives.
FORBIDDEN_CALLS: tuple[tuple[str, ...], ...] = (
    ("eval",),
    ("exec",),
    ("compile",),
    ("__import__",),
    ("importlib", "import_module"),
)

# Alias-based dynamic import primitives that require import symbol resolution.
FORBIDDEN_IMPORTLIB_SYMBOLS: frozenset[str] = frozenset({"import_module"})

# Entropy enforcement scope (stricter determinism checks).
ENTROPY_ENFORCED_PREFIXES: tuple[str, ...] = (
    "runtime/governance/",
    "runtime/evolution/",
)
ENTROPY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "runtime/governance/foundation/determinism.py",
        "runtime/governance/foundation/clock.py",
    }
)
FORBIDDEN_ENTROPY_IMPORTS: frozenset[str] = frozenset({"random", "secrets"})
FORBIDDEN_ENTROPY_CALLS: tuple[tuple[str, ...], ...] = (
    ("uuid", "uuid4"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("time", "time"),
)

FILESYSTEM_ENFORCED_PREFIXES: tuple[str, ...] = (
    "runtime/governance/",
    "runtime/evolution/",
)
FILESYSTEM_ALLOWLIST_WRAPPERS: frozenset[str] = frozenset(
    {
        "read_file_deterministic",
        "listdir_deterministic",
        "walk_deterministic",
        "glob_deterministic",
        "find_files_deterministic",
    }
)
FORBIDDEN_FILESYSTEM_CALLS: tuple[tuple[str, ...], ...] = (
    ("open",),
    ("os", "listdir"),
    ("os", "walk"),
    ("glob", "glob"),
)
FORBIDDEN_PATH_METHODS: frozenset[str] = frozenset({"read_text", "read_bytes", "open", "glob", "rglob"})


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
            if any(part == "__pycache__" for part in file_path.parts):
                continue
            yield file_path


def _call_path(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return _call_path(node.value) + (node.attr,)
    return ()


def _is_forbidden_call(node: ast.Call) -> bool:
    path = _call_path(node.func)
    if not path:
        return False
    return any(path == forbidden for forbidden in FORBIDDEN_CALLS)


def _collect_aliases(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """Collect import aliases relevant to dynamic import resolution."""
    module_aliases: dict[str, str] = {}
    import_module_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                asname = alias.asname or root
                module_aliases[asname] = root
        elif isinstance(node, ast.ImportFrom):
            if not node.module or node.level > 0:
                continue
            module_root = node.module.split(".", 1)[0]
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if module_root == "importlib" and alias.name in FORBIDDEN_IMPORTLIB_SYMBOLS:
                    import_module_aliases.add(bound_name)
    return module_aliases, import_module_aliases


def _is_alias_forbidden_call(node: ast.Call, module_aliases: dict[str, str], import_module_aliases: set[str]) -> bool:
    path = _call_path(node.func)
    if not path:
        return False

    # from importlib import import_module as im ; im("x")
    if len(path) == 1 and path[0] in import_module_aliases:
        return True

    # import importlib as il ; il.import_module("x")
    if len(path) >= 2:
        head, tail = path[0], path[1:]
        canonical_head = module_aliases.get(head, head)
        if canonical_head == "importlib" and tail == ("import_module",):
            return True

    return False


def _path_as_posix(path: Path) -> str:
    if path.is_absolute() and path.is_relative_to(REPO_ROOT):
        return path.relative_to(REPO_ROOT).as_posix()
    return path.as_posix()


def _is_entropy_enforced(path: Path) -> bool:
    normalized = _path_as_posix(path)
    if normalized in ENTROPY_ALLOWLIST:
        return False
    return any(normalized.endswith(prefix.removesuffix("/")) or f"/{prefix}" in normalized for prefix in ENTROPY_ENFORCED_PREFIXES)


def _iter_entropy_issues(path: Path, tree: ast.AST, module_aliases: dict[str, str]) -> Iterable[LintIssue]:
    if not _is_entropy_enforced(path):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in FORBIDDEN_ENTROPY_IMPORTS:
                    yield LintIssue(path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), "forbidden_entropy_import")
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                continue
            root = node.module.split(".", 1)[0]
            if root in FORBIDDEN_ENTROPY_IMPORTS:
                yield LintIssue(path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), "forbidden_entropy_import")
        elif isinstance(node, ast.Call):
            path_parts = _call_path(node.func)
            if not path_parts:
                continue
            if len(path_parts) >= 2:
                head, tail = path_parts[0], path_parts[1:]
                canonical_head = module_aliases.get(head, head)
                normalized = (canonical_head,) + tail
            else:
                normalized = path_parts
            if any(normalized == forbidden for forbidden in FORBIDDEN_ENTROPY_CALLS):
                yield LintIssue(path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), "forbidden_entropy_source")


def _is_filesystem_enforced(path: Path) -> bool:
    normalized = _path_as_posix(path)
    return any(normalized.endswith(prefix.removesuffix("/")) or f"/{prefix}" in normalized for prefix in FILESYSTEM_ENFORCED_PREFIXES)


def _function_scope_by_line(tree: ast.AST) -> dict[int, str]:
    scope_by_line: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None or end is None:
            continue
        for line in range(start, end + 1):
            scope_by_line.setdefault(line, node.name)
    return scope_by_line


def _is_forbidden_filesystem_call(node: ast.Call, module_aliases: dict[str, str]) -> bool:
    path_parts = _call_path(node.func)
    if not path_parts:
        return False

    normalized = path_parts
    if len(path_parts) >= 2:
        head, tail = path_parts[0], path_parts[1:]
        normalized = (module_aliases.get(head, head),) + tail

    if any(normalized == forbidden for forbidden in FORBIDDEN_FILESYSTEM_CALLS):
        return True

    if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_PATH_METHODS:
        return True

    return False


def _iter_filesystem_issues(path: Path, tree: ast.AST, module_aliases: dict[str, str]) -> Iterable[LintIssue]:
    if not _is_filesystem_enforced(path):
        return

    function_scope_by_line = _function_scope_by_line(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_forbidden_filesystem_call(node, module_aliases):
            continue

        line = getattr(node, "lineno", 1)
        scope_name = function_scope_by_line.get(line)
        if scope_name in FILESYSTEM_ALLOWLIST_WRAPPERS:
            continue

        yield LintIssue(path, line, getattr(node, "col_offset", 0), "forbidden_nondeterministic_filesystem_api")


def _lint_file(path: Path) -> list[LintIssue]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [LintIssue(path, 1, 0, f"read_error:{exc}")]

    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError as exc:
        line = exc.lineno or 1
        col = exc.offset or 0
        return [LintIssue(path, line, col, f"syntax_error:{exc.msg}")]

    module_aliases, import_module_aliases = _collect_aliases(tree)

    issues: list[LintIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_forbidden_call(node) or _is_alias_forbidden_call(node, module_aliases, import_module_aliases):
            line = getattr(node, "lineno", 1)
            col = getattr(node, "col_offset", 0)
            issues.append(LintIssue(path, line, col, "forbidden_dynamic_execution"))

    issues.extend(_iter_entropy_issues(path, tree, module_aliases) or [])
    issues.extend(_iter_filesystem_issues(path, tree, module_aliases) or [])
    return issues


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if args:
        roots = [Path(arg).resolve() for arg in args]
    else:
        roots = [REPO_ROOT / relative for relative in TARGET_DIRS]

    issues: list[LintIssue] = []
    for file_path in _iter_python_files(roots):
        issues.extend(_lint_file(file_path))

    if issues:
        for issue in issues:
            relative = issue.path.relative_to(REPO_ROOT) if issue.path.is_absolute() else issue.path
            print(f"{relative}:{issue.line}:{issue.column}: {issue.message}")
        print(f"determinism lint failed: {len(issues)} issue(s)")
        return 1

    print("determinism lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
