# SPDX-License-Identifier: Apache-2.0
"""
Preflight validation for mutation requests.

Validations are intentionally minimal and deterministic:
- Single-file scope enforcement.
- Python AST parse check.
- Import smoke test (for Python targets).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

from app.agents.discovery import agent_path_from_id
from app.agents.mutation_request import MutationRequest

from runtime import ROOT_DIR


_FILE_KEYS = ("file", "filepath", "target")
_CONTENT_KEYS = ("content", "source", "code", "value")


def _extract_targets(request: MutationRequest) -> Set[Path]:
    targets: Set[Path] = set()
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
    if targets:
        return targets
    agents_root = ROOT_DIR / "app" / "agents"
    agent_dir = agent_path_from_id(request.agent_id, agents_root)
    return {agent_dir / "dna.json"}


def _extract_source(request: MutationRequest, target: Path) -> Optional[str]:
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
        if source is not None:
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_path = Path(tmpdir) / target.name
                temp_path.write_text(source, encoding="utf-8")
                return _import_smoke_check(temp_path, None)
        if not target.exists():
            return {"ok": False, "reason": "missing_target"}
        module_name = f"mutation_preflight_{target.stem}"
        spec = importlib.util.spec_from_file_location(module_name, target)
        if spec is None or spec.loader is None:
            return {"ok": False, "reason": "import_spec_failed"}
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)
        return {"ok": True}
    except Exception as exc:  # pragma: no cover - defensive guardrail
        return {"ok": False, "reason": f"import_failed:{exc}"}


def _legacy_validate_mutation(request: MutationRequest) -> Dict[str, Any]:
    targets = _extract_targets(request)
    result: Dict[str, Any] = {
        "ok": True,
        "reason": "ok",
        "agent": request.agent_id,
        "targets": [str(target) for target in targets],
        "checks": {},
    }
    if len(targets) != 1:
        result.update({"ok": False, "reason": "multi_file_mutation"})
        result["checks"]["single_file"] = False
        return result
    result["checks"]["single_file"] = True
    target = next(iter(targets))
    source = _extract_source(request, target)

    ast_result = _ast_check(target, source)
    result["checks"]["ast_parse"] = ast_result
    if not ast_result.get("ok"):
        result.update({"ok": False, "reason": "ast_parse_failed"})
        return result

    import_result = _import_smoke_check(target, source)
    result["checks"]["import_smoke"] = import_result
    if not import_result.get("ok"):
        result.update({"ok": False, "reason": "import_smoke_failed"})
        return result

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
