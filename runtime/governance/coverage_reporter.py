# SPDX-License-Identifier: Apache-2.0
"""Coverage artifact helpers for constitutional coverage rule inputs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _extract_percent_covered(raw: Dict[str, Any]) -> float:
    totals = raw.get("totals")
    if isinstance(totals, dict):
        value = totals.get("percent_covered")
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("coverage", "line_coverage", "total", "ratio", "percent"):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    raise ValueError("coverage_percent_missing")


def build_coverage_artifact(raw: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    coverage = _extract_percent_covered(raw)
    return {
        "coverage": coverage,
        "source": source,
        "schema": "coverage_artifact.v1",
    }


def write_coverage_artifact(raw: Dict[str, Any], output_path: Path, *, source: str) -> Dict[str, Any]:
    artifact = build_coverage_artifact(raw, source=source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_canonical_json(artifact), encoding="utf-8")
    return artifact


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("coverage_input_not_object")
    return payload


def configure_coverage_artifact_env(*, baseline_path: Path | None = None, post_path: Path | None = None, environ: dict[str, str] | None = None) -> None:
    target_env = os.environ if environ is None else environ
    if baseline_path is not None:
        target_env["ADAAD_FITNESS_COVERAGE_BASELINE_PATH"] = str(baseline_path)
    if post_path is not None:
        target_env["ADAAD_FITNESS_COVERAGE_POST_PATH"] = str(post_path)


__all__ = [
    "build_coverage_artifact",
    "write_coverage_artifact",
    "load_json",
    "configure_coverage_artifact_env",
]
