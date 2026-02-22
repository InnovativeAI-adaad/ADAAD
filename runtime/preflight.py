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

from app.agents.discovery import agent_path_from_id
from app.agents.mutation_request import MutationRequest

from adaad.core.agent_contract import DEFAULT_AGENT_SCOPES, validate_agent_contracts
from adaad.core.tool_contract import DEFAULT_DISCOVERY_SCOPES, validate_tool_contracts

from runtime import ROOT_DIR
from runtime.governance.foundation import default_provider


_FILE_KEYS = ("file", "filepath", "target")
_CONTENT_KEYS = ("content", "source", "code", "value")


_MUTATION_PROPOSAL_SCHEMA_PATH = ROOT_DIR / "schemas" / "llm_mutation_proposal.v1.json"
_RUNTIME_PROFILE_PATH = ROOT_DIR / "governance_runtime_profile.lock.json"


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

    return {"ok": True, "reason": "ok", "checks": checks}


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


def _validate_against_schema(schema: Dict[str, Any], payload: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_schema_type(payload, expected_type):
        return [f"{path}:expected_{expected_type}"]

    if isinstance(payload, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if isinstance(key, str) and key not in payload:
                errors.append(f"{path}.{key}:missing_required")

        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, value in payload.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_validate_against_schema(properties[key], value, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}:additional_property")

    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        item_schema = schema["items"]
        for index, item in enumerate(payload):
            errors.extend(_validate_against_schema(item_schema, item, f"{path}[{index}]"))

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
