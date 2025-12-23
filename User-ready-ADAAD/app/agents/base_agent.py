"""
Base agent definition and validation utilities.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from runtime import metrics

REQUIRED_FILES = ("meta.json", "dna.json", "certificate.json")


class BaseAgent:
    """
    Minimal interface for agents participating in mutation cycles.
    """

    def info(self) -> Dict:
        raise NotImplementedError

    def run(self, input=None) -> Dict:
        raise NotImplementedError

    def mutate(self, src: str) -> str:
        raise NotImplementedError

    def score(self, output: Dict) -> float:
        raise NotImplementedError


def validate_agent_home(agent_path: Path) -> Tuple[bool, List[str]]:
    """
    Validate that a single agent directory contains the required files.
    """
    missing: List[str] = []
    for required in REQUIRED_FILES:
        if not (agent_path / required).exists():
            missing.append(required)
    if missing:
        metrics.log(
            event_type="agent_missing_metadata",
            payload={"agent": agent_path.name, "missing": missing},
            level="ERROR",
        )
        return False, missing
    return True, []


def validate_agents(agents_root: Path) -> Tuple[bool, List[str]]:
    """
    Validate all agent directories and fail fast on missing metadata.
    """
    errors: List[str] = []
    if not agents_root.exists():
        return False, [f"{agents_root} does not exist"]

    for agent_dir in agents_root.iterdir():
        if not agent_dir.is_dir():
            continue
        if agent_dir.name in {"agent_template", "lineage"}:
            continue
        valid, missing = validate_agent_home(agent_dir)
        if not valid:
            errors.append(f"{agent_dir.name}: {','.join(missing)}")
    if errors:
        metrics.log(event_type="agent_validation_failed", payload={"errors": errors}, level="ERROR")
        return False, errors
    metrics.log(event_type="agent_validation_passed", payload={"agents": agents_root.name}, level="INFO")
    return True, []


def write_offspring(parent_id: str, content: str, lineage_dir: Path) -> Path:
    """
    Persist a mutated offspring under the lineage directory with timestamp and hash.
    """
    lineage_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    offspring_dir = lineage_dir / f"{timestamp}_{content_hash}"
    offspring_dir.mkdir(parents=True, exist_ok=True)
    payload = {"parent": parent_id, "content": content}
    with (offspring_dir / "mutation.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    metrics.log(event_type="agent_offspring_written", payload={"path": str(offspring_dir)}, level="INFO")
    return offspring_dir
