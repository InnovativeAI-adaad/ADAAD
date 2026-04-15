#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate governance schema corpus + constitution + runtime profile lock payload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.governance.schema_validator import validate_governance_schemas
from runtime.preflight import _validate_against_schema, migrate_runtime_profile_lock

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION_PATH = REPO_ROOT / "runtime/governance/constitution.yaml"
SCHEMA_PATH = REPO_ROOT / "docs/schemas/constitution.v1.json"
RUNTIME_PROFILE_PATH = REPO_ROOT / "governance_runtime_profile.lock.json"
RUNTIME_PROFILE_SCHEMA_PATH = REPO_ROOT / "schemas/governance_runtime_profile.lock.v1.json"


def _validate_node(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, dict):
            return [f"{path}:type_error:expected_object"]
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}:missing_required:{key}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in instance and isinstance(child_schema, dict):
                    errors.extend(_validate_node(instance[key], child_schema, f"{path}.{key}"))
    elif schema_type == "array":
        if not isinstance(instance, list):
            return [f"{path}:type_error:expected_array"]
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(instance):
                errors.extend(_validate_node(item, item_schema, f"{path}[{idx}]"))
    elif schema_type == "string" and not isinstance(instance, str):
        errors.append(f"{path}:type_error:expected_string")
    elif schema_type == "number" and not isinstance(instance, (int, float)):
        errors.append(f"{path}:type_error:expected_number")
    elif schema_type == "integer" and not isinstance(instance, int):
        errors.append(f"{path}:type_error:expected_integer")
    elif schema_type == "boolean" and not isinstance(instance, bool):
        errors.append(f"{path}:type_error:expected_boolean")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and instance not in enum_values:
        errors.append(f"{path}:enum_error")

    return errors


def main() -> int:
    schema_errors = validate_governance_schemas()
    if schema_errors:
        print("governance_schema_corpus_validation:failed")
        for schema_path, errors in sorted(schema_errors.items()):
            print(f"- {schema_path}: {', '.join(errors)}")
        return 1

    try:
        constitution = json.loads(CONSTITUTION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"governance_schema_validation:failed:{exc}")
        return 1

    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"governance_schema_validation:failed:{exc}")
            return 1

        errors = _validate_node(constitution, schema)
        if errors:
            print("governance_schema_validation:failed")
            for error in errors:
                print(f"- {error}")
            return 1
    else:
        print("governance_schema_validation:ok:schema_missing_skipped")

    try:
        runtime_profile = json.loads(RUNTIME_PROFILE_PATH.read_text(encoding="utf-8"))
        runtime_profile_schema = json.loads(RUNTIME_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"governance_runtime_profile_validation:failed:{exc}")
        return 1

    migration = migrate_runtime_profile_lock(runtime_profile)
    runtime_errors = _validate_against_schema(runtime_profile_schema, migration["profile"])
    if runtime_errors:
        print("governance_runtime_profile_validation:failed")
        for error in runtime_errors:
            print(f"- {error}")
        return 1

    print("governance_schema_validation:ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
