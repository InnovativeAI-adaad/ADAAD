from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from app.api.nexus.mutate import router as mutate_router


ROOT = Path(__file__).resolve().parent
APONI_DIR = ROOT / "ui" / "aponi"
MOCK_DIR = APONI_DIR / "mock"
INDEX = APONI_DIR / "index.html"
GATE_LOCK_FILE = ROOT / "security" / "ledger" / "gate.lock"
GATE_PROTOCOL = "adaad-gate/1.0"


class SPAStaticFiles(StaticFiles):
    def __init__(self, *args, index_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._index_path = index_path

    async def get_response(self, path: str, scope) -> Response:
        resp = await super().get_response(path, scope)
        if resp.status_code != 404:
            return resp

        req_path = scope.get("path", "")
        if req_path == "/api" or req_path.startswith("/api/"):
            return resp

        return FileResponse(str(self._index_path))

app = FastAPI(title="InnovativeAI-adaad Unified Server")
app.include_router(mutate_router)


@app.on_event("startup")
def _startup_checks() -> None:
    if not APONI_DIR.exists():
        raise RuntimeError("ui/aponi not found. Import APONI into ui/aponi first.")
    if not INDEX.exists():
        raise RuntimeError("ui/aponi/index.html not found. Verify APONI import.")


def _load_mock(name: str) -> Any:
    p = MOCK_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"mock '{name}' not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=500, detail=f"mock '{name}' parse error: {e}")


def _read_gate_state() -> Dict[str, Any]:
    """
    Best-effort gate snapshot. Never surfaces secrets.
    """
    locked = False
    reason = None
    source = "default"

    env_flag = os.environ.get("ADAAD_GATE_LOCKED")
    if env_flag:
        locked = env_flag.lower() not in {"", "0", "false", "no"}
        source = "env"
        reason = os.environ.get("ADAAD_GATE_REASON") or reason

    if GATE_LOCK_FILE.exists():
        source = "file"
        locked = True
        try:
            contents = GATE_LOCK_FILE.read_text(encoding="utf-8").strip()
            if contents:
                reason = contents
        except Exception:
            # Fall back to prior reason if present (keep existing reason)
            pass

    if reason:
        reason = reason[:280]

    return {
        "locked": locked,
        "reason": reason,
        "source": source,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "protocol": GATE_PROTOCOL,
    }


def _assert_gate_open() -> Dict[str, Any]:
    gate = _read_gate_state()
    if gate["locked"]:
        raise HTTPException(
            status_code=423,
            detail=gate["reason"] or "Cryovant gate LOCKED",
            headers={"X-ADAAD-GATE": "locked"},
        )
    return gate


@app.get("/api/health")
def health() -> dict[str, Any]:
    gate = _read_gate_state()
    ok = not gate["locked"]
    return {
        "ok": ok,
        "gate_ok": ok,
        "ui_present": APONI_DIR.exists(),
        "mock_present": MOCK_DIR.exists(),
        "gate": gate,
        "protocol": GATE_PROTOCOL,
    }


@app.get("/api/nexus/health")
def nexus_health() -> dict[str, Any]:
    gate = _read_gate_state()
    snapshot = {"ok": not gate["locked"], "protocol": GATE_PROTOCOL, "gate": gate}
    if gate["locked"]:
        raise HTTPException(
            status_code=423,
            detail=gate["reason"] or "Cryovant gate LOCKED",
            headers={"X-ADAAD-GATE": "locked"},
        )
    return snapshot


@app.get("/api/nexus/handshake")
def nexus_handshake() -> dict[str, Any]:
    gate = _assert_gate_open()
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "protocol": GATE_PROTOCOL,
        "gate": {"locked": False, "reason": None, "checked_at": gate["checked_at"]},
    }


@app.get("/api/nexus/protocol")
def nexus_protocol() -> dict[str, Any]:
    gate = _assert_gate_open()
    # Static placeholder protocol snapshot
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
def nexus_agents() -> dict[str, Any]:
    _assert_gate_open()
    agents_dir = ROOT / "app" / "agents"
    agents: list[dict[str, Any]] = []
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


MOCK_ENDPOINTS = ["status", "agents", "tree", "kpis", "changes", "suggestions"]

for endpoint_name in MOCK_ENDPOINTS:
    app.add_api_route(
        f"/api/{endpoint_name}",
        endpoint=lambda n=endpoint_name: _load_mock(n),
        methods=["GET"],
    )

# Must be last so it can handle deep-link fallbacks after API routes
app.mount("/", SPAStaticFiles(directory=str(APONI_DIR), html=True, index_path=INDEX), name="aponi")
