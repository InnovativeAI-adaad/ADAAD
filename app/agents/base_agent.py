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
Base agent definition and validation utilities.
"""

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

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


def _is_agent_dir(path: Path) -> bool:
    return path.is_dir() and all((path / required).exists() for required in REQUIRED_FILES)


def _iter_candidate_agent_dirs(agents_root: Path) -> Iterable[Path]:
    """
    Yield agent directories, supporting both:
      1) app/agents/<agent_id>/
      2) app/agents/<bucket>/<agent_id>/
    """
    for entry in sorted(agents_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name.startswith("__") or entry.name in {"lineage"}:
            continue
        if _is_agent_dir(entry):
            yield entry
            continue

        # bucket container
        for child in sorted(entry.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith("__"):
                continue
            if _is_agent_dir(child):
                yield child


def validate_agents(agents_root: Path) -> Tuple[bool, List[str]]:
    """
    Validate all agent directories and fail fast on missing metadata.
    """
    errors: List[str] = []
    if not agents_root.exists():
        return False, [f"{agents_root} does not exist"]

    for agent_dir in _iter_candidate_agent_dirs(agents_root):
        if agent_dir.name == "agent_template":
            continue
        valid, missing = validate_agent_home(agent_dir)
        if not valid:
            errors.append(f"{agent_dir.name}: {','.join(missing)}")
    if errors:
        metrics.log(event_type="agent_validation_failed", payload={"errors": errors}, level="ERROR")
        return False, errors
    metrics.log(event_type="agent_validation_passed", payload={"agents": agents_root.name}, level="INFO")
    return True, []


def stage_offspring(parent_id: str, content: str, lineage_dir: Path) -> Path:
    """
    Stage a mutated offspring into the _staging area with metadata and hash.
    """
    staging_root = lineage_dir / "_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    staged_dir = staging_root / f"{timestamp}_{content_hash}"
    staged_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "parent": parent_id,
        "content": content,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "content_hash": content_hash,
    }
    with (staged_dir / "mutation.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    metrics.log(event_type="offspring_staged", payload={"path": str(staged_dir)}, level="INFO")
    return staged_dir


def promote_offspring(staged_dir: Path, lineage_dir: Path) -> Path:
    """
    Promote a staged offspring into the main lineage directory.
    """
    if not staged_dir.exists():
        raise FileNotFoundError(f"staged_dir missing: {staged_dir}")
    lineage_dir.mkdir(parents=True, exist_ok=True)
    target_dir = lineage_dir / staged_dir.name
    shutil.move(str(staged_dir), target_dir)
    metrics.log(event_type="offspring_promoted", payload={"from": str(staged_dir), "to": str(target_dir)}, level="INFO")
    return target_dir
