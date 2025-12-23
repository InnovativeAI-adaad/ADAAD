# SPDX-License-Identifier: Apache-2.0
"""
Cryovant gatekeeper enforcing environment and lineage validation.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from runtime import metrics
from security import SECURITY_ROOT
from security.ledger import journal

ELEMENT_ID = "Water"

KEYS_DIR = SECURITY_ROOT / "keys"
HMAC_KEY_PATH = KEYS_DIR / "hmac.key"
HMAC_KEY_ENV_PATH = "CRYOVANT_HMAC_KEY_PATH"
HMAC_KEY_ENV_B64 = "CRYOVANT_HMAC_KEY_B64"
CRYOVANT_ISSUER_ENV = "CRYOVANT_ISSUER"
CERT_SCHEMA_VERSION = 1


def _hmac_key_path() -> Optional[Path]:
    override = os.getenv(HMAC_KEY_ENV_PATH)
    if override:
        return Path(override)
    return HMAC_KEY_PATH


def _load_hmac_key() -> Optional[bytes]:
    b64_value = os.getenv(HMAC_KEY_ENV_B64)
    if b64_value:
        try:
            return base64.b64decode(b64_value.strip())
        except Exception:
            return None
    path = _hmac_key_path()
    if path and path.exists():
        try:
            if path.stat().st_mode & 0o077:
                return None
        except OSError:
            return None
        key = path.read_text(encoding="utf-8").strip()
        return key.encode("utf-8") if key else None
    return None


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:12]


def _issuer() -> str:
    return os.getenv(CRYOVANT_ISSUER_ENV, "cryovant-dev")


def _hash_payload(payload: Dict[str, Any]) -> Tuple[str, str]:
    canonical = _canonical_json(payload)
    payload_hash = _hash_text(canonical)
    return canonical, payload_hash


def _parse_ts(timestamp: str) -> Optional[datetime]:
    try:
        return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _signature_payload(
    agent_id: str,
    issued_at: str,
    issued_from: str,
    capabilities_snapshot: Dict[str, Any],
    meta: Dict[str, Any],
    dna: Dict[str, Any],
    issuer: str,
    key_id: str,
) -> Dict[str, Any]:
    return {
        "schema_version": CERT_SCHEMA_VERSION,
        "issuer": issuer,
        "key_id": key_id,
        "agent_id": agent_id,
        "issued_at": issued_at,
        "issued_from": issued_from,
        "meta_hash": _hash_text(_canonical_json(meta)),
        "dna_hash": _hash_text(_canonical_json(dna)),
        "capabilities_hash": _hash_text(_canonical_json(capabilities_snapshot)),
    }


def _sign_payload(payload: Dict[str, Any], key: bytes) -> Tuple[str, str]:
    canonical, payload_hash = _hash_payload(payload)
    mac = hmac.new(key, canonical.encode("utf-8"), hashlib.sha256)
    return f"hmac256:{mac.hexdigest()}", payload_hash


def verify_certificate(agent_id: str, meta: Dict[str, Any], dna: Dict[str, Any], certificate: Dict[str, Any]) -> bool:
    if not certificate:
        return False
    if certificate.get("schema_version") != CERT_SCHEMA_VERSION:
        return False
    issuer = certificate.get("issuer")
    if issuer != _issuer():
        return False
    if not isinstance(certificate.get("capabilities_snapshot", {}), dict):
        return False
    signature = certificate.get("signature", "")
    payload_hash = certificate.get("payload_hash", "")
    issued_at = certificate.get("issued_at", "")
    if not signature.startswith("hmac256:") or not payload_hash or not issued_at:
        return False
    issued_dt = _parse_ts(issued_at)
    if not issued_dt:
        return False
    last_issued = journal.last_issued_at(agent_id)
    if last_issued:
        last_dt = _parse_ts(last_issued)
        if not last_dt:
            return False
        if issued_dt < last_dt:
            return False
    key = _load_hmac_key()
    if not key:
        return False
    if certificate.get("key_id") != _key_id(key):
        return False
    expected_payload = _signature_payload(
        agent_id=agent_id,
        issued_at=certificate.get("issued_at", ""),
        issued_from=certificate.get("issued_from", ""),
        capabilities_snapshot=certificate.get("capabilities_snapshot", {}),
        meta=meta,
        dna=dna,
        issuer=issuer,
        key_id=certificate.get("key_id", ""),
    )
    _, recalculated_hash = _hash_payload(expected_payload)
    if payload_hash != recalculated_hash:
        return False
    mac = hmac.new(key, _canonical_json(expected_payload).encode("utf-8"), hashlib.sha256)
    expected_sig = f"hmac256:{mac.hexdigest()}"
    return hmac.compare_digest(expected_sig, signature)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def compute_lineage_hash(agent_dir: Path) -> str:
    """
    Compute the payload hash over agent metadata and certificate fields.
    """
    meta = _read_json(agent_dir / "meta.json")
    dna = _read_json(agent_dir / "dna.json")
    certificate = _read_json(agent_dir / "certificate.json")
    issuer = certificate.get("issuer", _issuer())
    key_id = certificate.get("key_id", "")
    issued_at = certificate.get("issued_at", "")
    issued_from = certificate.get("issued_from", "")
    payload = _signature_payload(
        agent_id=agent_dir.name,
        issued_at=issued_at,
        issued_from=issued_from,
        capabilities_snapshot=certificate.get("capabilities_snapshot", {}),
        meta=meta,
        dna=dna,
        issuer=issuer,
        key_id=key_id,
    )
    _, payload_hash = _hash_payload(payload)
    return payload_hash


def evolve_certificate(agent_id: str, agent_dir: Path, mutation_dir: Path, capabilities_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update the agent certificate with lineage hash and signature.
    """
    certificate_path = agent_dir / "certificate.json"
    existing_cert = _read_json(certificate_path)
    meta = _read_json(agent_dir / "meta.json")
    dna = _read_json(agent_dir / "dna.json")
    key = _load_hmac_key()
    if not key:
        raise RuntimeError("cryovant signing key missing")
    issuer = _issuer()
    key_id = _key_id(key)
    issued_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    base_certificate: Dict[str, Any] = {
        "schema_version": CERT_SCHEMA_VERSION,
        "issuer": issuer,
        "key_id": key_id,
        "issued_at": issued_at,
        "issued_from": str(mutation_dir),
        "capabilities_snapshot": capabilities_snapshot,
    }

    payload = _signature_payload(
        agent_id=agent_id,
        issued_at=issued_at,
        issued_from=str(mutation_dir),
        capabilities_snapshot=capabilities_snapshot,
        meta=meta,
        dna=dna,
        issuer=issuer,
        key_id=key_id,
    )
    signature, payload_hash = _sign_payload(payload, key)

    certificate = {
        **base_certificate,
        "meta_hash": payload["meta_hash"],
        "dna_hash": payload["dna_hash"],
        "capabilities_hash": payload["capabilities_hash"],
        "payload_hash": payload_hash,
        "lineage_hash": payload_hash,
        "signature": signature,
    }
    certificate_path.write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    journal.write_entry(
        agent_id=agent_id,
        action="certificate_evolved",
        payload={"mutation_dir": str(mutation_dir), "lineage_hash": payload_hash, "issued_at": issued_at},
    )
    metrics.log(
        event_type="certificate_evolved",
        payload={"agent": agent_id, "mutation_dir": str(mutation_dir), "lineage_hash": payload_hash},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return certificate


def validate_environment() -> bool:
    """
    Ensure ledger and keys directories exist and ledger is writable.
    """
    try:
        ledger_file = journal.ensure_ledger()
        KEYS_DIR.mkdir(parents=True, exist_ok=True)
        if not os.access(ledger_file.parent, os.W_OK):
            raise PermissionError("ledger not writable")
        test_entry = {"check": "environment_ok"}
        journal.write_entry(agent_id="system", action="env_check", payload=test_entry)
        metrics.log(
            event_type="cryovant_environment_valid",
            payload={"ledger": str(ledger_file), "keys_dir": str(KEYS_DIR)},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        metrics.log(event_type="cryovant_environment_error", payload={"error": str(exc)}, level="ERROR", element_id=ELEMENT_ID)
        return False


def certify_agents(app_agents_dir: Path) -> Tuple[bool, List[str]]:
    """
    Validate that each agent contains the required metadata triplet and signed certificate.
    """
    missing: List[str] = []
    signature_failures: List[str] = []
    agents_root = Path(app_agents_dir)
    if not agents_root.exists():
        metrics.log(event_type="cryovant_no_agents_dir", payload={"path": str(app_agents_dir)}, level="ERROR", element_id=ELEMENT_ID)
        return False, [f"missing agents directory: {app_agents_dir}"]

    for candidate in agents_root.iterdir():
        if not candidate.is_dir():
            continue
        if candidate.name in {"agent_template", "lineage"}:
            continue
        meta = candidate / "meta.json"
        dna = candidate / "dna.json"
        cert = candidate / "certificate.json"
        for required in (meta, dna, cert):
            if not required.exists():
                missing.append(f"{candidate.name}:{required.name}")
        if cert.exists():
            certificate = _read_json(cert)
            meta_data = _read_json(meta)
            dna_data = _read_json(dna)
            if not verify_certificate(candidate.name, meta_data, dna_data, certificate):
                signature_failures.append(candidate.name)
    if missing or signature_failures:
        errors = missing + [f"{name}:invalid_signature" for name in signature_failures]
        metrics.log(event_type="cryovant_certify_failed", payload={"missing": errors}, level="ERROR", element_id=ELEMENT_ID)
        for agent in signature_failures:
            journal.write_entry(agent_id=agent, action="certify_failed", payload={"reason": "invalid_signature"})
        return False, errors

    for candidate in agents_root.iterdir():
        if not candidate.is_dir():
            continue
        if candidate.name in {"agent_template", "lineage"}:
            continue
        certificate = _read_json(candidate / "certificate.json")
        payload = {"path": str(candidate), "lineage_hash": certificate.get("lineage_hash")}
        journal.write_entry(agent_id=candidate.name, action="certified", payload=payload)

    metrics.log(event_type="cryovant_certified", payload={"agents_dir": str(app_agents_dir)}, level="INFO", element_id=ELEMENT_ID)
    return True, []


def validate_ancestry(agent_id: Optional[str]) -> bool:
    """
    Ensure the agent lineage is known before mutation cycles proceed.
    """
    entries = journal.read_entries(limit=200)
    known_ids = {entry.get("agent_id") for entry in entries}
    if not agent_id:
        metrics.log(event_type="cryovant_invalid_agent_id", payload={}, level="ERROR", element_id=ELEMENT_ID)
        journal.write_entry(agent_id="unknown", action="ancestry_failed", payload={"reason": "missing_id"})
        return False

    if known_ids and agent_id not in known_ids:
        metrics.log(
            event_type="cryovant_unknown_ancestry",
            payload={"agent_id": agent_id, "known": list(known_ids)},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        journal.write_entry(agent_id=agent_id, action="ancestry_failed", payload={"known": list(known_ids)})
        return False

    journal.write_entry(agent_id=agent_id, action="ancestry_validated", payload={})
    metrics.log(event_type="cryovant_ancestry_valid", payload={"agent_id": agent_id}, level="INFO", element_id=ELEMENT_ID)
    return True
