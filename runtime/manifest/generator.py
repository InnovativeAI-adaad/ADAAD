# SPDX-License-Identifier: Apache-2.0
"""Mutation manifest generation helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from runtime import ROOT_DIR
from runtime.founders_law import LAW_VERSION
from runtime.mutation_lifecycle import MutationLifecycleContext
from runtime.timeutils import now_iso

from .validator import validate_manifest

EMPTY_SHA = hashlib.sha256(b"").hexdigest()
MANIFEST_VERSION = "1.0"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _capability_snapshot_hash() -> str:
    cap_path = ROOT_DIR / "data" / "capabilities.json"
    if not cap_path.exists():
        return EMPTY_SHA
    return _sha256_hex(cap_path.read_bytes())


def _parent_lineage_hash(context: MutationLifecycleContext) -> str:
    value = context.metadata.get("parent_lineage_hash")
    if isinstance(value, str) and len(value) == 64:
        return value
    lineage_blob = json.dumps(context.metadata.get("lineage", {}), sort_keys=True).encode("utf-8")
    if lineage_blob == b"{}":
        return EMPTY_SHA
    return _sha256_hex(lineage_blob)


def _cert_references(context: MutationLifecycleContext) -> Dict[str, str]:
    refs: Dict[str, str] = {}
    for key, value in dict(context.cert_refs).items():
        if isinstance(key, str) and key and isinstance(value, str) and value.strip():
            refs[key] = value
    return refs


def generate_manifest(context: MutationLifecycleContext, terminal_status: str, risk_score: float | None = None) -> Dict[str, Any]:
    stage_timestamps = dict(context.stage_timestamps)
    stage_timestamps.setdefault("proposed", now_iso())
    stage_timestamps.setdefault("staged", stage_timestamps["proposed"])
    stage_timestamps.setdefault("certified", stage_timestamps.get("staged", now_iso()))
    stage_timestamps.setdefault("executing", stage_timestamps.get("certified", now_iso()))
    stage_timestamps.setdefault("completed", stage_timestamps.get("executing", now_iso()))

    manifest: Dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "law_version": LAW_VERSION,
        "capability_snapshot_hash": _capability_snapshot_hash(),
        "mutation_id": context.mutation_id,
        "parent_lineage_hash": _parent_lineage_hash(context),
        "proposed_at": stage_timestamps["proposed"],
        "proposer_identity": context.agent_id,
        "target_epoch": context.epoch_id,
        "stage_timestamps": stage_timestamps,
        "cert_references": _cert_references(context),
        "fitness_summary": {
            "score": context.fitness_score,
            "threshold": context.fitness_threshold,
            "passed": (context.fitness_score or 0.0) >= context.fitness_threshold,
            "risk_score": risk_score,
            "notes": [],
        },
        "terminal_status": terminal_status,
    }
    ok, errors = validate_manifest(manifest)
    if not ok:
        raise ValueError("manifest_validation_failed:" + ",".join(errors))
    return manifest


def manifest_hash(manifest: Dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_hex(canonical)


def write_manifest(path: Path, manifest: Dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"sha256:{manifest_hash(manifest)}"
