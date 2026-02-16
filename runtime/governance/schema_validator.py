# SPDX-License-Identifier: Apache-2.0
"""Validation helpers for governance JSON schemas.

This module keeps all governance schema validation on a single deterministic path
that does not require optional external dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from runtime import ROOT_DIR
from runtime.governance.deterministic_filesystem import read_file_deterministic

GOVERNANCE_SCHEMA_FILES: tuple[str, ...] = (
    "schemas/mutation_manifest.v1.json",
    "schemas/scoring_input.v1.json",
    "schemas/scoring_result.v1.json",
    "schemas/promotion_policy.v1.json",
    "schemas/checkpoint.v1.json",
    "schemas/manifest.v1.json",
    "schemas/entropy_metadata.v1.json",
    "schemas/entropy_policy.v1.json",
    "schemas/sandbox_manifest.v1.json",
    "schemas/sandbox_policy.v1.json",
    "schemas/sandbox_evidence.v1.json",
    "schemas/evidence_bundle.v1.json",
    "schemas/governance_policy_payload.v1.json",
    "schemas/governance_policy_artifact.v1.json",
    "schemas/replay_attestation.v1.json",
)

_CANONICAL_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_CANONICAL_ID_PREFIX = "https://adaad.local/schemas/"


def _is_valid_url_id(raw_id: object) -> bool:
    if not isinstance(raw_id, str):
        return False
    parsed = urlparse(raw_id)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and bool(parsed.path)


def _validate_schema_document(schema_path: Path) -> list[str]:
    errors: list[str] = []

    try:
        document = json.loads(read_file_deterministic(schema_path))
    except json.JSONDecodeError as exc:
        return [f"invalid_json:{exc.msg}"]

    if not isinstance(document, dict):
        return ["schema_root_not_object"]

    schema_dialect = document.get("$schema")
    if schema_dialect != _CANONICAL_DIALECT:
        errors.append("invalid_schema_dialect")

    schema_id = document.get("$id")
    if not _is_valid_url_id(schema_id):
        errors.append("invalid_schema_id_url")
    else:
        expected_id = f"{_CANONICAL_ID_PREFIX}{schema_path.name}"
        if schema_id != expected_id:
            errors.append("noncanonical_schema_id")

    if document.get("type") != "object":
        errors.append("schema_root_type_not_object")

    if not isinstance(document.get("properties"), dict):
        errors.append("schema_missing_properties_object")

    return errors


def validate_governance_schemas(paths: Iterable[Path] | None = None) -> dict[str, list[str]]:
    """Validate all governance schema files and return errors by relative file path."""
    schema_paths = list(paths) if paths is not None else [ROOT_DIR / path for path in GOVERNANCE_SCHEMA_FILES]
    errors_by_schema: dict[str, list[str]] = {}

    for schema_path in schema_paths:
        path_obj = Path(schema_path)
        rel_key = str(path_obj.relative_to(ROOT_DIR)) if path_obj.is_absolute() else str(path_obj)

        if not path_obj.exists():
            errors_by_schema[rel_key] = ["missing_schema_file"]
            continue

        errors = _validate_schema_document(path_obj)
        if errors:
            errors_by_schema[rel_key] = errors

    return errors_by_schema
