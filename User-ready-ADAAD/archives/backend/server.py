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

from datetime import datetime
import difflib
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "dashboard_state.json"
ACTIONS_LOG = DATA_DIR / "actions.jsonl"

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