# SPDX-License-Identifier: Apache-2.0
"""Deterministic AST snapshot helpers for Beast-mode routing."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class _DocstringStripper(ast.NodeTransformer):
    """Remove docstring-only expression nodes from module/class/function scopes."""

    @staticmethod
    def _strip(nodes: list[ast.stmt]) -> list[ast.stmt]:
        if not nodes:
            return nodes
        first = nodes[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            return nodes[1:]
        return nodes

    def visit_Module(self, node: ast.Module) -> ast.AST:
        node.body = self._strip(node.body)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.body = self._strip(node.body)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.body = self._strip(node.body)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.body = self._strip(node.body)
        self.generic_visit(node)
        return node


@dataclass(frozen=True)
class SnapshotResult:
    """AST digest result for a single target module."""

    target: str
    digest: str


def target_key(agent_id: str, module_path: Path | None, agents_root: Path) -> str:
    """Return deterministic persistence key for an agent module."""
    if module_path is None:
        return f"{agent_id}::unknown"
    rel = module_path.resolve().relative_to(agents_root.resolve()).as_posix()
    return f"{agent_id}::{rel}"


def compute_digest(source: str, *, filename: str = "<memory>") -> str:
    """Compute deterministic digest ignoring comments, whitespace, and docstrings."""
    module = ast.parse(source, filename=filename)
    normalized = _DocstringStripper().visit(module)
    ast.fix_missing_locations(normalized)
    canonical = ast.dump(normalized, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_snapshot(
    *, agent_id: str, module_path: Path | None, agents_root: Path, source: str
) -> SnapshotResult:
    """Build a stable AST snapshot for a target agent/module source payload."""
    return SnapshotResult(
        target=target_key(agent_id, module_path, agents_root),
        digest=compute_digest(source, filename=str(module_path or "<memory>")),
    )


def read_previous_digest(state: dict[str, Any], snapshot_target: str) -> str | None:
    """Read the previously persisted digest for ``snapshot_target``."""
    snapshots = state.get("ast_snapshots")
    if not isinstance(snapshots, dict):
        return None
    previous = snapshots.get(snapshot_target)
    if not isinstance(previous, dict):
        return None
    value = previous.get("digest")
    return value if isinstance(value, str) and value else None


def write_snapshot_state(
    state: dict[str, Any],
    *,
    snapshot_target: str,
    digest: str,
    now: float,
    accepted_change: bool,
) -> None:
    """Persist AST digest + metadata, with cosmetic updates tracked separately."""
    snapshots = state.setdefault("ast_snapshots", {})
    if not isinstance(snapshots, dict):
        snapshots = {}
        state["ast_snapshots"] = snapshots

    previous = snapshots.get(snapshot_target)
    if not isinstance(previous, dict):
        previous = {}

    version = int(previous.get("version", 0))
    if accepted_change:
        version += 1
        snapshots[snapshot_target] = {
            "digest": digest,
            "version": version,
            "updated_at": now,
            "last_outcome": "ast_changed",
        }
        return

    snapshots[snapshot_target] = {
        "digest": previous.get("digest", digest),
        "version": version,
        "updated_at": previous.get("updated_at"),
        "last_outcome": "ast_unchanged",
        "last_cosmetic_update_at": now,
    }


def dump_state(state: dict[str, Any]) -> str:
    """Stable JSON serialization helper for deterministic tests."""
    return json.dumps(state, indent=2, sort_keys=True)
@dataclass(frozen=True)
class ASTSnapshot:
    """Computed AST snapshot for a target module."""

    agent_id: str
    module_id: str
    digest: str


class ASTSnapshotStore:
    """Persists and loads deterministic AST snapshots across beast cycles."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def compute_digest(self, *, source: str, agent_id: str, module_id: str) -> ASTSnapshot:
        """Compute a deterministic digest after removing docstring-only noise."""
        normalized_tree = ast.parse(source)
        _strip_docstrings(normalized_tree)
        normalized_dump = ast.dump(normalized_tree, include_attributes=False)
        payload = f"{agent_id}::{module_id}::{normalized_dump}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return ASTSnapshot(agent_id=agent_id, module_id=module_id, digest=digest)

    def read_previous_digest(self, *, agent_id: str, module_id: str) -> str | None:
        state = self._load_state()
        return (
            state.get("agents", {})
            .get(agent_id, {})
            .get("modules", {})
            .get(module_id, {})
            .get("ast_digest")
        )

    def record_cosmetic_update(self, *, agent_id: str, module_id: str, observed_at: float) -> None:
        state = self._load_state()
        module_state = self._ensure_module_state(state, agent_id=agent_id, module_id=module_id)
        module_state["metadata_version"] = int(module_state.get("metadata_version", 0)) + 1
        module_state["last_metadata_update_ts"] = observed_at
        self._save_state(state)

    def record_accepted_ast_change(
        self,
        *,
        agent_id: str,
        module_id: str,
        digest: str,
        accepted_at: float,
    ) -> None:
        state = self._load_state()
        module_state = self._ensure_module_state(state, agent_id=agent_id, module_id=module_id)
        module_state["ast_digest"] = digest
        module_state["ast_version"] = int(module_state.get("ast_version", 0)) + 1
        module_state["last_ast_change_ts"] = accepted_at
        self._save_state(state)

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"agents": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"agents": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _ensure_module_state(state: dict[str, Any], *, agent_id: str, module_id: str) -> dict[str, Any]:
        agents = state.setdefault("agents", {})
        agent_state = agents.setdefault(agent_id, {})
        modules = agent_state.setdefault("modules", {})
        return modules.setdefault(module_id, {})


def _strip_docstrings(node: ast.AST) -> None:
    body = getattr(node, "body", None)
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
            if isinstance(first.value.value, str):
                del body[0]
    for child in ast.iter_child_nodes(node):
        _strip_docstrings(child)
