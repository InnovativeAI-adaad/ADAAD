# SPDX-License-Identifier: Apache-2.0
"""Deterministic evidence bundle exports for Aponi forensic endpoints."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List

from runtime import ROOT_DIR
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.foundation import ZERO_HASH, canonical_json, sha256_prefixed_digest
from runtime.governance.policy_artifact import DEFAULT_GOVERNANCE_POLICY_PATH, load_governance_policy
from runtime.sandbox.evidence import SANDBOX_EVIDENCE_PATH

FORENSIC_EXPORT_DIR = ROOT_DIR / "reports" / "forensics"
EVIDENCE_BUNDLE_SCHEMA_VERSION = "1.0"
DEFAULT_EXPORT_SIGNING_ALGORITHM = "hmac-sha256"
DEFAULT_RETENTION_DAYS = 365
DEFAULT_ACCESS_SCOPE = "governance_audit"


class EvidenceBundleError(RuntimeError):
    """Raised when deterministic forensic bundle export fails."""


def _resolve_export_signing_secret(key_id: str) -> str:
    env_specific = os.getenv(f"ADAAD_EVIDENCE_BUNDLE_KEY_{key_id.upper().replace('-', '_')}", "").strip()
    if env_specific:
        return env_specific
    generic = os.getenv("ADAAD_EVIDENCE_BUNDLE_SIGNING_KEY", "").strip()
    if generic:
        return generic
    return f"adaad-evidence-bundle-dev-secret:{key_id}"


def _signature_material(secret: str, signed_digest: str) -> str:
    return "sha256:" + sha256(f"{secret}:{signed_digest}".encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line_no, line in enumerate(read_file_deterministic(path).splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:  # fail-closed parse semantics
            raise EvidenceBundleError(f"invalid_jsonl:{path}:{line_no}:{exc.msg}") from exc
        if not isinstance(payload, dict):
            raise EvidenceBundleError(f"invalid_jsonl_entry:{path}:{line_no}:expected_object")
        entries.append(payload)
    return entries


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _validate_schema_subset(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    errors: List[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and _json_type_name(instance) != expected_type:
        return [f"{path}:expected_{expected_type}:got_{_json_type_name(instance)}"]

    if expected_type == "object":
        if not isinstance(instance, dict):
            return [f"{path}:not_object"]
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append(f"{path}.{key}:missing_required")
        properties = schema.get("properties") or {}
        for key, value in instance.items():
            if key in properties:
                errors.extend(_validate_schema_subset(value, properties[key], f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra_keys = sorted(set(instance.keys()) - set(properties.keys()))
            for key in extra_keys:
                errors.append(f"{path}.{key}:additional_property")

    if expected_type == "array":
        if not isinstance(instance, list):
            return [f"{path}:not_array"]
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, value in enumerate(instance):
                errors.extend(_validate_schema_subset(value, item_schema, f"{path}[{idx}]"))

    return errors


class EvidenceBundleBuilder:
    def __init__(
        self,
        *,
        ledger: LineageLedgerV2 | None = None,
        replay_engine: ReplayEngine | None = None,
        sandbox_evidence_path: Path | None = None,
        policy_path: Path = DEFAULT_GOVERNANCE_POLICY_PATH,
        export_dir: Path | None = None,
        schema_path: Path | None = None,
    ) -> None:
        self.ledger = ledger or LineageLedgerV2()
        self.replay_engine = replay_engine or ReplayEngine(self.ledger)
        self.sandbox_evidence_path = sandbox_evidence_path or SANDBOX_EVIDENCE_PATH
        self.policy_path = policy_path
        self.export_dir = export_dir or FORENSIC_EXPORT_DIR
        self.schema_path = schema_path or (ROOT_DIR / "schemas" / "evidence_bundle.v1.json")

    def _resolve_epoch_ids(self, epoch_start: str, epoch_end: str | None = None) -> List[str]:
        requested_start = epoch_start.strip()
        requested_end = (epoch_end or epoch_start).strip()
        if not requested_start:
            raise EvidenceBundleError("missing_epoch_start")
        if not requested_end:
            raise EvidenceBundleError("missing_epoch_end")

        known_epochs = self.ledger.list_epoch_ids()
        if requested_start not in known_epochs:
            raise EvidenceBundleError("epoch_start_not_found")
        if requested_end not in known_epochs:
            raise EvidenceBundleError("epoch_end_not_found")

        start_idx = known_epochs.index(requested_start)
        end_idx = known_epochs.index(requested_end)
        low = min(start_idx, end_idx)
        high = max(start_idx, end_idx)
        return sorted(known_epochs[low : high + 1])

    def _collect_bundle_events(self, epoch_ids: List[str]) -> List[Dict[str, Any]]:
        bundles: List[Dict[str, Any]] = []
        for epoch_id in epoch_ids:
            for entry in self.ledger.read_epoch(epoch_id):
                if entry.get("type") != "MutationBundleEvent":
                    continue
                payload = dict(entry.get("payload") or {})
                bundles.append(
                    {
                        "epoch_id": epoch_id,
                        "bundle_id": str(payload.get("bundle_id") or payload.get("certificate", {}).get("bundle_id") or ""),
                        "bundle_digest": str(payload.get("bundle_digest") or ""),
                        "epoch_digest": str(payload.get("epoch_digest") or ""),
                        "risk_tier": str(payload.get("risk_tier") or ""),
                        "certificate": dict(payload.get("certificate") or {}),
                    }
                )
        bundles.sort(key=lambda item: (item["epoch_id"], item["bundle_id"], item["bundle_digest"]))
        return bundles

    def _collect_sandbox_evidence(self, epoch_ids: List[str]) -> List[Dict[str, Any]]:
        allowed = set(epoch_ids)
        evidence: List[Dict[str, Any]] = []
        for entry in _read_jsonl(self.sandbox_evidence_path):
            payload = dict(entry.get("payload") or {})
            manifest = dict(payload.get("manifest") or {})
            epoch_id = str(manifest.get("epoch_id") or payload.get("epoch_id") or "")
            if epoch_id not in allowed:
                continue
            evidence.append(
                {
                    "epoch_id": epoch_id,
                    "bundle_id": str(manifest.get("bundle_id") or payload.get("bundle_id") or ""),
                    "evidence_hash": str(payload.get("evidence_hash") or ""),
                    "manifest_hash": str(payload.get("manifest_hash") or ""),
                    "policy_hash": str(payload.get("policy_hash") or ""),
                    "entry_hash": str(entry.get("hash") or ""),
                    "prev_hash": str(entry.get("prev_hash") or ZERO_HASH),
                }
            )
        evidence.sort(key=lambda item: (item["epoch_id"], item["bundle_id"], item["entry_hash"]))
        return evidence

    def _collect_replay_proofs(self, epoch_ids: List[str]) -> List[Dict[str, Any]]:
        proofs: List[Dict[str, Any]] = []
        for epoch_id in epoch_ids:
            replay = self.replay_engine.replay_epoch(epoch_id)
            proofs.append(
                {
                    "epoch_id": epoch_id,
                    "digest": str(replay.get("digest") or ""),
                    "canonical_digest": str(replay.get("canonical_digest") or ""),
                    "event_count": int(replay.get("events") or 0),
                    "sandbox_replay": list(replay.get("sandbox_replay") or []),
                }
            )
        proofs.sort(key=lambda item: item["epoch_id"])
        return proofs

    def _collect_lineage_anchors(self, epoch_ids: List[str], bundles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        anchors: List[Dict[str, Any]] = []
        for epoch_id in epoch_ids:
            epoch_bundle_ids = sorted({entry["bundle_id"] for entry in bundles if entry["epoch_id"] == epoch_id and entry["bundle_id"]})
            anchors.append(
                {
                    "epoch_id": epoch_id,
                    "expected_epoch_digest": str(self.ledger.get_expected_epoch_digest(epoch_id) or ""),
                    "incremental_epoch_digest": str(self.ledger.compute_incremental_epoch_digest(epoch_id)),
                    "bundle_ids": epoch_bundle_ids,
                }
            )
        return anchors

    def _build_core(self, epoch_start: str, epoch_end: str | None) -> Dict[str, Any]:
        epoch_ids = self._resolve_epoch_ids(epoch_start=epoch_start, epoch_end=epoch_end)
        bundles = self._collect_bundle_events(epoch_ids)
        sandbox_evidence = self._collect_sandbox_evidence(epoch_ids)
        replay_proofs = self._collect_replay_proofs(epoch_ids)
        lineage_anchors = self._collect_lineage_anchors(epoch_ids, bundles)
        policy = load_governance_policy(self.policy_path)
        policy_artifact_metadata = {
            "path": str(self.policy_path),
            "schema_version": policy.schema_version,
            "fingerprint": policy.fingerprint,
            "model": {"name": policy.model.name, "version": policy.model.version},
            "thresholds": {
                "determinism_pass": policy.thresholds.determinism_pass,
                "determinism_warn": policy.thresholds.determinism_warn,
            },
        }
        return {
            "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "export_scope": {
                "epoch_start": epoch_ids[0],
                "epoch_end": epoch_ids[-1],
                "epoch_ids": epoch_ids,
            },
            "replay_proofs": replay_proofs,
            "sandbox_evidence": sandbox_evidence,
            "policy_artifact_metadata": policy_artifact_metadata,
            "risk_summaries": {
                "bundle_count": len(bundles),
                "sandbox_evidence_count": len(sandbox_evidence),
                "replay_proof_count": len(replay_proofs),
                "high_risk_bundle_count": len([b for b in bundles if b.get("risk_tier") in {"high", "critical"}]),
            },
            "lineage_anchors": lineage_anchors,
            "bundle_index": bundles,
        }

    def _export_metadata(self, *, bundle_id: str, digest: str) -> Dict[str, Any]:
        key_id = os.getenv("ADAAD_EVIDENCE_BUNDLE_KEY_ID", "forensics-dev").strip() or "forensics-dev"
        algorithm = os.getenv("ADAAD_EVIDENCE_BUNDLE_SIGNING_ALGO", DEFAULT_EXPORT_SIGNING_ALGORITHM).strip()
        signed_digest = digest
        signature = _signature_material(_resolve_export_signing_secret(key_id), signed_digest)
        return {
            "digest": digest,
            "canonical_ordering": "json_sort_keys",
            "immutable": True,
            "path": str(self.export_dir / f"{bundle_id}.json"),
            "retention_days": int(os.getenv("ADAAD_FORENSIC_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)) or DEFAULT_RETENTION_DAYS),
            "access_scope": os.getenv("ADAAD_FORENSIC_EXPORT_SCOPE", DEFAULT_ACCESS_SCOPE).strip() or DEFAULT_ACCESS_SCOPE,
            "signer": {
                "key_id": key_id,
                "algorithm": algorithm,
                "signed_digest": signed_digest,
                "signature": signature,
            },
        }

    def build_bundle(self, *, epoch_start: str, epoch_end: str | None = None, persist: bool = True) -> Dict[str, Any]:
        core = self._build_core(epoch_start=epoch_start, epoch_end=epoch_end)
        digest = sha256_prefixed_digest(core)
        bundle_id = f"evidence-{digest.split(':', 1)[1][:16]}"
        bundle = dict(core)
        bundle["bundle_id"] = bundle_id
        bundle["export_metadata"] = self._export_metadata(bundle_id=bundle_id, digest=digest)

        validation_errors = self.validate_bundle(bundle)
        if validation_errors:
            raise EvidenceBundleError("invalid_bundle:" + "|".join(validation_errors))

        if persist:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            export_path = self.export_dir / f"{bundle_id}.json"
            serialized = canonical_json(bundle)
            if export_path.exists():
                current = read_file_deterministic(export_path)
                if current != serialized:
                    raise EvidenceBundleError("immutable_export_mismatch")
            else:
                export_path.write_text(serialized, encoding="utf-8")
        return bundle

    def validate_bundle(self, bundle: Dict[str, Any]) -> List[str]:
        if not self.schema_path.exists():
            raise EvidenceBundleError(f"missing_schema:{self.schema_path}")
        try:
            schema = json.loads(read_file_deterministic(self.schema_path))
        except json.JSONDecodeError as exc:
            raise EvidenceBundleError(f"invalid_schema_json:{self.schema_path}:{exc.msg}") from exc
        return _validate_schema_subset(bundle, schema)


__all__ = [
    "DEFAULT_ACCESS_SCOPE",
    "DEFAULT_EXPORT_SIGNING_ALGORITHM",
    "DEFAULT_RETENTION_DAYS",
    "EVIDENCE_BUNDLE_SCHEMA_VERSION",
    "FORENSIC_EXPORT_DIR",
    "EvidenceBundleBuilder",
    "EvidenceBundleError",
]
