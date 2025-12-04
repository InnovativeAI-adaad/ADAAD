# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# core/agent_assigner.py
from __future__ import annotations
import json
from pathlib import Path
import logging
from typing import List, Dict, Optional
import time

LOG = logging.getLogger("agent_assigner")
ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
STATUS_FILE = ROOT / "data" / "logs" / "agent_status.json"

def _ensure_status():
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATUS_FILE.exists():
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)

def load_status() -> Dict:
    _ensure_status()
    with open(STATUS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f) or {}
        except Exception:
            return {}

def save_status(st: Dict):
    _ensure_status()
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)

def discover_agents() -> List[Path]:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p for p in AGENTS_DIR.iterdir() if p.is_file() and p.suffix == ".py"])

def assign_agents_to_goal(agent_paths: List[Path], goal: Dict, max_per_goal: int = 3) -> List[str]:
    st = load_status()
    assigned = []
    count = 0
    for p in agent_paths:
        name = p.name
        # skip if already assigned
        if st.get(name, {}).get("assigned_goal") == goal.get("id"):
            continue
        if count >= max_per_goal:
            break
        st[name] = st.get(name, {})
        st[name].update({
            "assigned_goal": goal.get("id"),
            "assigned_at": time.time(),
            "status": "assigned"
        })
        assigned.append(name)
        count += 1
    save_status(st)
    return assigned

def unassign_agent(name: str):
    st = load_status()
    if name in st:
        st[name].pop("assigned_goal", None)
        st[name]["status"] = "idle"
    save_status(st)