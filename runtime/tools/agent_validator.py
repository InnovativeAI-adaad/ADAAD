from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

REQUIRED_FILES = ("meta.json", "dna.json", "certificate.json")


@dataclass
class AgentValidationResult:
    ok: bool
    missing: List[str]
    lineage_hash: str | None
    path: Path


def compute_lineage_hash(agent_path: Path) -> str:
    h = hashlib.sha256()
    for name in REQUIRED_FILES:
        file_path = agent_path / name
        content = file_path.read_text(encoding="utf-8", errors="replace")
        h.update(name.encode("utf-8"))
        h.update(content.encode("utf-8"))
    return h.hexdigest()


def validate_agent_dir(agent_path: Path) -> AgentValidationResult:
    missing = [name for name in REQUIRED_FILES if not (agent_path / name).exists()]
    lineage_hash = None
    ok = not missing
    if ok:
        lineage_hash = compute_lineage_hash(agent_path)
    return AgentValidationResult(ok=ok, missing=missing, lineage_hash=lineage_hash, path=agent_path)


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
