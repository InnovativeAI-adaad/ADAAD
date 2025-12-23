"""
Cryovant gatekeeper enforcing environment and lineage validation.
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple

from runtime import metrics
from security import SECURITY_ROOT
from security.ledger import journal

ELEMENT_ID = "Water"

KEYS_DIR = SECURITY_ROOT / "keys"


def _valid_signature(signature: str) -> bool:
    return bool(signature and signature not in {"sample-signature", "fill-me"} and len(signature) >= 12)


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
            try:
                import json

                certificate = json.loads(cert.read_text(encoding="utf-8"))
                signature = certificate.get("signature", "")
                if not _valid_signature(signature):
                    signature_failures.append(candidate.name)
            except Exception:
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
        journal.write_entry(agent_id=candidate.name, action="certified", payload={"path": str(candidate)})

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
