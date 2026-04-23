#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enforce canonical runtime import paths in production code."""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS: tuple[str, ...] = ("app", "runtime", "adaad", "security", "ui", "tools", "scripts", "governance")
ALWAYS_EXCLUDED: frozenset[str] = frozenset({"tools/lint_import_paths.py"})
# Prefix-based exclusions MUST end with "/" for segment-safe matching.
ALWAYS_EXCLUDED_PREFIXES: frozenset[str] = frozenset()
ALLOWLIST_PATH_PREFIXES: frozenset[str] = frozenset({"governance/"})

# M-01: Inline suppression token. A line ending with this comment suppresses
# the import-boundary violation on that specific line. The <reason> field is
# mandatory and is captured in the suppression audit log.
# Format: # adaad: import-boundary-ok:<reason>
_INLINE_SUPPRESSION_PREFIX = "# adaad: import-boundary-ok:"
VIOLATION_MESSAGE = (
    "direct governance.* import is forbidden; use runtime.* adapter paths "
    "(see docs/governance/mutation_lifecycle.md)"
)
GOVERNANCE_IMPL_VIOLATION_MESSAGE = (
    "implementation code detected in governance/ adapter layer; "
    "move logic to runtime.* and re-export from governance/ "
    "(see docs/governance/mutation_lifecycle.md)"
)
GOVERNANCE_IMPL_ALLOWED_ASSIGNMENTS: frozenset[str] = frozenset({"__all__", "__version__", "__author__"})
LAYER_BOUNDARY_VIOLATION_MESSAGE = "forbidden cross-layer import; see docs/ARCHITECTURE_CONTRACT.md"
ARCHIVE_IMPORT_VIOLATION_MESSAGE = "imports from archives/ are forbidden"
RUNTIME_APP_IMPORT_VIOLATION_MESSAGE = "runtime/* must not import app/* (except runtime/api facade modules)"
APP_RUNTIME_INTERNAL_VIOLATION_MESSAGE = "app/* must import runtime only via runtime.api facade"
LEGACY_AGENT_NAMESPACE_VIOLATION_MESSAGE = "import app.agents.* is deprecated; use adaad.agents.* canonical namespace"
DUPLICATE_AGENT_NAMESPACE_VIOLATION_MESSAGE = "duplicate agent namespace usage detected; keep a single canonical namespace (adaad.agents)"
DEPRECATED_IMPORT_VIOLATION_MESSAGE = "deprecated import path used; migrate to canonical import surface"

DEPRECATED_IMPORT_PATHS: tuple[tuple[str, str], ...] = (
    ("app.root", "adaad.core.root"),
    ("app.orchestration", "adaad.orchestrator"),
    ("app.api.governance", "adaad.api.governance"),
    ("app.api.schemas", "adaad.api.schemas"),
)

LAYER_IMPORT_BOUNDARIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Directory scopes MUST end with "/" so prefix checks remain segment-safe.
    # Orchestrator wiring must stay app/UI-agnostic.
    ("adaad/orchestrator/", ("app", "ui", "runtime.integrations", "runtime.platform")),
    # Pure execution engine must not depend on entrypoints/UI.
    ("app/mutation_executor.py", ("app.main", "ui")),
    # Runtime package root remains a stable adapter surface only.
    ("runtime/__init__.py", ("app", "adaad.orchestrator", "ui")),
)



_RULE_MAP: dict[str, str] = {
    VIOLATION_MESSAGE: "governance_direct_import",
    GOVERNANCE_IMPL_VIOLATION_MESSAGE: "governance_impl_leak",
    LAYER_BOUNDARY_VIOLATION_MESSAGE: "layer_boundary_violation",
    ARCHIVE_IMPORT_VIOLATION_MESSAGE: "archive_import_violation",
    RUNTIME_APP_IMPORT_VIOLATION_MESSAGE: "runtime_imports_app_violation",
    APP_RUNTIME_INTERNAL_VIOLATION_MESSAGE: "app_runtime_internal_violation",
    LEGACY_AGENT_NAMESPACE_VIOLATION_MESSAGE: "legacy_agent_namespace_violation",
    DUPLICATE_AGENT_NAMESPACE_VIOLATION_MESSAGE: "duplicate_agent_namespace_violation",
    DEPRECATED_IMPORT_VIOLATION_MESSAGE: "deprecated_import_path_violation",
    "syntax_error": "syntax_error",
}


def _classify_rule(message: str) -> str:
    """Map violation message text to stable programmatic rule identifiers."""

    return _RULE_MAP.get(message, "unknown")


def _validate_boundary_table() -> None:
    """Validate layer boundary table shape before lint execution."""

    for scope, forbidden in LAYER_IMPORT_BOUNDARIES:
        if not scope.endswith("/") and not scope.endswith(".py"):
            raise ValueError(
                f"LAYER_IMPORT_BOUNDARIES: scope {scope!r} must end with '/' (directory) "
                "or '.py' (file). See docs/ARCHITECTURE_CONTRACT.md."
            )
        if not forbidden:
            raise ValueError(
                f"LAYER_IMPORT_BOUNDARIES: scope {scope!r} has an empty forbidden-prefix tuple. "
                "Add forbidden prefixes or remove the rule."
            )


_validate_boundary_table()


def _matches_forbidden_prefix(module_name: str, forbidden_prefixes: tuple[str, ...]) -> bool:
    return any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in forbidden_prefixes)


def _resolve_relative_module(path: Path, node: ast.ImportFrom) -> str:
    """Resolve a relative ImportFrom node to an absolute dotted module path."""

    rel = _relative_path(path)
    package_parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    base_parts = package_parts[:-1]

    level = max(int(node.level or 0), 0)
    if level > 1:
        ascend = level - 1
        if ascend > len(base_parts):
            return ""
        base_parts = base_parts[:-ascend]

    module_parts = node.module.split(".") if node.module else []
    return ".".join([*base_parts, *module_parts])


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
    rel = _relative_path(path)
    return rel in ALWAYS_EXCLUDED or any(rel.startswith(prefix) for prefix in ALWAYS_EXCLUDED_PREFIXES)


def _is_allowlisted(path: Path) -> bool:
    rel = _relative_path(path)
    return any(rel.startswith(prefix) for prefix in ALLOWLIST_PATH_PREFIXES)


def _is_suppressed(path: Path, line_number: int) -> tuple[bool, str]:
    """M-01: Check whether a specific line carries an inline suppression token.

    Returns ``(suppressed, reason)`` where *reason* is the text after the
    suppression prefix. An empty or missing reason is not accepted — the
    suppression is treated as invalid and the violation is reported anyway.

    This allows per-line opt-outs with an auditable reason string, rather than
    blanket file-level allowlisting.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if 1 <= line_number <= len(lines):
            line = lines[line_number - 1]
            idx = line.find(_INLINE_SUPPRESSION_PREFIX)
            if idx != -1:
                reason = line[idx + len(_INLINE_SUPPRESSION_PREFIX):].strip()
                if reason:
                    return True, reason
    except OSError:
        pass
    return False, ""


def _is_forbidden_import(module_name: str) -> bool:
    return module_name == "governance" or module_name.startswith("governance.")


def _iter_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    if _is_allowlisted(path):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "archives" or alias.name.startswith("archives."):
                    yield LintIssue(path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), ARCHIVE_IMPORT_VIOLATION_MESSAGE)
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
            if node.module == "archives" or node.module.startswith("archives."):
                yield LintIssue(path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), ARCHIVE_IMPORT_VIOLATION_MESSAGE)
            if _is_forbidden_import(node.module):
                yield LintIssue(
                    path,
                    getattr(node, "lineno", 1),
                    getattr(node, "col_offset", 0),
                    VIOLATION_MESSAGE,
                )


def _iter_governance_impl_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    rel = _relative_path(path)
    if not rel.startswith("governance/"):
        return

    module = tree if isinstance(tree, ast.Module) else None
    if module is None:
        return

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield LintIssue(
                path,
                getattr(node, "lineno", 1),
                getattr(node, "col_offset", 0),
                GOVERNANCE_IMPL_VIOLATION_MESSAGE,
            )
        elif isinstance(node, ast.Assign):
            target_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if not target_names or not target_names.issubset(GOVERNANCE_IMPL_ALLOWED_ASSIGNMENTS):
                yield LintIssue(
                    path,
                    getattr(node, "lineno", 1),
                    getattr(node, "col_offset", 0),
                    GOVERNANCE_IMPL_VIOLATION_MESSAGE,
                )
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.target.id not in GOVERNANCE_IMPL_ALLOWED_ASSIGNMENTS:
                yield LintIssue(
                    path,
                    getattr(node, "lineno", 1),
                    getattr(node, "col_offset", 0),
                    GOVERNANCE_IMPL_VIOLATION_MESSAGE,
                )


def _iter_layer_boundary_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    rel = _relative_path(path)
    forbidden_prefixes: tuple[str, ...] = ()
    for scope, forbidden in LAYER_IMPORT_BOUNDARIES:
        # rel == scope handles exact file rules (e.g. app/mutation_executor.py)
        # rel.startswith(scope) handles directory rules (e.g. adaad/orchestrator/)
        if rel == scope or rel.startswith(scope):
            forbidden_prefixes = forbidden
            break

    if not forbidden_prefixes:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_forbidden_prefix(alias.name, forbidden_prefixes):
                    yield LintIssue(path, node.lineno, node.col_offset, LAYER_BOUNDARY_VIOLATION_MESSAGE)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and not node.module:
                continue
            module_name = _resolve_relative_module(path, node) if node.level > 0 else (node.module or "")
            if module_name and _matches_forbidden_prefix(module_name, forbidden_prefixes):
                yield LintIssue(path, node.lineno, node.col_offset, LAYER_BOUNDARY_VIOLATION_MESSAGE)


def _iter_runtime_app_boundary_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    rel = _relative_path(path)
    if not rel.startswith("runtime/") or rel.startswith("runtime/api/"):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    yield LintIssue(path, node.lineno, node.col_offset, RUNTIME_APP_IMPORT_VIOLATION_MESSAGE)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue
            module_name = node.module or ""
            if module_name == "app" or module_name.startswith("app."):
                yield LintIssue(path, node.lineno, node.col_offset, RUNTIME_APP_IMPORT_VIOLATION_MESSAGE)




def _iter_agent_namespace_drift_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    rel = _relative_path(path)
    if rel.startswith("app/agents/"):
        return

    has_app_agents = False
    has_adaad_agents = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "app.agents" or name.startswith("app.agents."):
                    has_app_agents = True
                    yield LintIssue(path, node.lineno, node.col_offset, LEGACY_AGENT_NAMESPACE_VIOLATION_MESSAGE)
                if name == "adaad.agents" or name.startswith("adaad.agents."):
                    has_adaad_agents = True
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue
            module_name = node.module or ""
            if module_name == "app.agents" or module_name.startswith("app.agents."):
                has_app_agents = True
                yield LintIssue(path, node.lineno, node.col_offset, LEGACY_AGENT_NAMESPACE_VIOLATION_MESSAGE)
            if module_name == "adaad.agents" or module_name.startswith("adaad.agents."):
                has_adaad_agents = True

    if has_app_agents and has_adaad_agents:
        yield LintIssue(path, 1, 0, DUPLICATE_AGENT_NAMESPACE_VIOLATION_MESSAGE)


def _iter_deprecated_import_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    rel = _relative_path(path)
    if (
        rel.startswith("app/agents/")
        or rel.startswith("app/orchestration/")
        or rel == "app/root.py"
        or rel == "app/api/governance.py"
        or rel.startswith("app/api/schemas/")
    ):
        return

    deprecated_prefixes = tuple(prefix for prefix, _ in DEPRECATED_IMPORT_PATHS)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_forbidden_prefix(alias.name, deprecated_prefixes):
                    yield LintIssue(path, node.lineno, node.col_offset, DEPRECATED_IMPORT_VIOLATION_MESSAGE)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue
            module_name = node.module or ""
            if module_name and _matches_forbidden_prefix(module_name, deprecated_prefixes):
                yield LintIssue(path, node.lineno, node.col_offset, DEPRECATED_IMPORT_VIOLATION_MESSAGE)

def _iter_app_runtime_facade_issues(path: Path, tree: ast.AST) -> Iterable[LintIssue]:
    rel = _relative_path(path)
    if not rel.startswith("app/"):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "runtime" or alias.name.startswith("runtime."):
                    if not (alias.name == "runtime.api" or alias.name.startswith("runtime.api.")):
                        yield LintIssue(path, node.lineno, node.col_offset, APP_RUNTIME_INTERNAL_VIOLATION_MESSAGE)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue
            module_name = node.module or ""
            if module_name == "runtime" or module_name.startswith("runtime."):
                if not (module_name == "runtime.api" or module_name.startswith("runtime.api.")):
                    yield LintIssue(path, node.lineno, node.col_offset, APP_RUNTIME_INTERNAL_VIOLATION_MESSAGE)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    output_format = "text"
    fix_mode = False
    show_suppressed = False

    if "--format=json" in args:
        args.remove("--format=json")
        output_format = "json"
    if "--fix" in args:
        # M-01: --fix mode appends the inline suppression token to flagged lines.
        # This is a convenience tool for bulk suppression of known-good violations;
        # each suppressed line still requires a reason token to be added manually.
        args.remove("--fix")
        fix_mode = True
    if "--show-suppressed" in args:
        args.remove("--show-suppressed")
        show_suppressed = True

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
        issues.extend(_iter_governance_impl_issues(file_path, tree))
        issues.extend(_iter_layer_boundary_issues(file_path, tree))
        issues.extend(_iter_runtime_app_boundary_issues(file_path, tree))
        issues.extend(_iter_app_runtime_facade_issues(file_path, tree))
        issues.extend(_iter_agent_namespace_drift_issues(file_path, tree))
        issues.extend(_iter_deprecated_import_issues(file_path, tree))

    # M-01: Filter out issues that have a valid inline suppression token.
    suppressed: list[tuple[LintIssue, str]] = []
    active_issues: list[LintIssue] = []
    for issue in issues:
        is_sup, reason = _is_suppressed(issue.path, issue.line)
        if is_sup:
            suppressed.append((issue, reason))
        else:
            active_issues.append(issue)

    sorted_issues = sorted(active_issues, key=lambda item: (str(item.path), item.line, item.column, item.message))

    # M-01: --fix mode: annotate first violation per line with suppression stub.
    if fix_mode and sorted_issues:
        seen_lines: set[tuple[Path, int]] = set()
        for issue in sorted_issues:
            key = (issue.path, issue.line)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            lines = issue.path.read_text(encoding="utf-8").splitlines(keepends=True)
            if 1 <= issue.line <= len(lines):
                original = lines[issue.line - 1].rstrip("\n").rstrip("\r")
                stub = f"{original}  {_INLINE_SUPPRESSION_PREFIX}<reason-required>\n"
                lines[issue.line - 1] = stub
                issue.path.write_text("".join(lines), encoding="utf-8")
        print(f"[fix] Annotated {len(seen_lines)} line(s) with suppression stubs. "
              f"Replace '<reason-required>' with a specific rationale before committing.")
        return 1  # still exit 1 — reasons must be filled in before violations clear

    if output_format == "json":
        result: dict = {
            "passed": not sorted_issues,
            "issue_count": len(sorted_issues),
            "suppressed_count": len(suppressed),
            "issues": [
                {
                    "path": issue.path.relative_to(REPO_ROOT).as_posix(),
                    "line": issue.line,
                    "column": issue.column,
                    "message": issue.message,
                    "rule": _classify_rule(issue.message),
                }
                for issue in sorted_issues
            ],
        }
        if show_suppressed:
            result["suppressed"] = [
                {
                    "path": issue.path.relative_to(REPO_ROOT).as_posix(),
                    "line": issue.line,
                    "reason": reason,
                }
                for issue, reason in suppressed
            ]
        print(json.dumps(result, indent=2))
        return 1 if sorted_issues else 0

    if not sorted_issues:
        sup_note = f" ({len(suppressed)} suppressed)" if suppressed else ""
        print(f"import path lint passed{sup_note}")
        return 0

    for issue in sorted_issues:
        rel = issue.path.relative_to(REPO_ROOT)
        print(f"{rel}:{issue.line}:{issue.column}: {issue.message}")

    if show_suppressed and suppressed:
        print(f"\n[suppressed — {len(suppressed)} inline suppressions active]")
        for issue, reason in suppressed:
            rel = issue.path.relative_to(REPO_ROOT)
            print(f"  {rel}:{issue.line}: {reason}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
