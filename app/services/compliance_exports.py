from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any


COMPLIANCE_EXPORT_DATASETS: frozenset[str] = frozenset(
    {
        "control-evidence-snapshots",
        "immutable-replay-attestations",
        "policy-change-history",
        "incident-remediation-logs",
    }
)


def jsonable_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def render_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys: list[str] = sorted({key for row in rows for key in row.keys()})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=keys)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: jsonable_scalar(row.get(key)) for key in keys})
    return buffer.getvalue()


def load_replay_attestations(*, replay_proofs_dir: Path) -> list[dict[str, Any]]:
    attestations: list[dict[str, Any]] = []
    if not replay_proofs_dir.exists():
        return attestations
    for proof_file in sorted(replay_proofs_dir.glob("*.replay_attestation.v1.json")):
        try:
            bundle = json.loads(proof_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        attestations.append(
            {
                "epoch_id": str(bundle.get("epoch_id") or proof_file.name.split(".", 1)[0]),
                "proof_digest": str(bundle.get("proof_digest", "")),
                "canonical_digest": str(bundle.get("canonical_digest", "")),
                "checkpoint_chain_digest": str(bundle.get("checkpoint_chain_digest", "")),
                "replay_digest": str(bundle.get("replay_digest", "")),
                "signature_count": len(bundle.get("signatures", [])) if isinstance(bundle.get("signatures"), list) else 0,
                "source_path": str(proof_file),
            }
        )
    return attestations


def load_policy_change_history(*, root: Path, journal_module: Any) -> list[dict[str, Any]]:
    entries = journal_module.read_entries(limit=1000)
    filtered: list[dict[str, Any]] = []
    for item in entries:
        tx_type = str(item.get("tx_type", ""))
        payload = item.get("payload", {})
        reason = ""
        if isinstance(payload, dict):
            reason = str(payload.get("reason_code") or payload.get("reason") or "")
        text = f"{tx_type} {reason}".lower()
        if "policy" not in text and "governance" not in text:
            continue
        filtered.append(
            {
                "entry_id": str(item.get("entry_id", "")),
                "timestamp": str(item.get("timestamp", "")),
                "tx_type": tx_type,
                "reason_code": reason,
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    policy_baseline = root / "governance" / "governance_policy_v1.json"
    if policy_baseline.exists():
        try:
            baseline = json.loads(policy_baseline.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            baseline = {}
        filtered.insert(
            0,
            {
                "entry_id": "baseline-governance-policy-v1",
                "timestamp": "",
                "tx_type": "policy_baseline",
                "reason_code": "",
                "payload": baseline if isinstance(baseline, dict) else {},
            },
        )
    return filtered


def load_control_evidence_snapshots(*, root: Path, replay_attestations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evidence_matrix = root / "docs" / "comms" / "claims_evidence_matrix.md"
    if evidence_matrix.exists():
        rows.append(
            {
                "control_id": "claims-evidence-matrix",
                "snapshot_type": "evidence_matrix",
                "source_path": str(evidence_matrix),
                "sha256": hashlib.sha256(evidence_matrix.read_bytes()).hexdigest(),
            }
        )
    runtime_profile = root / "governance_runtime_profile.lock.json"
    if runtime_profile.exists():
        rows.append(
            {
                "control_id": "governance-runtime-profile",
                "snapshot_type": "runtime_profile",
                "source_path": str(runtime_profile),
                "sha256": hashlib.sha256(runtime_profile.read_bytes()).hexdigest(),
            }
        )
    rows.extend(
        {
            "control_id": f"replay-attestation:{row['epoch_id']}",
            "snapshot_type": "immutable_replay_attestation",
            "source_path": row["source_path"],
            "sha256": row["proof_digest"] or row["canonical_digest"],
        }
        for row in replay_attestations
    )
    return rows


def load_incident_remediation_logs(*, journal_module: Any) -> list[dict[str, Any]]:
    entries = journal_module.read_entries(limit=2000)
    rows: list[dict[str, Any]] = []
    for item in entries:
        tx_type = str(item.get("tx_type", ""))
        payload = item.get("payload", {})
        payload_text = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else str(payload)
        combined = f"{tx_type} {payload_text}".lower()
        if "incident" not in combined and "remediation" not in combined and "recover" not in combined:
            continue
        rows.append(
            {
                "entry_id": str(item.get("entry_id", "")),
                "timestamp": str(item.get("timestamp", "")),
                "tx_type": tx_type,
                "severity": str(payload.get("severity", "")) if isinstance(payload, dict) else "",
                "status": str(payload.get("status", "")) if isinstance(payload, dict) else "",
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    return rows
