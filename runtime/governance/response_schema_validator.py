# SPDX-License-Identifier: Apache-2.0
"""
Module: response_schema_validator
Purpose: Deterministically validate Aponi response payloads against local JSON schema definitions.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: runtime.ROOT_DIR
  - Consumed by: ui.aponi_dashboard response handlers
  - Governance impact: medium — enforces fail-closed schema conformance for governance surfaces
"""

from __future__ import annotations

import json
from typing import Any

from runtime import ROOT_DIR

SCHEMA_ROOT = ROOT_DIR / "schemas" / "aponi_responses"


def _is_type(value: Any, expected: str) -> bool:
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


def _validate(schema: dict[str, Any], payload: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_type(payload, expected_type):
        return [f"{path}:expected_{expected_type}"]

    if "const" in schema and payload != schema["const"]:
        errors.append(f"{path}:const_mismatch")

    enum = schema.get("enum")
    if isinstance(enum, list) and payload not in enum:
        errors.append(f"{path}:enum_mismatch")

    if isinstance(payload, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if isinstance(key, str) and key not in payload:
                errors.append(f"{path}.{key}:missing_required")

        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, value in payload.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_validate(properties[key], value, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}:additional_property")

    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        item_schema = schema["items"]
        for index, item in enumerate(payload):
            errors.extend(_validate(item_schema, item, f"{path}[{index}]"))

    return errors


def validate_response(schema_filename: str, payload: Any) -> list[str]:
    schema_path = SCHEMA_ROOT / schema_filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return _validate(schema, payload)


__all__ = ["validate_response"]
