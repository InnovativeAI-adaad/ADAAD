from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from security.schema_versions import LINEAGE_SCHEMA_VERSION

REQUIRED_FILES = ("meta.json", "dna.json", "certificate.json")


@dataclass
class AgentValidationResult:
    ok: bool
    missing: List[str]
    lineage_hash: str | None
    path: Path
    schema_violations: List[str]


def compute_lineage_hash(agent_path: Path) -> str:
    h = hashlib.sha256()
    for name in REQUIRED_FILES:
        file_path = agent_path / name
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        h.update(name.encode("utf-8"))
        h.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


def validate_agent_dir(agent_path: Path) -> AgentValidationResult:
    missing = [name for name in REQUIRED_FILES if not (agent_path / name).exists()]
    schema_violations: List[str] = []
    lineage_hash = None
    ok = not missing
    if ok:
        for name in REQUIRED_FILES:
            file_path = agent_path / name
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                schema_violations.append(f"{name}:invalid_json")
                continue
            version = payload.get("schema_version")
            if version != LINEAGE_SCHEMA_VERSION:
                schema_violations.append(f"{name}:schema_version:{version or 'missing'}")
        ok = not schema_violations
        if ok:
            lineage_hash = compute_lineage_hash(agent_path)
    return AgentValidationResult(
        ok=ok, missing=missing, lineage_hash=lineage_hash, path=agent_path, schema_violations=schema_violations
    )


def validate_agents(agent_root: Path) -> Tuple[List[AgentValidationResult], List[AgentValidationResult]]:
    ok: List[AgentValidationResult] = []
    failed: List[AgentValidationResult] = []
    if not agent_root.exists():
        return ok, failed
    for candidate in sorted(agent_root.iterdir()):
        if candidate.is_dir():
            result = validate_agent_dir(candidate)
            (ok if result.ok else failed).append(result)
    return ok, failed
