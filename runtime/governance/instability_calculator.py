# SPDX-License-Identifier: Apache-2.0
"""
Module: instability_calculator
Purpose: Load deterministic instability/alert weighting configuration from governance policy artifacts.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: runtime.governance.policy_artifact
  - Consumed by: ui.aponi_dashboard risk and alert computation paths
  - Governance impact: medium — drives policy-defined instability thresholds and weighting behavior
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.governance.policy_artifact import DEFAULT_GOVERNANCE_POLICY_PATH, GovernancePolicyError


@dataclass(frozen=True)
class InstabilityPolicy:
    instability_weights: dict[str, float]
    drift_class_weights: dict[str, float]
    velocity_spike_threshold: float
    wilson_z_95: float
    alert_thresholds: dict[str, float | bool]


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GovernancePolicyError(f"{field_name} must be an object")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GovernancePolicyError(f"{field_name} must be a number")
    return float(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise GovernancePolicyError(f"{field_name} must be a boolean")
    return value


def load_instability_policy(path: Path = DEFAULT_GOVERNANCE_POLICY_PATH) -> InstabilityPolicy:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GovernancePolicyError(f"unable to read governance policy: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GovernancePolicyError(f"invalid JSON in governance policy: {exc}") from exc

    payload = _require_mapping(artifact.get("payload"), "payload")
    risk = _require_mapping(payload.get("risk"), "payload.risk")

    instability_weights_obj = _require_mapping(risk.get("instability_weights"), "payload.risk.instability_weights")
    drift_class_weights_obj = _require_mapping(risk.get("drift_class_weights"), "payload.risk.drift_class_weights")
    alerts_obj = _require_mapping(risk.get("alerts_thresholds"), "payload.risk.alerts_thresholds")

    instability_weights = {str(k): _require_number(v, f"payload.risk.instability_weights.{k}") for k, v in instability_weights_obj.items()}
    drift_class_weights = {str(k): _require_number(v, f"payload.risk.drift_class_weights.{k}") for k, v in drift_class_weights_obj.items()}

    alert_thresholds: dict[str, float | bool] = {}
    for key, value in alerts_obj.items():
        if key == "velocity_spike":
            alert_thresholds[key] = _require_bool(value, "payload.risk.alerts_thresholds.velocity_spike")
        else:
            alert_thresholds[key] = _require_number(value, f"payload.risk.alerts_thresholds.{key}")

    return InstabilityPolicy(
        instability_weights=instability_weights,
        drift_class_weights=drift_class_weights,
        velocity_spike_threshold=_require_number(risk.get("velocity_spike_threshold"), "payload.risk.velocity_spike_threshold"),
        wilson_z_95=_require_number(risk.get("wilson_z_95"), "payload.risk.wilson_z_95"),
        alert_thresholds=alert_thresholds,
    )


__all__ = ["InstabilityPolicy", "load_instability_policy"]
