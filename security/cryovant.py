# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Cryovant gatekeeper enforcing environment and lineage validation.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents.discovery import iter_agent_dirs, resolve_agent_id
from runtime import metrics
from security import SECURITY_ROOT
from security.ledger import journal

ELEMENT_ID = "Water"

KEYS_DIR = SECURITY_ROOT / "keys"
LEDGER_DIR = SECURITY_ROOT / "ledger"


def dev_mode() -> bool:
    return os.environ.get("CRYOVANT_DEV_MODE", "0").lower() in {"1", "true", "yes", "on"}


def verify_signature(signature: str) -> bool:
    """
    Placeholder signature verification hook. Returns False until real keys are configured.
    """
    return False


def _valid_signature(signature: str) -> bool:
    return (signature.startswith("cryovant-dev-") and dev_mode()) or verify_signature(signature)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def compute_lineage_hash(agent_dir: Path) -> str:
    """
    Compute a stable hash over agent metadata triplet.
    """
    meta = _read_json(agent_dir / "meta.json")
    dna = _read_json(agent_dir / "dna.json")
    certificate = _read_json(agent_dir / "certificate.json")
    bundle = {"certificate.json": certificate, "dna.json": dna, "meta.json": meta}
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evolve_certificate(agent_id: str, agent_dir: Path, mutation_dir: Path, capabilities_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update the agent certificate with lineage hash and signature.
    """
    certificate_path = agent_dir / "certificate.json"
    existing_cert = _read_json(certificate_path)
    meta = _read_json(agent_dir / "meta.json")
    dna = _read_json(agent_dir / "dna.json")
    base_certificate: Dict[str, Any] = {
        "issuer": "cryovant-dev",
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issued_from": str(mutation_dir),
        "capabilities_snapshot": capabilities_snapshot,
    }
    for key, value in existing_cert.items():
        if key not in base_certificate:
            base_certificate[key] = value

    bundle = {"certificate.json": base_certificate, "dna.json": dna, "meta.json": meta}
    lineage_hash = hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    signature = existing_cert.get("signature")
    if not _valid_signature(signature or ""):
        signature = f"cryovant-dev-{lineage_hash[:12]}"

    certificate = {**base_certificate, "lineage_hash": lineage_hash, "signature": signature}
    certificate_path.write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    journal.write_entry(
        agent_id=agent_id,
        action="certificate_evolved",
        payload={"mutation_dir": str(mutation_dir), "lineage_hash": lineage_hash},
    )
    metrics.log(
        event_type="certificate_evolved",
        payload={"agent": agent_id, "mutation_dir": str(mutation_dir), "lineage_hash": lineage_hash},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return certificate


def validate_environment() -> bool:
    """
    Ensure ledger and keys directories exist and ledger is writable.
    """
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(KEYS_DIR), 0o700)
    except Exception:
        pass

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    probe = LEDGER_DIR / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        metrics.log(
            event_type="cryovant_environment_invalid",
            payload={"ledger_dir": str(LEDGER_DIR), "error": str(exc)},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        return False

    try:
        ledger_file = journal.ensure_ledger()
        journal.write_entry(agent_id="system", action="env_check", payload={"check": "environment_ok"})
    except Exception as exc:  # pragma: no cover - defensive logging
        metrics.log(
            event_type="cryovant_environment_error",
            payload={"ledger_dir": str(LEDGER_DIR), "error": str(exc)},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        return False

    metrics.log(
        event_type="cryovant_environment_valid",
        payload={"ledger_dir": str(LEDGER_DIR), "ledger_file": str(ledger_file), "keys_dir": str(KEYS_DIR)},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return True


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

    agent_dirs = list(iter_agent_dirs(agents_root))
    if not agent_dirs:
        metrics.log(event_type="cryovant_certified", payload={"agents_dir": str(app_agents_dir), "agents": 0}, level="INFO", element_id=ELEMENT_ID)
        return True, []

    for candidate in agent_dirs:
        agent_id = resolve_agent_id(candidate, agents_root)
        meta = candidate / "meta.json"
        dna = candidate / "dna.json"
        cert = candidate / "certificate.json"
        for required in (meta, dna, cert):
            if not required.exists():
                missing.append(f"{agent_id}:{required.name}")
        if cert.exists():
            certificate = _read_json(cert)
            signature = certificate.get("signature", "")
            lineage_hash = certificate.get("lineage_hash")
            if not lineage_hash and _valid_signature(signature):
                lineage_hash = compute_lineage_hash(candidate)
                certificate["lineage_hash"] = lineage_hash
                cert.write_text(json.dumps(certificate, indent=2), encoding="utf-8")
                journal.write_entry(agent_id=agent_id, action="certificate_evolved", payload={"lineage_hash": lineage_hash})
            if not _valid_signature(signature):
                signature_failures.append(agent_id)
    if missing or signature_failures:
        errors = missing + [f"{name}:invalid_signature" for name in signature_failures]
        metrics.log(event_type="cryovant_certify_failed", payload={"missing": errors}, level="ERROR", element_id=ELEMENT_ID)
        for agent in signature_failures:
            journal.write_entry(agent_id=agent, action="certify_failed", payload={"reason": "invalid_signature"})
        return False, errors

    for candidate in agent_dirs:
        agent_id = resolve_agent_id(candidate, agents_root)
        certificate = _read_json(candidate / "certificate.json")
        payload = {"path": str(candidate), "lineage_hash": certificate.get("lineage_hash")}
        journal.write_entry(agent_id=agent_id, action="certified", payload=payload)

    metrics.log(event_type="cryovant_certified", payload={"agents_dir": str(app_agents_dir), "agents": len(agent_dirs)}, level="INFO", element_id=ELEMENT_ID)
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
