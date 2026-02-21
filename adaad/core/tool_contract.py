# SPDX-License-Identifier: Apache-2.0
"""Tool contract discovery and validation helpers."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
DEFAULT_DISCOVERY_SCOPES: Sequence[Path] = (Path("tools"), Path("adaad/tools"))
LEGACY_TOOL_MODULES: Sequence[Path] = (Path("tools/asset_generator.py"),)


@dataclass(frozen=True)
class ContractViolation:
    code: str
    message: str


@dataclass(frozen=True)
class ModuleValidationResult:
    module_path: Path
    violations: List[ContractViolation]

    @property
    def ok(self) -> bool:
        return not self.violations


def discover_tool_modules(root: Path, scopes: Sequence[Path] = DEFAULT_DISCOVERY_SCOPES) -> List[Path]:
    modules: List[Path] = []
    seen: set[Path] = set()

    for legacy in LEGACY_TOOL_MODULES:
        path = root / legacy
        if path.is_file():
            modules.append(legacy)
            seen.add(legacy)

    for scope in scopes:
        base = root / scope
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name.startswith("__"):
                continue
            rel = path.relative_to(root)
            if rel in seen:
                continue
            if rel.parts and rel.parts[0] == "tools" and not path.name.startswith("tool_"):
                continue
            seen.add(rel)
            modules.append(rel)
    return modules


def _load_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _collect_symbols(path: Path) -> tuple[Dict[str, ast.AST], Dict[str, ast.FunctionDef]]:
    tree = _load_ast(path)
    assignments: Dict[str, ast.AST] = {}
    functions: Dict[str, ast.FunctionDef] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments[node.target.id] = node.value if node.value is not None else node
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = node
    return assignments, functions


def _static_validate(path: Path) -> List[ContractViolation]:
    assignments, functions = _collect_symbols(path)

    violations: List[ContractViolation] = []
    if "TOOL_ID" not in assignments:
        violations.append(ContractViolation("missing_symbol", "Missing TOOL_ID"))
    if "VERSION" not in assignments:
        violations.append(ContractViolation("missing_symbol", "Missing VERSION"))
    if "get_tool_manifest" not in functions:
        violations.append(ContractViolation("missing_symbol", "Missing get_tool_manifest"))
    if "run_tool" not in functions:
        violations.append(ContractViolation("missing_symbol", "Missing run_tool"))
    return violations


def _ast_semantic_validate(path: Path) -> List[ContractViolation]:
    assignments, functions = _collect_symbols(path)
    violations: List[ContractViolation] = []

    tool_id_node = assignments.get("TOOL_ID")
    if not isinstance(tool_id_node, ast.Constant) or not isinstance(tool_id_node.value, str) or not tool_id_node.value.strip():
        violations.append(ContractViolation("invalid_type", "TOOL_ID must be a non-empty str"))

    version_node = assignments.get("VERSION")
    if not isinstance(version_node, ast.Constant) or not isinstance(version_node.value, str) or SEMVER_RE.fullmatch(version_node.value) is None:
        violations.append(ContractViolation("invalid_type", "VERSION must be a valid semver string"))

    manifest_fn = functions.get("get_tool_manifest")
    if manifest_fn is None or manifest_fn.args.args:
        violations.append(ContractViolation("signature_mismatch", "get_tool_manifest must have signature ()"))

    run_fn = functions.get("run_tool")
    if run_fn is None:
        violations.append(ContractViolation("signature_mismatch", "run_tool must have signature (params)"))
    else:
        arg_names = [arg.arg for arg in run_fn.args.args]
        if arg_names != ["params"]:
            violations.append(ContractViolation("signature_mismatch", "run_tool must have signature (params)"))

    return violations


def _import_module(path: Path, root: Path):
    module_rel = path.relative_to(root).with_suffix("")
    module_name = "_adaad_tool_contract_" + "_".join(module_rel.parts)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _signature_exactly(func: Any, parameter_names: List[str]) -> bool:
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    if len(params) != len(parameter_names):
        return False
    for param, expected in zip(params, parameter_names):
        if param.name != expected:
            return False
        if param.kind not in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}:
            return False
    return True


def _reflective_validate(path: Path, root: Path) -> List[ContractViolation]:
    violations: List[ContractViolation] = []
    try:
        module = _import_module(path, root)
    except BaseException:
        return []

    tool_id = getattr(module, "TOOL_ID", None)
    if not isinstance(tool_id, str) or not tool_id.strip():
        violations.append(ContractViolation("invalid_type", "TOOL_ID must be a non-empty str"))

    version = getattr(module, "VERSION", None)
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        violations.append(ContractViolation("invalid_type", "VERSION must be a valid semver string"))

    manifest_fn = getattr(module, "get_tool_manifest", None)
    if not callable(manifest_fn):
        violations.append(ContractViolation("invalid_type", "get_tool_manifest must be callable"))
    elif not _signature_exactly(manifest_fn, []):
        violations.append(ContractViolation("signature_mismatch", "get_tool_manifest must have signature ()"))

    run_fn = getattr(module, "run_tool", None)
    if not callable(run_fn):
        violations.append(ContractViolation("invalid_type", "run_tool must be callable"))
    elif not _signature_exactly(run_fn, ["params"]):
        violations.append(ContractViolation("signature_mismatch", "run_tool must have signature (params)"))

    return violations


def validate_tool_module(path: Path, root: Optional[Path] = None) -> ModuleValidationResult:
    resolved = path.resolve()
    root_dir = root.resolve() if root else Path.cwd().resolve()
    violations = _static_validate(resolved)
    if not violations:
        violations = _ast_semantic_validate(resolved)
    if not violations:
        violations = _reflective_validate(resolved, root_dir)
    return ModuleValidationResult(module_path=resolved.relative_to(root_dir), violations=violations)


def validate_tool_contracts(root: Path, scopes: Sequence[Path] = DEFAULT_DISCOVERY_SCOPES) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    failing: List[Dict[str, Any]] = []
    for module in discover_tool_modules(root, scopes=scopes):
        result = validate_tool_module(root / module, root=root)
        payload = {
            "module": str(result.module_path),
            "ok": result.ok,
            "violations": [{"code": item.code, "message": item.message} for item in result.violations],
        }
        results.append(payload)
        if not result.ok:
            failing.append(payload)
    return {
        "ok": not failing,
        "checked_modules": len(results),
        "failing_modules": failing,
        "results": results,
    }


__all__ = [
    "DEFAULT_DISCOVERY_SCOPES",
    "ContractViolation",
    "LEGACY_TOOL_MODULES",
    "ModuleValidationResult",
    "discover_tool_modules",
    "validate_tool_module",
    "validate_tool_contracts",
]
