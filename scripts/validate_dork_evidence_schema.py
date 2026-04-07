#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate Dork evidence artifacts against the versioned schema contract."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = REPO_ROOT / "data" / "proposal_capture.jsonl"
SCHEMA_PATH = REPO_ROOT / "schemas" / "dork_evidence.v1.json"
SUPPORTED_SCHEMA_VERSIONS = {"dork-evidence-v1"}
SOURCE_PATH_ENUM = {"provider_adapter", "proposal_orchestrator"}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_iso8601_utc(ts: str) -> bool:
    if not isinstance(ts, str) or not ts.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(ts[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_dork_evidence_artifact(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    version = payload.get("evidence_schema_version")
    if not isinstance(version, str) or not version:
        return ["missing_required:evidence_schema_version"]
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        return [f"unknown_evidence_schema_version:{version}"]

    artifact_id = payload.get("artifact_id")
    if not isinstance(artifact_id, str) or not _UUID_RE.fullmatch(artifact_id):
        errors.append("invalid_format:artifact_id_uuid")

    generated_at = payload.get("generated_at", payload.get("ts"))
    if not isinstance(generated_at, str) or not _validate_iso8601_utc(generated_at):
        errors.append("invalid_format:generated_at_iso8601_utc")

    source_path = payload.get("source_path")
    if source_path not in SOURCE_PATH_ENUM:
        errors.append(f"invalid_enum:source_path:{source_path}")

    provider = payload.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        errors.append("invalid_format:provider_nonempty")

    provider_ok = payload.get("provider_ok")
    if not isinstance(provider_ok, bool):
        errors.append("invalid_type:provider_ok_boolean")

    prompt_hash = payload.get("prompt_hash")
    if not isinstance(prompt_hash, str) or not _SHA256_RE.fullmatch(prompt_hash):
        errors.append("invalid_format:prompt_hash_sha256")

    response_hash = payload.get("response_hash")
    if not isinstance(response_hash, str) or not _SHA256_RE.fullmatch(response_hash):
        errors.append("invalid_format:response_hash_sha256")

    return errors


def _iter_artifacts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix == ".jsonl":
        artifacts: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                row = line.strip()
                if not row:
                    continue
                artifacts.append(json.loads(row))
        return artifacts
    payload = _load_json(path)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH, help="Artifact file path (.json or .jsonl)")
    args = parser.parse_args()

    if not SCHEMA_PATH.exists():
        print(f"dork_evidence_schema_validation:failed:missing_schema:{SCHEMA_PATH}")
        return 1

    try:
        artifacts = _iter_artifacts(args.path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"dork_evidence_schema_validation:failed:{exc}")
        return 1

    if not artifacts:
        print(f"dork_evidence_schema_validation:ok:no_artifacts:{args.path}")
        return 0

    failed = False
    for idx, artifact in enumerate(artifacts):
        errors = validate_dork_evidence_artifact(artifact)
        if errors:
            failed = True
            print(f"dork_evidence_schema_validation:item_failed:index={idx}")
            for error in errors:
                print(f"- {error}")

    if failed:
        print("dork_evidence_schema_validation:failed")
        return 1

    print(f"dork_evidence_schema_validation:ok:count={len(artifacts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
