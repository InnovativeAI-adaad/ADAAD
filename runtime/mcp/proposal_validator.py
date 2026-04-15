# SPDX-License-Identifier: Apache-2.0
"""Validation for incoming MCP mutation proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from runtime.api.agents import MutationRequest
from runtime.constitution import Tier
from runtime.governance.decision_pipeline import evaluate_mutation_decision
from runtime.preflight import migrate_runtime_profile_lock

# Backward-compatible alias for tests and existing patch points.
evaluate_mutation = evaluate_mutation_decision

SCHEMA_PATH = Path("schemas/llm_mutation_proposal.v1.json")
RUNTIME_PROFILE_PATH = Path("governance_runtime_profile.lock.json")
TIER0_PATH_PREFIXES = ("runtime/", "security/")
TIER0_EXACT_PATHS = {"app/main.py", "app/mutation_executor.py", "runtime/constitution.py"}
_GROK_AGENT_IDS = frozenset({"grok-integrator", "grok-proposal-agent"})


class ProposalValidationError(ValueError):
    def __init__(self, status_code: int, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def _load_schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _matches_schema_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate_schema_subset(payload: Any, schema: Dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _matches_schema_type(payload, expected_type):
        return [f"{path}:expected_{expected_type}"]

    if isinstance(payload, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for field in required:
            if isinstance(field, str) and field not in payload:
                errors.append(f"{path}.{field}:missing_required")

        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, value in payload.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_validate_schema_subset(value, properties[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}:additional_property")

    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        for idx, item in enumerate(payload):
            errors.extend(_validate_schema_subset(item, schema["items"], f"{path}[{idx}]"))

    min_length = schema.get("minLength")
    if isinstance(min_length, int) and isinstance(payload, str) and len(payload) < min_length:
        errors.append(f"{path}:min_length")

    return errors


def _validate_schema(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    errors = _validate_schema_subset(payload, schema)
    if errors:
        raise ProposalValidationError(400, "schema_validation_failed", ";".join(errors))


def _is_tier0_path(path: str) -> bool:
    normalized = str(path or "").strip()
    if normalized in TIER0_EXACT_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in TIER0_PATH_PREFIXES)


def _resolve_grok_vault_path(vault_ref: str) -> Path:
    candidate = Path(vault_ref)
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def _validate_grok_binding(payload: Dict[str, Any]) -> None:
    agent_id = str(payload.get("agent_id") or "").strip().lower()
    if agent_id not in _GROK_AGENT_IDS:
        return

    if not RUNTIME_PROFILE_PATH.exists():
        raise ProposalValidationError(503, "grok_runtime_profile_missing", "runtime profile lock unavailable")

    try:
        profile = json.loads(RUNTIME_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalValidationError(503, "grok_runtime_profile_unreadable", type(exc).__name__) from exc

    migrated = migrate_runtime_profile_lock(profile)["profile"]
    agents = migrated.get("agents") if isinstance(migrated.get("agents"), dict) else {}
    grok = agents.get("grok-integrator") if isinstance(agents, dict) else None
    if not isinstance(grok, dict) or not bool(grok.get("enabled")):
        raise ProposalValidationError(403, "grok_disabled", "grok-integrator is disabled in governance runtime profile")

    metadata = grok.get("metadata") if isinstance(grok.get("metadata"), dict) else {}
    vault_file = str(metadata.get("vault_file") or "").strip()
    if not vault_file:
        raise ProposalValidationError(403, "grok_unbound", "vault_file metadata is required when grok-integrator is enabled")

    if not _resolve_grok_vault_path(vault_file).exists():
        raise ProposalValidationError(403, "grok_unbound", f"vault_file_missing:{vault_file}")


def validate_proposal(raw_payload: Dict[str, Any]) -> Tuple[MutationRequest, Dict[str, Any]]:
    schema = _load_schema()

    # 1. schema validation
    _validate_schema(raw_payload, schema)

    payload = dict(raw_payload)
    _validate_grok_binding(payload)

    # 2. unconditional authority override
    payload["authority_level"] = "governor-review"

    # 3. Tier-0 path check
    elevation_token = str(payload.get("elevation_token") or "").strip()
    for target in payload.get("targets") or []:
        if _is_tier0_path(str((target or {}).get("path") or "")) and not elevation_token:
            raise ProposalValidationError(403, "tier0_escalation_required", "human elevation_token required")

    request = MutationRequest.from_dict(payload)

    # 4. constitutional pre-check
    verdict = evaluate_mutation(request, Tier.STABLE)
    if not verdict.get("passed", False):
        blocking = [v for v in verdict.get("verdicts", []) if str(v.get("severity", "")).lower() == "blocking" and not v.get("ok", False)]
        if blocking:
            raise ProposalValidationError(422, "pre_check_failed", json.dumps(verdict.get("verdicts", []), sort_keys=True))

    # 5. return tuple
    return request, verdict


__all__ = ["ProposalValidationError", "validate_proposal"]
