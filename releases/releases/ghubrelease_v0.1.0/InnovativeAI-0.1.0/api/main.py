# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from pathlib import Path
import json

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from config import settings

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"


def _load_demo_json(filename: str, fallback):
    """Return demo JSON payloads without side effects or writes."""
    path = (DATA_DIR / filename).resolve()
    if DATA_DIR.resolve() not in path.parents or path.name != filename:
        return fallback

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return fallback


async def serve_index(_request):
    return FileResponse(STATIC_DIR / "aponi_dashboard.html")


async def health(_request):
    payload = _load_demo_json(
        "sample_health.json",
        {"status": "ok", "mode": "public-demo", "device": "unknown"},
    )
    return JSONResponse(payload)


async def metrics(_request):
    payload = _load_demo_json(
        "sample_metrics.json",
        {"uptime_seconds": 0, "mutation_survival_rate": 0.0, "promoted_agents": 0, "quarantined_agents": 0},
    )
    return JSONResponse(payload)


async def agents(_request):
    payload = _load_demo_json(
        "sample_agents.json",
        [
            {
                "id": "demo_agent",
                "name": "Demo Agent",
                "status": "available",
                "description": "Placeholder agent for the ADAAD-Free public demo (not executable).",
            }
        ],
    )
    return JSONResponse(payload)


routes = [
    Route("/", serve_index, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
    Route("/metrics", metrics, methods=["GET"]),
    Route("/agents", agents, methods=["GET"]),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]


app = Starlette(debug=settings.DEBUG, routes=routes)
