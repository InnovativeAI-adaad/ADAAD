# SPDX-License-Identifier: Apache-2.0
"""
Canonical agent discovery for He65.

Supports both layouts:
  1) app/agents/<agent_id>/
  2) app/agents/<bucket>/<agent_id>/

An agent directory is defined by the presence of the REQUIRED_FILES set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

REQUIRED_FILES = ("meta.json", "dna.json", "certificate.json")


def is_agent_dir(path: Path) -> bool:
    return path.is_dir() and all((path / req).exists() for req in REQUIRED_FILES)


def iter_agent_dirs(agents_root: Path) -> Iterable[Path]:
    """
    Deterministically yield agent directories, skipping non-agent folders.
    """
    if not agents_root.exists():
        return

    for entry in sorted(agents_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name.startswith("__") or entry.name in {"lineage", "agent_template"}:
            continue

        if is_agent_dir(entry):
            yield entry
            continue

        # Treat as a bucket container; yield valid child agent dirs.
        for child in sorted(entry.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            if child.name.startswith("__"):
                continue
            if is_agent_dir(child):
                yield child


def resolve_agent_id(agent_dir: Path, agents_root: Path) -> str:
    """
    Stable identifier for ledger and metrics: relative path, slashes replaced by colons.
    """
    rel = agent_dir.resolve().relative_to(agents_root.resolve()).as_posix()
    return rel.replace("/", ":")


def agent_path_from_id(agent_id: str, agents_root: Path) -> Path:
    """
    Convert a canonical agent_id back to a filesystem path under agents_root.
    """
    return agents_root / agent_id.replace(":", "/")
