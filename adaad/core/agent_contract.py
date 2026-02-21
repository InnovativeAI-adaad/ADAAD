# SPDX-License-Identifier: Apache-2.0
"""Agent contract specification and validators for governed agent runtime."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Sequence

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
DEFAULT_AGENT_SCOPES: Sequence[Path] = (Path("adaad/agents"),)
DEFAULT_LEGACY_AGENT_BRIDGE_MODULES: Sequence[Path] = (
    Path("app/agents/sample_agent/__init__.py"),
    Path("app/agents/test_subject/__init__.py"),
)


@dataclass(frozen=True)
class AgentContractViolation:
    code: str
    message: str


@dataclass(frozen=True)
class AgentContractResult:
    module_path: Path
    violations: List[AgentContractViolation]

    @property
    def ok(self) -> bool:
        return not self.violations


def discover_agent_modules(root: Path, scopes: Sequence[Path] = DEFAULT_AGENT_SCOPES) -> List[Path]:
    modules: List[Path] = []
    for scope in scopes:
        base = root / scope
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name.startswith("__"):
                continue
            modules.append(path.relative_to(root))
    return modules


@lru_cache(maxsize=256)
def _parse_cached(path_str: str) -> ast.Module:
    path = Path(path_str)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _parse(path: Path) -> ast.Module:
    return _parse_cached(str(path.resolve()))


def _collect_assignments_and_functions(path: Path) -> tuple[dict[str, ast.AST], dict[str, ast.FunctionDef]]:
    tree = _parse(path)
    assignments: dict[str, ast.AST] = {}
    functions: dict[str, ast.FunctionDef] = {}
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


def _annotation_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id
    return ""


def _is_dict_annotation(node: ast.AST | None) -> bool:
    return _annotation_name(node) in {"dict", "Dict"}


def _is_str_annotation(node: ast.AST | None) -> bool:
    return _annotation_name(node) == "str"


def _is_float_annotation(node: ast.AST | None) -> bool:
    return _annotation_name(node) == "float"


def _validate_required_api(functions: dict[str, ast.FunctionDef], *, bound: bool) -> List[AgentContractViolation]:
    violations: List[AgentContractViolation] = []

    def expected_args(base: list[str]) -> list[str]:
        return (["self"] + base) if bound else base

    info_fn = functions.get("info")
    if info_fn is not None:
        if [arg.arg for arg in info_fn.args.args] != expected_args([]) or not _is_dict_annotation(info_fn.returns):
            violations.append(AgentContractViolation("signature_mismatch", "def info() -> dict:"))
    else:
        violations.append(AgentContractViolation("missing_symbol", "Missing info"))

    run_fn = functions.get("run")
    if run_fn is not None:
        args = [arg.arg for arg in run_fn.args.args]
        if args != expected_args(["input"]):
            violations.append(AgentContractViolation("signature_mismatch", "def run(input=None) -> dict:"))
        if not _is_dict_annotation(run_fn.returns):
            violations.append(AgentContractViolation("signature_mismatch", "def run(input=None) -> dict:"))
    else:
        violations.append(AgentContractViolation("missing_symbol", "Missing run"))

    mutate_fn = functions.get("mutate")
    if mutate_fn is not None:
        args = mutate_fn.args.args
        expected = expected_args(["src"])
        if [arg.arg for arg in args] != expected:
            violations.append(AgentContractViolation("signature_mismatch", "def mutate(src: str) -> str:"))
        else:
            src_arg = args[-1]
            if not _is_str_annotation(src_arg.annotation):
                violations.append(AgentContractViolation("signature_mismatch", "def mutate(src: str) -> str:"))
        if not _is_str_annotation(mutate_fn.returns):
            violations.append(AgentContractViolation("signature_mismatch", "def mutate(src: str) -> str:"))
    else:
        violations.append(AgentContractViolation("missing_symbol", "Missing mutate"))

    score_fn = functions.get("score")
    if score_fn is not None:
        args = score_fn.args.args
        expected = expected_args(["output"])
        if [arg.arg for arg in args] != expected:
            violations.append(AgentContractViolation("signature_mismatch", "def score(output: dict) -> float:"))
        else:
            output_arg = args[-1]
            if not _is_dict_annotation(output_arg.annotation):
                violations.append(AgentContractViolation("signature_mismatch", "def score(output: dict) -> float:"))
        if not _is_float_annotation(score_fn.returns):
            violations.append(AgentContractViolation("signature_mismatch", "def score(output: dict) -> float:"))
    else:
        violations.append(AgentContractViolation("missing_symbol", "Missing score"))

    return violations


def validate_agent_module(path: Path, root: Path) -> AgentContractResult:
    abs_path = (root / path).resolve()
    assignments, functions = _collect_assignments_and_functions(abs_path)
    violations: List[AgentContractViolation] = []

    required_constants = {
        "AGENT_ID": lambda node: isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(node.value.strip()),
        "VERSION": lambda node: isinstance(node, ast.Constant) and isinstance(node.value, str) and SEMVER_RE.fullmatch(node.value) is not None,
        "CAPABILITIES": lambda node: isinstance(node, (ast.List, ast.Tuple)),
        "GOAL_SCHEMA": lambda node: isinstance(node, ast.Dict),
        "OUTPUT_SCHEMA": lambda node: isinstance(node, ast.Dict),
        "SPAWN_POLICY": lambda node: isinstance(node, ast.Dict),
    }
    for name, validator in required_constants.items():
        node = assignments.get(name)
        if node is None:
            violations.append(AgentContractViolation("missing_symbol", f"Missing {name}"))
        elif not validator(node):
            violations.append(AgentContractViolation("invalid_constant", f"Invalid {name}"))

    manifest_fn = functions.get("get_agent_manifest")
    if manifest_fn is None:
        violations.append(AgentContractViolation("missing_symbol", "Missing get_agent_manifest"))
    else:
        if manifest_fn.args.args:
            violations.append(AgentContractViolation("signature_mismatch", "get_agent_manifest must have signature ()"))
        if not _is_dict_annotation(manifest_fn.returns):
            violations.append(AgentContractViolation("signature_mismatch", "get_agent_manifest must return dict"))

    run_goal_fn = functions.get("run_goal")
    if run_goal_fn is None:
        violations.append(AgentContractViolation("missing_symbol", "Missing run_goal"))
    else:
        args = [arg.arg for arg in run_goal_fn.args.args]
        if args != ["goal"]:
            violations.append(AgentContractViolation("signature_mismatch", "run_goal must have signature (goal)"))
        if not _is_dict_annotation(run_goal_fn.returns):
            violations.append(AgentContractViolation("signature_mismatch", "run_goal must return dict"))

    violations.extend(_validate_required_api(functions, bound=False))
    return AgentContractResult(module_path=abs_path.relative_to(root.resolve()), violations=violations)


def validate_legacy_agent_module(path: Path, root: Path) -> AgentContractResult:
    abs_path = (root / path).resolve()
    tree = _parse(abs_path)
    violations: List[AgentContractViolation] = []

    class_nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not class_nodes:
        violations.append(AgentContractViolation("missing_symbol", "Missing agent class"))
        return AgentContractResult(module_path=abs_path.relative_to(root.resolve()), violations=violations)

    target = class_nodes[0]
    methods = {node.name: node for node in target.body if isinstance(node, ast.FunctionDef)}
    violations.extend(_validate_required_api(methods, bound=True))
    return AgentContractResult(module_path=abs_path.relative_to(root.resolve()), violations=violations)


def validate_agent_contracts(
    root: Path,
    scopes: Sequence[Path] = DEFAULT_AGENT_SCOPES,
    *,
    include_legacy_bridge: bool = False,
    legacy_modules: Sequence[Path] = DEFAULT_LEGACY_AGENT_BRIDGE_MODULES,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    failing: List[Dict[str, Any]] = []
    for rel in discover_agent_modules(root, scopes=scopes):
        result = validate_agent_module(rel, root)
        payload = {
            "module": str(result.module_path),
            "ok": result.ok,
            "violations": [{"code": v.code, "message": v.message} for v in result.violations],
        }
        results.append(payload)
        if not result.ok:
            failing.append(payload)

    if include_legacy_bridge:
        for rel in legacy_modules:
            if not (root / rel).exists():
                continue
            result = validate_legacy_agent_module(rel, root)
            payload = {
                "module": str(result.module_path),
                "ok": result.ok,
                "violations": [{"code": v.code, "message": v.message} for v in result.violations],
            }
            results.append(payload)
            if not result.ok:
                failing.append(payload)

    return {"ok": not failing, "checked_modules": len(results), "failing_modules": failing, "results": results}


__all__ = [
    "AgentContractResult",
    "AgentContractViolation",
    "DEFAULT_AGENT_SCOPES",
    "DEFAULT_LEGACY_AGENT_BRIDGE_MODULES",
    "discover_agent_modules",
    "validate_agent_module",
    "validate_legacy_agent_module",
    "validate_agent_contracts",
]
