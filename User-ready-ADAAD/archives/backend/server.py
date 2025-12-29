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

"""Lightweight FastAPI backend for the Aponi 1.0 dashboard.

The server exposes simple JSON endpoints that mirror ADAAD's Beast Mode
artifacts. It prefers locally logged data under ``data/dashboard_state.json``
but falls back to baked-in samples when no logs are present.
"""
from __future__ import annotations

import difflib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import logging

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "dashboard_state.json"
ACTIONS_LOG = DATA_DIR / "actions.jsonl"
GATE_LOCK_FILE = ROOT / "security" / "ledger" / "gate.lock"
GATE_PROTOCOL = "adaad-gate/1.0"

app = FastAPI(title="Aponi Dashboard Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid state file: {exc}")
    return {}


def _fallback_state() -> Dict[str, Any]:
    now = datetime.utcnow().isoformat() + "Z"
    return {
        "metrics": {
            "trends": [
                {"ts": now, "metric": "fitness", "value": 0.91},
                {"ts": now, "metric": "survival", "value": 0.83},
                {"ts": now, "metric": "repair_rate", "value": 0.72},
            ],
            "promotion_summary": {"promoted": 6, "quarantined": 2},
            "rolling": [
                {"label": "last_10", "value": 0.78},
                {"label": "last_50", "value": 0.74},
                {"label": "last_100", "value": 0.7},
            ],
        },
        "agents": [
            {
                "id": "aponi-core",
                "status": "promoted",
                "score": 0.91,
                "version": "v1.0",
                "lineage": ["seed", "repair", "promoted"],
                "source": "adad_core/agents/base_agent.py",
                "last_seen": now,
            },
            {
                "id": "aponi-muted",
                "status": "quarantine",
                "score": 0.31,
                "version": "v0.3",
                "lineage": ["seed", "mutate", "quarantine"],
                "source": None,
                "last_seen": now,
            },
        ],
        "actions": [
            {"action": "run_cycle", "ts": now, "result": "ok"},
            {"action": "snapshot", "ts": now, "result": "ok"},
        ],
        "lineage": [
            {"ts": now, "label": "seed", "detail": "Initial agent import"},
            {"ts": now, "label": "repair", "detail": "Self-repair after IO fault"},
            {"ts": now, "label": "promoted", "detail": "Cryovant signature updated"},
        ],
        "mutations": [
            {
                "label": "adaptive_io",
                "before": "def mutate(src):\n    return src\n",
                "after": "def mutate(src):\n    patched = src + '\\n# adaptive IO'\n    return patched\n",
            }
        ],
    }


def _gate_state() -> Dict[str, Any]:
    locked = False
    reason = None
    source = "default"

    env_flag = os.environ.get("ADAAD_GATE_LOCKED")
    if env_flag:
        locked = env_flag.lower() not in {"", "0", "false", "no"}
        source = "env"
        reason = os.environ.get("ADAAD_GATE_REASON") or reason

    if GATE_LOCK_FILE.exists():
        locked = True
        source = "file"
        try:
            contents = GATE_LOCK_FILE.read_text(encoding="utf-8").strip()
            if contents:
                reason = contents
        except Exception as exc:
            # Failed to read gate lock reason; keep gate locked but log for diagnostics.
            logger.warning("Failed to read gate lock file '%s': %s", GATE_LOCK_FILE, exc)

    if reason:
        reason = reason[:280]

    return {
        "locked": locked,
        "reason": reason,
        "source": source,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "protocol": GATE_PROTOCOL,
    }


def _assert_gate_open() -> Dict[str, Any]:
    gate = _gate_state()
    if gate["locked"]:
        raise HTTPException(
            status_code=423,
            detail=gate["reason"] or "Cryovant gate LOCKED",
            headers={"X-ADAAD-GATE": "locked"},
        )
    return gate


def _load_agent_source(path: str | None) -> str:
    if not path:
        return ""
    candidate = (BASE_DIR / path).resolve()
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8")


def _with_survival_rate(metrics: Dict[str, Any]) -> Dict[str, Any]:
    summary = metrics.setdefault("promotion_summary", {})
    promoted = summary.get("promoted", 0)
    quarantined = summary.get("quarantined", 0)
    total = promoted + quarantined
    summary["survival_rate"] = round(promoted / total, 3) if total else 0.0
    return metrics


def _append_action_log(action: str, result: str, details: Dict[str, Any]) -> None:
    ACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "action": action,
        "result": result,
        "ts": datetime.utcnow().isoformat() + "Z",
        "details": details,
    }
    ACTIONS_LOG.write_text(
        (ACTIONS_LOG.read_text(encoding="utf-8") if ACTIONS_LOG.exists() else "")
        + json.dumps(payload)
        + "\n",
        encoding="utf-8",
    )


@app.get("/api/metrics")
def metrics() -> Dict[str, Any]:
    state = _load_state() or _fallback_state()
    metrics_block = state.get("metrics", {})
    return _with_survival_rate(metrics_block)


@app.get("/api/agents")
def agents() -> List[Dict[str, Any]]:
    state = _load_state() or _fallback_state()
    enriched: List[Dict[str, Any]] = []
    for agent in state.get("agents", []):
        enriched.append({**agent, "source_content": _load_agent_source(agent.get("source"))})
    return enriched


@app.get("/api/nexus/handshake")
def nexus_handshake() -> Dict[str, Any]:
    gate = _assert_gate_open()
    return {
        "ok": True,
        "ts": datetime.utcnow().isoformat() + "Z",
        "protocol": GATE_PROTOCOL,
        "gate": {"locked": False, "reason": None, "checked_at": gate["checked_at"]},
    }


@app.get("/api/nexus/protocol")
def nexus_protocol() -> Dict[str, Any]:
    gate = _assert_gate_open()
    return {
        "ok": True,
        "version": "1.0",
        "created_at": gate["checked_at"],
        "gate_cycle": {
            "keys_dir": "security/keys",
            "keys_mode_required_octal": "0700",
            "ledger_dir": "security/ledger",
            "no_bypass": True,
        },
    }


@app.get("/api/nexus/agents")
def nexus_agents() -> Dict[str, Any]:
    gate = _assert_gate_open()
    agents_dir = ROOT / "app" / "agents"
    agents: List[Dict[str, Any]] = []
    if agents_dir.exists():
        for entry in sorted(agents_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir() or entry.name in {"agent_template", "lineage"} or entry.name.startswith("__"):
                continue
            agents.append(
                {
                    "name": entry.name,
                    "meta_exists": (entry / "meta.json").exists(),
                    "dna_exists": (entry / "dna.json").exists(),
                    "certificate_exists": (entry / "certificate.json").exists(),
                    "entrypoint_exists": (entry / "__init__.py").exists(),
                }
            )
    return {"ok": True, "count": len(agents), "agents": agents}


@app.get("/api/nexus/health")
def nexus_health() -> Dict[str, Any]:
    gate = _gate_state()
    snapshot = {"ok": not gate["locked"], "protocol": GATE_PROTOCOL, "gate": gate}
    if gate["locked"]:
        raise HTTPException(
            status_code=423,
            detail=gate["reason"] or "Cryovant gate LOCKED",
            headers={"X-ADAAD-GATE": "locked"},
        )
    return snapshot


@app.get("/api/actions")
def actions() -> List[Dict[str, Any]]:
    state = _load_state() or _fallback_state()
    actions_block = state.get("actions", [])
    if ACTIONS_LOG.exists():
        lines = [json.loads(line) for line in ACTIONS_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
        actions_block = lines + actions_block
    return actions_block


@app.post("/api/actions/{action}")
def perform_action(action: str, payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    allowed = {"run_cycle", "repair", "snapshot", "mutate"}
    if action not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown action: {action}")
    details = {"payload": payload, "ack": True}
    _append_action_log(action, "accepted", details)
    return {
        "action": action,
        "accepted": True,
        "details": details,
        "ts": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/lineage")
def lineage() -> List[Dict[str, Any]]:
    state = _load_state() or _fallback_state()
    return state.get("lineage", [])


@app.get("/api/diff")
def diff() -> Dict[str, Any]:
    state = _load_state() or _fallback_state()
    mutations = state.get("mutations", [])
    if not mutations:
        raise HTTPException(status_code=404, detail="No mutations available")
    record = mutations[-1]
    before = record.get("before", "")
    after = record.get("after", "")
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="before.py",
            tofile="after.py",
            lineterm="",
        )
    )
    return {
        "label": record.get("label", "mutation"),
        "before": before,
        "after": after,
        "diff": "\n".join(diff_lines),
    }
