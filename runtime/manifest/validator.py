# SPDX-License-Identifier: Apache-2.0
"""Mutation manifest validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from runtime import ROOT_DIR

SCHEMA_PATH = ROOT_DIR / "schemas" / "mutation_manifest.v1.json"


def _is_hex64(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def validate_manifest(manifest: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Validate manifest against required schema constraints without external deps."""
    schema = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
    required = list(schema.get("required") or [])
    errors: list[str] = []
    for key in required:
        if key not in manifest:
            errors.append(f"missing_required:{key}")

    if manifest.get("manifest_version") != "1.0":
        errors.append("invalid_manifest_version")
    if not _is_hex64(manifest.get("capability_snapshot_hash")):
        errors.append("invalid_capability_snapshot_hash")
    if not _is_hex64(manifest.get("parent_lineage_hash")):
        errors.append("invalid_parent_lineage_hash")

    timestamps = manifest.get("stage_timestamps")
    if not isinstance(timestamps, dict):
        errors.append("invalid_stage_timestamps")
    else:
        for key in ["proposed", "staged", "certified", "executing", "completed"]:
            if key not in timestamps:
                errors.append(f"missing_stage_timestamp:{key}")

    terminal = manifest.get("terminal_status")
    if terminal not in {"completed", "pruned", "rejected", "failed"}:
        errors.append("invalid_terminal_status")

    fitness = manifest.get("fitness_summary")
    if not isinstance(fitness, dict):
        errors.append("invalid_fitness_summary")
    else:
        for key in ["score", "threshold", "passed"]:
            if key not in fitness:
                errors.append(f"missing_fitness_field:{key}")

    return len(errors) == 0, errors
