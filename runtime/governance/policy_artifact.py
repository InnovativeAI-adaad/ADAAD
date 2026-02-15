# SPDX-License-Identifier: Apache-2.0
"""Deterministic loader/validator for the governance policy artifact."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.governance.foundation import sha256_prefixed_digest

DEFAULT_GOVERNANCE_POLICY_PATH = Path(__file__).resolve().parents[2] / "governance" / "governance_policy_v1.json"


class GovernancePolicyError(ValueError):
    """Raised when a governance policy artifact is missing or invalid."""


@dataclass(frozen=True)
class GovernanceThresholds:
    determinism_pass: float
    determinism_warn: float


@dataclass(frozen=True)
class GovernanceModelMetadata:
    name: str
    version: str


@dataclass(frozen=True)
class GovernancePolicy:
    schema_version: str
    model: GovernanceModelMetadata
    determinism_window: int
    mutation_rate_window_sec: int
    thresholds: GovernanceThresholds
    fingerprint: str


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GovernancePolicyError(f"{field_name} must be an object")
    return value


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernancePolicyError(f"{field_name} must be a non-empty string")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GovernancePolicyError(f"{field_name} must be an integer")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GovernancePolicyError(f"{field_name} must be a number")
    return float(value)


def load_governance_policy(path: Path = DEFAULT_GOVERNANCE_POLICY_PATH) -> GovernancePolicy:
    if not path.exists():
        raise GovernancePolicyError(f"governance policy not found at {path}")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GovernancePolicyError(f"invalid JSON in governance policy: {exc}") from exc

    root = _require_mapping(artifact, "root")
    schema_version = _require_str(root.get("schema_version"), "schema_version")

    model_obj = _require_mapping(root.get("model"), "model")
    model = GovernanceModelMetadata(
        name=_require_str(model_obj.get("name"), "model.name"),
        version=_require_str(model_obj.get("version"), "model.version"),
    )

    thresholds_obj = _require_mapping(root.get("thresholds"), "thresholds")
    thresholds = GovernanceThresholds(
        determinism_pass=_require_number(thresholds_obj.get("determinism_pass"), "thresholds.determinism_pass"),
        determinism_warn=_require_number(thresholds_obj.get("determinism_warn"), "thresholds.determinism_warn"),
    )
    if thresholds.determinism_warn > thresholds.determinism_pass:
        raise GovernancePolicyError("thresholds.determinism_warn must be <= thresholds.determinism_pass")

    determinism_window = _require_int(root.get("determinism_window"), "determinism_window")
    mutation_rate_window_sec = _require_int(root.get("mutation_rate_window_sec"), "mutation_rate_window_sec")
    if determinism_window <= 0:
        raise GovernancePolicyError("determinism_window must be > 0")
    if mutation_rate_window_sec <= 0:
        raise GovernancePolicyError("mutation_rate_window_sec must be > 0")

    return GovernancePolicy(
        schema_version=schema_version,
        model=model,
        determinism_window=determinism_window,
        mutation_rate_window_sec=mutation_rate_window_sec,
        thresholds=thresholds,
        fingerprint=sha256_prefixed_digest(root),
    )


__all__ = [
    "DEFAULT_GOVERNANCE_POLICY_PATH",
    "GovernanceModelMetadata",
    "GovernancePolicy",
    "GovernancePolicyError",
    "GovernanceThresholds",
    "load_governance_policy",
]
