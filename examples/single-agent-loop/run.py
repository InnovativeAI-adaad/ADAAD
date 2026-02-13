#!/usr/bin/env python3
"""Minimal runnable loop: single constrained agent -> dream -> beast."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("CRYOVANT_DEV_MODE", "1")

from app.beast_mode_loop import BeastModeLoop
from app.dream_mode import DreamMode
from security import cryovant
from security.ledger import journal

ROOT = Path(__file__).resolve().parent
WORKDIR = ROOT / ".run"
AGENTS_ROOT = WORKDIR / "agents"
LINEAGE_DIR = AGENTS_ROOT / "lineage"


def reset_workspace() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    (AGENTS_ROOT / "solo_agent").mkdir(parents=True, exist_ok=True)


def write_single_agent() -> None:
    agent_dir = AGENTS_ROOT / "solo_agent"
    (agent_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "solo_agent",
                "name": "Solo Agent",
                "version": "0.1.0",
                "description": "Minimal loop example agent",
                "dream_scope": {
                    "enabled": True,
                    "allow": ["mutation"],
                    "deny": ["network", "filesystem:outside_agent"],
                },
                "resource_envelope": {"profile": "sandbox"},
                "boot_signature": "deterministic-boot-v1",
                "mutable_global_dependencies": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (agent_dir / "dna.json").write_text(
        json.dumps({"lineage": "seed", "traits": ["minimal"], "version": 1}, indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_dir / "certificate.json").write_text(
        json.dumps(
            {
                "issuer": "cryovant-dev",
                "signature": "cryovant-dev-solo-agent",
                "lineage_hash": "",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    reset_workspace()
    write_single_agent()

    if not cryovant.validate_environment():
        raise SystemExit("cryovant environment failed")
    certified, errors = cryovant.certify_agents(AGENTS_ROOT)
    if not certified:
        raise SystemExit(f"certification failed: {errors}")

    dream = DreamMode(AGENTS_ROOT, LINEAGE_DIR, replay_mode="audit", recovery_tier="advisory")
    tasks = dream.discover_tasks()
    dream_result = dream.run_cycle(agent_id="solo_agent", epoch_id="example-epoch", bundle_id="single-agent-loop")

    beast = BeastModeLoop(AGENTS_ROOT, LINEAGE_DIR)
    beast_result = beast.run_cycle(agent_id="solo_agent")

    print("tasks:", tasks)
    print("dream_result:", json.dumps(dream_result, indent=2))
    print("beast_result:", json.dumps(beast_result, indent=2))
    print("staging:", LINEAGE_DIR / "_staging")
    print("promoted lineage dir:", LINEAGE_DIR)
    print("ledger:", journal.LEDGER_FILE)


if __name__ == "__main__":
    main()
