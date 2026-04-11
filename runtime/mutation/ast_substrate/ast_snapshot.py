# SPDX-License-Identifier: Apache-2.0
"""Deterministic AST snapshot helpers for Beast-mode routing."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
