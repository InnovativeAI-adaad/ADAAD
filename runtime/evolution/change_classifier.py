# SPDX-License-Identifier: Apache-2.0
"""Change classification helpers for mutation-cycle orchestration."""

from __future__ import annotations

import ast
import io
import json
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from adaad.agents.path_guard import AgentPathEscapeError, resolve_agent_scoped_path
from runtime.timeutils import now_iso

FUNCTIONAL_NODE_TYPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Return,
    ast.Call,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.BinOp,
    ast.BoolOp,
)
_ALLOWED_METADATA_PATHS = {"/last_mutation", "/mutation_count", "/version"}
_DOCUMENTATION_EXTENSIONS = {".md", ".txt", ".comment"}


@dataclass(frozen=True)
class ChangeDecision:
    classification: str
    run_mutation: bool
    run_fitness: bool
    run_resign: bool
    reason: str


def _parse_ast(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _without_docstrings(tree: ast.AST) -> ast.AST:
    class StripDocstrings(ast.NodeTransformer):
        def _strip(self, node: ast.AST) -> ast.AST:
            body = getattr(node, "body", None)
            if isinstance(body, list) and body:
                head = body[0]
                if isinstance(head, ast.Expr) and isinstance(getattr(head, "value", None), ast.Constant) and isinstance(head.value.value, str):
                    node.body = body[1:]
            return node

        def visit_Module(self, node: ast.Module) -> ast.AST:
            self.generic_visit(node)
            return self._strip(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            self.generic_visit(node)
            return self._strip(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
            self.generic_visit(node)
            return self._strip(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
            self.generic_visit(node)
            return self._strip(node)

    return StripDocstrings().visit(ast.fix_missing_locations(tree))


def _imports(tree: ast.AST) -> set[str]:
    entries: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                entries.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names = ",".join(alias.name for alias in node.names)
            entries.add(f"{node.module or ''}:{node.level}:{names}")
    return entries


def _constants(tree: ast.AST) -> list[str]:
    values: list[str] = []
    stripped_tree = _without_docstrings(tree)
    for node in ast.walk(stripped_tree):
        if isinstance(node, ast.Constant):
            values.append(repr(node.value))
    return sorted(values)


def _functional_nodes(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, FUNCTIONAL_NODE_TYPES):
            names.append(type(node).__name__)
    return sorted(names)


def is_functional_change(old_ast: ast.AST, new_ast: ast.AST) -> bool:
    if _imports(old_ast) != _imports(new_ast):
        return True
    if _constants(old_ast) != _constants(new_ast):
        return True
    if _functional_nodes(old_ast) != _functional_nodes(new_ast):
        return True

    old_dump = ast.dump(_without_docstrings(old_ast), include_attributes=False)
    new_dump = ast.dump(_without_docstrings(new_ast), include_attributes=False)
    return old_dump != new_dump


def _token_kinds(source: str) -> list[int]:
    tokens: list[int] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}:
            continue
        tokens.append(token.type)
    return tokens


def is_doc_change(old_src: str, new_src: str) -> bool:
    old_ast = _parse_ast(old_src)
    new_ast = _parse_ast(new_src)
    if old_ast is None or new_ast is None:
        return False
    old_dump = ast.dump(_without_docstrings(old_ast), include_attributes=False)
    new_dump = ast.dump(_without_docstrings(new_ast), include_attributes=False)
    if old_dump != new_dump:
        return False
    return _token_kinds(old_src) == _token_kinds(new_src)


def classify_mutation_change(agent_path: Path, mutation_request: Mapping[str, Any]) -> ChangeDecision:
    request = dict(mutation_request)
    ops = request.get("ops") or []
    targets = request.get("targets") or []

    if not isinstance(ops, Sequence) or not ops:
        ops = []
    if not isinstance(targets, Sequence) or not targets:
        targets = []
    if not ops and not targets:
        return ChangeDecision("NON_FUNCTIONAL_CHANGE", False, False, False, "no_ops_or_targets")

    if ops and all(isinstance(op, Mapping) and str(op.get("path") or "") in _ALLOWED_METADATA_PATHS for op in ops):
        return ChangeDecision(
            classification="NON_FUNCTIONAL_CHANGE",
            run_mutation=False,
            run_fitness=False,
            run_resign=False,
            reason="allowed_metadata_only",
        )

    def _classify_op(op: Mapping[str, Any], default_file: str = "") -> ChangeDecision | None:
        file_candidate = op.get("file") or op.get("target") or op.get("filepath") or default_file
        path_candidate = str(op.get("path") or "")

        file_name = file_candidate.strip() if isinstance(file_candidate, str) else ""
        ext = ""
        if file_name:
            ext = (agent_path / file_name).suffix.lower()

            in_docs_dir = any(part == "docs" for part in Path(file_name).parts)
            starts_with_comment_marker = Path(file_name).name.startswith("#")
            if ext in _DOCUMENTATION_EXTENSIONS or in_docs_dir or starts_with_comment_marker:
                return None

            if Path(file_name).name == "dna.json" and path_candidate and path_candidate not in _ALLOWED_METADATA_PATHS:
                return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "non_metadata_path_change")

        if not isinstance(file_candidate, str) or not file_candidate.strip():
            if path_candidate and path_candidate not in _ALLOWED_METADATA_PATHS:
                return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "non_metadata_path_change")
            return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "unscoped_change")

        try:
            path = resolve_agent_scoped_path(agent_path, file_name)
        except AgentPathEscapeError:
            return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "path_outside_agent_root")
        if ext == ".py":
            old_src = path.read_text(encoding="utf-8") if path.exists() else ""
            new_src = op.get("content") or op.get("source") or op.get("code") or op.get("value")
            if isinstance(new_src, str) and is_doc_change(old_src, new_src):
                return None
            old_ast = _parse_ast(old_src)
            new_ast = _parse_ast(new_src) if isinstance(new_src, str) else None
            if old_ast is not None and new_ast is not None and not is_functional_change(old_ast, new_ast):
                return None
        return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "ast_or_code_change")

    for op in ops:
        if not isinstance(op, Mapping):
            return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "unknown_op_shape")
        decision = _classify_op(op)
        if decision is not None:
            return decision

    for target in targets:
        if not isinstance(target, Mapping):
            return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "unknown_target_shape")
        target_path = target.get("path")
        target_file = target_path.strip() if isinstance(target_path, str) else ""
        target_ops = target.get("ops")
        if not isinstance(target_ops, Sequence) or not target_ops:
            return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "target_missing_ops")
        for target_op in target_ops:
            if not isinstance(target_op, Mapping):
                return ChangeDecision("FUNCTIONAL_CHANGE", True, True, True, "unknown_target_op_shape")
            decision = _classify_op(target_op, default_file=target_file)
            if decision is not None:
                return decision

    return ChangeDecision("NON_FUNCTIONAL_CHANGE", False, False, False, "documentation_comment_or_metadata_change")


def apply_metadata_updates(agent_path: Path) -> dict[str, Any]:
    dna_path = agent_path / "dna.json"
    payload: dict[str, Any] = {}
    if dna_path.exists():
        try:
            payload = json.loads(dna_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    payload["mutation_count"] = int(payload.get("mutation_count", 0) or 0) + 1
    payload["last_mutation"] = now_iso()
    payload["version"] = int(payload.get("version", 0) or 0) + 1
    dna_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


__all__ = [
    "ChangeDecision",
    "apply_metadata_updates",
    "classify_mutation_change",
    "is_doc_change",
    "is_functional_change",
]
