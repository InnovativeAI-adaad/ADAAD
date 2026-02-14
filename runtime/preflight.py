# SPDX-License-Identifier: Apache-2.0
"""
Preflight validation for mutation requests.

Validations are intentionally minimal and deterministic:
- Multi-file scope support.
- Python AST parse check (per target).
- Import smoke test (for Python targets, per target).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

from app.agents.discovery import agent_path_from_id
from app.agents.mutation_request import MutationRequest

from runtime import ROOT_DIR


_FILE_KEYS = ("file", "filepath", "target")
_CONTENT_KEYS = ("content", "source", "code", "value")


def _extract_targets(request: MutationRequest) -> Set[Path]:
    targets: Set[Path] = set()
    if request.targets:
        agents_root = ROOT_DIR / "app" / "agents"
        agent_dir = agent_path_from_id(request.agent_id, agents_root)
        for target in request.targets:
            if not target.path:
                continue
            path = Path(target.path)
            if not path.is_absolute():
                path = agent_dir / path
            targets.add(path)
        if targets:
            return targets
    for op in request.ops:
        if not isinstance(op, dict):
            continue
        for key in _FILE_KEYS:
            value = op.get(key)
            if isinstance(value, str) and value.strip():
                targets.add(Path(value))
        value = op.get("files")
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    targets.add(Path(entry))
                if isinstance(entry, dict):
                    for key in _FILE_KEYS:
                        nested = entry.get(key)
                        if isinstance(nested, str) and nested.strip():
                            targets.add(Path(nested))
    if targets:
        return targets
    agents_root = ROOT_DIR / "app" / "agents"
    agent_dir = agent_path_from_id(request.agent_id, agents_root)
    return {agent_dir / "dna.json"}


def _extract_source(request: MutationRequest, target: Path) -> Optional[str]:
    if request.targets:
        for target_entry in request.targets:
            if not target_entry.ops:
                continue
            candidate = Path(target_entry.path)
            if not candidate.is_absolute():
                agents_root = ROOT_DIR / "app" / "agents"
                agent_dir = agent_path_from_id(request.agent_id, agents_root)
                candidate = agent_dir / candidate
            if candidate != target:
                continue
            for op in target_entry.ops:
                if not isinstance(op, dict):
                    continue
                for key in _CONTENT_KEYS:
                    value = op.get(key)
                    if isinstance(value, str):
                        return value
        return None
    for op in request.ops:
        if not isinstance(op, dict):
            continue
        target_value = None
        for key in _FILE_KEYS:
            value = op.get(key)
            if isinstance(value, str):
                target_value = value
                break
        if target_value and Path(target_value) != target:
            continue
        files_value = op.get("files")
        if isinstance(files_value, list):
            for entry in files_value:
                if isinstance(entry, dict):
                    nested_target = None
                    for key in _FILE_KEYS:
                        nested_value = entry.get(key)
                        if isinstance(nested_value, str):
                            nested_target = nested_value
                            break
                    if nested_target and Path(nested_target) != target:
                        continue
                    for key in _CONTENT_KEYS:
                        nested_content = entry.get(key)
                        if isinstance(nested_content, str):
                            return nested_content
        for key in _CONTENT_KEYS:
            value = op.get(key)
            if isinstance(value, str):
                return value
    return None


def _ast_check(target: Path, source: Optional[str]) -> Dict[str, Any]:
    if target.suffix != ".py":
        return {"ok": True, "reason": "not_python"}
    if source is None:
        if not target.exists():
            return {"ok": False, "reason": "missing_target"}
        source = target.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(target))
    except SyntaxError as exc:
        return {"ok": False, "reason": f"syntax_error:{exc.msg}"}
    return {"ok": True}


def _import_smoke_check(target: Path, source: Optional[str]) -> Dict[str, Any]:
    if target.suffix != ".py":
        return {"ok": True, "reason": "not_python"}
    try:
        if source is None:
            if not target.exists():
                return {"ok": False, "reason": "missing_target"}
            source = target.read_text(encoding="utf-8")

        # Baseline: AST parse validates syntax and import statement shape without execution.
        try:
            tree = ast.parse(source, filename=str(target))
        except SyntaxError as exc:
            return {"ok": False, "reason": f"syntax_error:{exc.msg}"}

        imported_roots: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root:
                        imported_roots.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0 or not node.module:
                    continue
                root = node.module.split(".", 1)[0]
                if root:
                    imported_roots.add(root)

        stdlib_modules = getattr(sys, "stdlib_module_names", set())
        for module_name in sorted(imported_roots):
            if module_name in stdlib_modules:
                continue
            if importlib.util.find_spec(module_name) is None:
                return {"ok": False, "reason": f"missing_dependency:{module_name}"}
        return {"ok": True}
    except Exception as exc:  # pragma: no cover - defensive guardrail
        return {"ok": False, "reason": f"import_analysis_failed:{exc}"}


def _legacy_validate_mutation(request: MutationRequest) -> Dict[str, Any]:
    targets = _extract_targets(request)
    result: Dict[str, Any] = {
        "ok": True,
        "reason": "ok",
        "agent": request.agent_id,
        "targets": [str(target) for target in targets],
        "checks": {},
    }
    per_target: Dict[str, Any] = {}
    for target in targets:
        source = _extract_source(request, target)
        ast_result = _ast_check(target, source)
        import_result = _import_smoke_check(target, source)
        per_target[str(target)] = {
            "ast_parse": ast_result,
            "import_smoke": import_result,
        }
        if not ast_result.get("ok"):
            result.update({"ok": False, "reason": ast_result.get("reason", "ast_parse_failed")})
        if not import_result.get("ok"):
            result.update({"ok": False, "reason": import_result.get("reason", "import_smoke_failed")})
    result["checks"]["targets"] = per_target
    return result


def validate_mutation(request: MutationRequest, tier: Optional[Any] = None) -> Dict[str, Any]:
    """
    Preflight validation - delegates to constitutional evaluation when tier is provided.
    """
    if tier is None:
        return _legacy_validate_mutation(request)
    from runtime.constitution import evaluate_mutation

    return evaluate_mutation(request, tier)


__all__ = ["validate_mutation"]
