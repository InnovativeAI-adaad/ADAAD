# SPDX-License-Identifier: Apache-2.0
"""Mutation manifest validation helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from runtime import ROOT_DIR

SCHEMA_PATH = ROOT_DIR / "schemas" / "mutation_manifest.v1.json"

_V1_SCHEMA = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
_TERMINAL_STATUS_ENUM = {"completed", "pruned", "rejected", "failed"}
_STAGE_ORDER = ["proposed", "staged", "certified", "executing", "completed"]


def _is_hex64(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def _is_replay_seed16_nonzero(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 16:
        return False
    if not all(ch in "0123456789abcdefABCDEF" for ch in value):
        return False
    return value.lower() != "0" * 16


def _is_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _major_version(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    major, _, _rest = value.partition(".")
    if not major.isdigit():
        return None
    return int(major)


def _validate_v1_manifest(manifest: Mapping[str, Any], *, strict_version: bool = True) -> list[str]:
    errors: list[str] = []

    required = list(_V1_SCHEMA.get("required") or [])
    for key in required:
        if key not in manifest:
            errors.append(f"missing_required:{key}")

    allowed_keys = set((_V1_SCHEMA.get("properties") or {}).keys())
    unexpected = sorted(key for key in manifest.keys() if key not in allowed_keys)
    for key in unexpected:
        errors.append(f"unexpected_field:{key}")

    if strict_version and manifest.get("manifest_version") != "1.0":
        errors.append("invalid_manifest_version")

    law_version = manifest.get("law_version")
    if not isinstance(law_version, str) or not law_version.strip():
        errors.append("invalid_law_version")

    if not _is_hex64(manifest.get("capability_snapshot_hash")):
        errors.append("invalid_capability_snapshot_hash")
    if not _is_hex64(manifest.get("parent_lineage_hash")):
        errors.append("invalid_parent_lineage_hash")

    mutation_id = manifest.get("mutation_id")
    if not isinstance(mutation_id, str) or not mutation_id.strip():
        errors.append("invalid_mutation_id")
    proposer_identity = manifest.get("proposer_identity")
    if not isinstance(proposer_identity, str) or not proposer_identity.strip():
        errors.append("invalid_proposer_identity")
    target_epoch = manifest.get("target_epoch")
    if not isinstance(target_epoch, str) or not target_epoch.strip():
        errors.append("invalid_target_epoch")

    proposed_at = manifest.get("proposed_at")
    if not _is_utc_timestamp(proposed_at):
        errors.append("invalid_proposed_at")

    timestamps = manifest.get("stage_timestamps")
    parsed_stamps: list[datetime] = []
    if not isinstance(timestamps, dict):
        errors.append("invalid_stage_timestamps")
    else:
        allowed_stages = set(_STAGE_ORDER + ["pruned"])
        for stage in sorted(timestamps.keys()):
            if stage not in allowed_stages:
                errors.append(f"unexpected_stage_timestamp:{stage}")

        for stage in _STAGE_ORDER:
            value = timestamps.get(stage)
            if value is None:
                errors.append(f"missing_stage_timestamp:{stage}")
                continue
            if not _is_utc_timestamp(value):
                errors.append(f"invalid_stage_timestamp_format:{stage}")
                continue
            parsed_stamps.append(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))

        pruned_ts = timestamps.get("pruned")
        if pruned_ts is not None and not _is_utc_timestamp(pruned_ts):
            errors.append("invalid_stage_timestamp_format:pruned")

        if _is_utc_timestamp(proposed_at) and isinstance(timestamps.get("proposed"), str) and proposed_at != timestamps.get("proposed"):
            errors.append("inconsistent_proposed_timestamp")

    if len(parsed_stamps) == len(_STAGE_ORDER):
        for index in range(1, len(parsed_stamps)):
            if parsed_stamps[index] < parsed_stamps[index - 1]:
                errors.append("non_monotonic_stage_timestamps")
                break

    cert_refs = manifest.get("cert_references")
    if not isinstance(cert_refs, dict):
        errors.append("invalid_cert_references")
    else:
        for key, value in cert_refs.items():
            if not isinstance(key, str) or not key:
                errors.append("invalid_cert_reference_key")
                break
            if not isinstance(value, str) or not value.strip():
                errors.append(f"invalid_cert_reference_value:{key}")
        replay_seed = cert_refs.get("replay_seed")
        if replay_seed is not None and not _is_replay_seed16_nonzero(replay_seed):
            errors.append("invalid_replay_seed")

    terminal = manifest.get("terminal_status")
    if terminal not in _TERMINAL_STATUS_ENUM:
        errors.append("invalid_terminal_status")

    fitness = manifest.get("fitness_summary")
    if not isinstance(fitness, dict):
        errors.append("invalid_fitness_summary")
    else:
        for key in ["score", "threshold", "passed"]:
            if key not in fitness:
                errors.append(f"missing_fitness_field:{key}")

        score = fitness.get("score")
        if score is not None and not isinstance(score, (int, float)):
            errors.append("invalid_fitness_score")
        threshold = fitness.get("threshold")
        if not isinstance(threshold, (int, float)):
            errors.append("invalid_fitness_threshold")
        if not isinstance(fitness.get("passed"), bool):
            errors.append("invalid_fitness_passed")

        risk_score = fitness.get("risk_score")
        if risk_score is not None and not isinstance(risk_score, (int, float)):
            errors.append("invalid_fitness_risk_score")

        notes = fitness.get("notes")
        if notes is not None:
            if not isinstance(notes, list) or any(not isinstance(item, str) for item in notes):
                errors.append("invalid_fitness_notes")

        allowed_fitness_keys = {"score", "threshold", "passed", "risk_score", "notes"}
        for key in fitness.keys():
            if key not in allowed_fitness_keys:
                errors.append(f"unexpected_fitness_field:{key}")

    return errors


def _validate_v2_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Placeholder for future v2 constraints.

    For now we keep forward-compatible parsing by validating against v1 structural
    constraints while not requiring an exact version literal.
    """
    return _validate_v1_manifest(manifest, strict_version=False)


def validate_manifest(manifest: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Validate manifest via version-aware validators without external deps."""
    major = _major_version(manifest.get("manifest_version"))
    validators = {
        1: lambda payload: _validate_v1_manifest(payload, strict_version=True),
        2: _validate_v2_manifest,
    }
    if major is None:
        errors = ["invalid_manifest_version"]
    elif major in validators:
        errors = validators[major](manifest)
    elif major > 2:
        errors = _validate_v2_manifest(manifest)
    else:
        errors = ["unsupported_manifest_version"]

    return len(errors) == 0, errors
