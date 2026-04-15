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
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set

from runtime.api.agents import agent_path_from_id
from runtime.api.agents import MutationRequest
from adaad.agents.path_guard import AgentPathEscapeError, resolve_agent_scoped_path

from adaad.core.agent_contract import DEFAULT_AGENT_SCOPES, validate_agent_contracts
from adaad.core.tool_contract import DEFAULT_DISCOVERY_SCOPES, validate_tool_contracts

from runtime import ROOT_DIR
from runtime.constitution import CONSTITUTION_VERSION
from runtime.governance.foundation import default_provider


_FILE_KEYS = ("file", "filepath", "target")
_CONTENT_KEYS = ("content", "source", "code", "value")


_MUTATION_PROPOSAL_SCHEMA_PATH = ROOT_DIR / "schemas" / "llm_mutation_proposal.v1.json"
_RUNTIME_PROFILE_PATH = ROOT_DIR / "governance_runtime_profile.lock.json"
_RUNTIME_PROFILE_SCHEMA_PATH = ROOT_DIR / "schemas" / "governance_runtime_profile.lock.v1.json"


_STRICT_GOVERNANCE_MODES = frozenset({"strict", "audit"})


def validate_constitution_version_config(*, expected_version: str | None = None) -> Dict[str, Any]:
    """Validate constitution version pinning against the canonical runtime constant."""
    expected = (expected_version if expected_version is not None else os.getenv("ADAAD_CONSTITUTION_VERSION", "")).strip()
    if not expected:
        expected = CONSTITUTION_VERSION
    if expected != CONSTITUTION_VERSION:
        return {
            "ok": False,
            "reason": f"constitution_version_mismatch:{CONSTITUTION_VERSION}!={expected}",
            "expected": expected,
            "actual": CONSTITUTION_VERSION,
        }
    return {
        "ok": True,
        "reason": "ok",
        "expected": expected,
        "actual": CONSTITUTION_VERSION,
    }


def _legacy_mutation_validation_enabled() -> bool:
    configured = os.getenv("ADAAD_ENABLE_LEGACY_MUTATION_PREFLIGHT")
    if configured is not None:
        return _is_truthy_env(configured)
    env = (os.getenv("ADAAD_ENV") or "").strip().lower()
    replay_mode = (os.getenv("ADAAD_REPLAY_MODE") or "").strip().lower()
    recovery_tier = (os.getenv("ADAAD_RECOVERY_TIER") or "").strip().lower()
    strict_override = _is_truthy_env(os.getenv("ADAAD_GOVERNANCE_STRICT", ""))
    governance_strict = env in {"staging", "production", "prod"} or replay_mode in _STRICT_GOVERNANCE_MODES or recovery_tier in _STRICT_GOVERNANCE_MODES or strict_override
    return not governance_strict


def _is_truthy_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_env(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def _dependency_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_surface_contract(manifest: Mapping[str, Any], key: str) -> Dict[str, Any]:
    section = manifest.get(key)
    if not isinstance(section, Mapping):
        return {"ok": False, "reason": f"runtime_manifest_invalid:{key}"}
    disable_env = str(section.get("disable_env", "")).strip()
    allowlist_env = str(section.get("allowlist_env", "")).strip()
    approved = {str(item) for item in section.get("allowlist", []) if isinstance(item, str)}
    disabled = _is_truthy_env(os.getenv(disable_env, "")) if disable_env else False
    configured = _parse_csv_env(os.getenv(allowlist_env, "")) if allowlist_env else set()
    if disabled:
        return {"ok": True, "status": "disabled", "configured": sorted(configured)}
    if configured and configured.issubset(approved):
        return {"ok": True, "status": "allowlisted", "configured": sorted(configured)}
    return {
        "ok": False,
        "reason": f"{key}_surface_must_be_disabled_or_allowlisted",
        "approved": sorted(approved),
        "configured": sorted(configured),
    }


def validate_boot_runtime_profile(*, replay_mode: str = "off", recovery_tier: str | None = None) -> Dict[str, Any]:
    """Validate hermetic runtime profile required by strict/audit governance modes."""
    normalized_mode = (replay_mode or "off").strip().lower()
    normalized_tier = (recovery_tier or "").strip().lower()
    checks: Dict[str, Any] = {}

    try:
        profile = json.loads(_RUNTIME_PROFILE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": False, "reason": "missing_runtime_profile_lock", "checks": checks}

    migration = migrate_runtime_profile_lock(profile)
    profile = migration["profile"]
    checks["profile_migration"] = migration["migration"]
    try:
        profile_schema = json.loads(_RUNTIME_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ok": False, "reason": "runtime_profile_schema_unavailable", "checks": checks}
    schema_errors = _validate_against_schema(profile_schema, profile)
    if schema_errors:
        checks["runtime_profile_schema_errors"] = schema_errors
        return {"ok": False, "reason": "runtime_profile_schema_invalid", "checks": checks}

    dependency_lock = profile.get("dependency_lock")
    if not isinstance(dependency_lock, Mapping):
        return {"ok": False, "reason": "runtime_profile_missing_dependency_lock", "checks": checks}
    dependency_path = ROOT_DIR / str(dependency_lock.get("path", ""))
    expected_fingerprint = str(dependency_lock.get("sha256", ""))
    if not dependency_path.exists():
        return {"ok": False, "reason": "dependency_lock_target_missing", "checks": checks}
    actual_fingerprint = _dependency_fingerprint(dependency_path)
    dependency_ok = bool(expected_fingerprint) and actual_fingerprint == expected_fingerprint
    checks["dependency_fingerprint"] = {
        "ok": dependency_ok,
        "path": str(dependency_path.relative_to(ROOT_DIR)),
        "expected": expected_fingerprint,
        "actual": actual_fingerprint,
    }
    if not dependency_ok:
        return {"ok": False, "reason": "dependency_fingerprint_mismatch", "checks": checks}

    runtime_manifest = profile.get("runtime_manifest")
    if not isinstance(runtime_manifest, Mapping):
        return {"ok": False, "reason": "runtime_profile_missing_runtime_manifest", "checks": checks}

    governance_modes = {str(item).strip().lower() for item in runtime_manifest.get("governance_modes", []) if isinstance(item, str)}
    governance_mode_active = normalized_mode in governance_modes or normalized_tier in governance_modes
    checks["governance_mode_active"] = governance_mode_active
    if not governance_mode_active:
        return {"ok": True, "reason": "ok", "checks": checks}

    provider = default_provider()
    provider_ok = bool(getattr(provider, "deterministic", False))
    checks["deterministic_provider"] = {
        "ok": provider_ok,
        "provider": type(provider).__name__,
    }
    if not provider_ok:
        return {"ok": False, "reason": "governance_mode_requires_deterministic_provider", "checks": checks}

    filesystem_check = _check_surface_contract(runtime_manifest, "mutable_filesystem")
    checks["mutable_filesystem"] = filesystem_check
    if not filesystem_check.get("ok"):
        return {"ok": False, "reason": filesystem_check.get("reason", "filesystem_surface_violation"), "checks": checks}

    network_check = _check_surface_contract(runtime_manifest, "network")
    checks["network"] = network_check
    if not network_check.get("ok"):
        return {"ok": False, "reason": network_check.get("reason", "network_surface_violation"), "checks": checks}

    agents_block = profile.get("agents", {})
    grok_integrator = agents_block.get("grok-integrator") if isinstance(agents_block, Mapping) else None
    checks["agents"] = {
        "grok_integrator_present": isinstance(grok_integrator, Mapping),
        "grok_integrator_enabled": bool(grok_integrator.get("enabled")) if isinstance(grok_integrator, Mapping) else False,
    }

    return {"ok": True, "reason": "ok", "checks": checks}


def migrate_runtime_profile_lock(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply deterministic in-memory migration for new runtime profile sections."""
    migrated = dict(profile)
    migration: list[str] = []

    agents = migrated.get("agents")
    if not isinstance(agents, Mapping):
        agents = {}
        migration.append("added_agents_section")
    else:
        agents = dict(agents)
    if "grok-integrator" not in agents:
        agents["grok-integrator"] = {
            "enabled": False,
            "provider": "xai",
            "profile": "governance-observer",
            "metadata": {"migration": "schema-aware-default"},
        }
        migration.append("added_agents.grok-integrator")

    migrated["agents"] = agents
    return {"profile": migrated, "migration": migration}


def _is_schema_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _resolve_schema_ref(schema_root: Dict[str, Any], ref: str) -> Dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    node: Any = schema_root
    for part in ref[2:].split("/"):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if isinstance(node, dict) else None


def _validate_against_schema(schema: Dict[str, Any], payload: Any, path: str = "$", schema_root: Dict[str, Any] | None = None) -> list[str]:
    if schema_root is None:
        schema_root = schema
    errors: list[str] = []

    schema_ref = schema.get("$ref")
    if isinstance(schema_ref, str):
        resolved = _resolve_schema_ref(schema_root, schema_ref)
        if resolved is None:
            return [f"{path}:invalid_ref:{schema_ref}"]
        return _validate_against_schema(resolved, payload, path, schema_root=schema_root)

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(isinstance(t, str) and _is_schema_type(payload, t) for t in expected_type):
            return [f"{path}:expected_one_of_{'_'.join(str(x) for x in expected_type)}"]
    elif isinstance(expected_type, str) and not _is_schema_type(payload, expected_type):
        return [f"{path}:expected_{expected_type}"]

    if "const" in schema and payload != schema["const"]:
        errors.append(f"{path}:const_mismatch")

    if isinstance(payload, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(payload) < min_length:
            errors.append(f"{path}:min_length")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            import re
            if re.fullmatch(pattern, payload) is None:
                errors.append(f"{path}:pattern_mismatch")

    if isinstance(payload, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if isinstance(key, str) and key not in payload:
                errors.append(f"{path}.{key}:missing_required")

        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, value in payload.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_validate_against_schema(properties[key], value, f"{path}.{key}", schema_root=schema_root))
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(_validate_against_schema(schema["additionalProperties"], value, f"{path}.{key}", schema_root=schema_root))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}:additional_property")

    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        item_schema = schema["items"]
        for index, item in enumerate(payload):
            errors.extend(_validate_against_schema(item_schema, item, f"{path}[{index}]", schema_root=schema_root))

    return errors


def validate_mutation_proposal_schema(proposal: Mapping[str, Any]) -> Dict[str, Any]:
    schema = json.loads(_MUTATION_PROPOSAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = dict(proposal)
    errors = _validate_against_schema(schema, payload)
    if errors:
        return {"ok": False, "reason": "invalid_mutation_proposal_schema", "errors": errors}
    return {"ok": True, "reason": "ok", "errors": []}


def _extract_targets(request: MutationRequest) -> Set[Path]:
    targets: Set[Path] = set()
    agents_root = ROOT_DIR / "app" / "agents"
    agent_dir = agent_path_from_id(request.agent_id, agents_root)
    if request.targets:
        for target in request.targets:
            if not target.path:
                continue
            path = resolve_agent_scoped_path(agent_dir, target.path)
            targets.add(path)
        if targets:
            return targets
    for op in request.ops:
        if not isinstance(op, dict):
            continue
        for key in _FILE_KEYS:
            value = op.get(key)
            if isinstance(value, str) and value.strip():
                targets.add(resolve_agent_scoped_path(agent_dir, value))
        value = op.get("files")
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    targets.add(resolve_agent_scoped_path(agent_dir, entry))
                if isinstance(entry, dict):
                    for key in _FILE_KEYS:
                        nested = entry.get(key)
                        if isinstance(nested, str) and nested.strip():
                            targets.add(resolve_agent_scoped_path(agent_dir, nested))
    if targets:
        return targets
    return {agent_dir / "dna.json"}


def _extract_source(request: MutationRequest, target: Path) -> Optional[str]:
    agents_root = ROOT_DIR / "app" / "agents"
    agent_dir = agent_path_from_id(request.agent_id, agents_root)
    if request.targets:
        for target_entry in request.targets:
            if not target_entry.ops:
                continue
            candidate = resolve_agent_scoped_path(agent_dir, target_entry.path)
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
                target_value = str(resolve_agent_scoped_path(agent_dir, value))
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
                            nested_target = str(resolve_agent_scoped_path(agent_dir, nested_value))
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

        def _is_optional_import_handler(handler: ast.ExceptHandler) -> bool:
            if handler.type is None:
                return True
            if isinstance(handler.type, ast.Name):
                return handler.type.id in {"ImportError", "ModuleNotFoundError"}
            if isinstance(handler.type, ast.Tuple):
                return any(
                    isinstance(item, ast.Name) and item.id in {"ImportError", "ModuleNotFoundError"}
                    for item in handler.type.elts
                )
            return False

        class _ImportCollector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.hard_imports: Set[str] = set()
                self.optional_imports: Set[str] = set()
                self._optional_depth = 0

            def _record(self, module_name: str) -> None:
                root = module_name.split(".", 1)[0]
                if not root:
                    return
                if self._optional_depth > 0:
                    self.optional_imports.add(root)
                else:
                    self.hard_imports.add(root)

            def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
                for alias in node.names:
                    self._record(alias.name)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
                if node.level > 0 or not node.module:
                    return
                self._record(node.module)

            def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
                has_optional_import_handler = any(_is_optional_import_handler(handler) for handler in node.handlers)
                if has_optional_import_handler:
                    self._optional_depth += 1
                    for stmt in node.body:
                        self.visit(stmt)
                    self._optional_depth -= 1
                    for stmt in node.handlers + node.orelse + node.finalbody:
                        self.visit(stmt)
                    return
                self.generic_visit(node)

        collector = _ImportCollector()
        collector.visit(tree)

        optional_only_imports = collector.optional_imports - collector.hard_imports

        project_root = ROOT_DIR.resolve()

        def _is_local_package_root(module_name: str) -> bool:
            package_dir = project_root / module_name
            if package_dir.is_dir() and (
                (package_dir / "__init__.py").exists() or any(package_dir.glob("*.py"))
            ):
                return True
            return (project_root / f"{module_name}.py").exists()

        stdlib_modules = getattr(sys, "stdlib_module_names", set())
        missing_dependencies: list[str] = []
        optional_dependencies: list[str] = []
        for module_name in sorted(collector.hard_imports):
            if module_name in stdlib_modules:
                continue
            if _is_local_package_root(module_name):
                continue
            if importlib.util.find_spec(module_name) is None:
                missing_dependencies.append(module_name)

        for module_name in sorted(optional_only_imports):
            if module_name in stdlib_modules:
                continue
            if _is_local_package_root(module_name):
                continue
            if importlib.util.find_spec(module_name) is None:
                optional_dependencies.append(module_name)

        if missing_dependencies:
            return {
                "ok": False,
                "reason": f"missing_dependency:{missing_dependencies[0]}",
                "missing_dependency": missing_dependencies,
                "optional_dependency": optional_dependencies,
            }
        return {
            "ok": True,
            "missing_dependency": missing_dependencies,
            "optional_dependency": optional_dependencies,
        }
    except (SyntaxError, ValueError, TypeError, OSError) as exc:  # pragma: no cover - defensive guardrail
        return {
            "ok": False,
            "reason": "import_analysis_failed",
            "reason_code": "import_analysis_failed",
            "operation_class": "governance-critical",
            "context": {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "target": str(target),
            },
        }


def _legacy_validate_mutation(request: MutationRequest) -> Dict[str, Any]:
    try:
        targets = _extract_targets(request)
    except AgentPathEscapeError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "reason_code": exc.reason_code,
            "agent": request.agent_id,
            "targets": [],
            "checks": {},
        }
    result: Dict[str, Any] = {
        "ok": True,
        "reason": "ok",
        "agent": request.agent_id,
        "targets": [str(target) for target in targets],
        "checks": {},
    }
    per_target: Dict[str, Any] = {}
    for target in targets:
        try:
            source = _extract_source(request, target)
        except AgentPathEscapeError as exc:
            result.update({"ok": False, "reason": str(exc), "reason_code": exc.reason_code})
            break
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


def validate_tool_contract_preflight(scopes: Sequence[Path] = DEFAULT_DISCOVERY_SCOPES) -> Dict[str, Any]:
    """Run tool contract checks as part of preflight governance validation."""
    return validate_tool_contracts(ROOT_DIR, scopes=scopes)


def validate_agent_contract_preflight(scopes: Sequence[Path] = DEFAULT_AGENT_SCOPES, *, include_legacy_bridge: bool = True) -> Dict[str, Any]:
    """Run agent contract checks as part of preflight governance validation."""
    return validate_agent_contracts(ROOT_DIR, scopes=scopes, include_legacy_bridge=include_legacy_bridge)


def validate_mutation(request: MutationRequest, tier: Optional[Any] = None) -> Dict[str, Any]:
    """
    Preflight validation - delegates to constitutional evaluation when tier is provided.
    """
    if tier is None:
        if not _legacy_mutation_validation_enabled():
            return {
                "ok": False,
                "reason": "legacy_mutation_preflight_disabled",
                "reason_code": "legacy_mutation_preflight_disabled",
                "operation_class": "governance-critical",
                "context": {"hint": "provide tier or set ADAAD_ENABLE_LEGACY_MUTATION_PREFLIGHT=1"},
            }
        return _legacy_validate_mutation(request)
    from runtime.constitution import evaluate_mutation

    return evaluate_mutation(request, tier)


__all__ = [
    "validate_mutation",
    "validate_tool_contract_preflight",
    "validate_agent_contract_preflight",
    "validate_mutation_proposal_schema",
    "validate_boot_runtime_profile",
]
