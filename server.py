from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


ROOT = Path(__file__).resolve().parent
APONI_DIR = ROOT / "ui" / "aponi"
ENHANCED_DIR = ROOT / "ui" / "enhanced"
INDEX = APONI_DIR / "index.html"
ENHANCED_INDEX = ENHANCED_DIR / "enhanced_dashboard.html"
PLACEHOLDER_HTML = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>ADAAD Dashboard Placeholder</title>
    <style>
      body { font-family: sans-serif; margin: 2rem; line-height: 1.5; }
      code { background: #f3f4f6; padding: 0.1rem 0.25rem; border-radius: 4px; }
    </style>
  </head>
  <body>
    <h1>ADAAD dashboard placeholder</h1>
    <p>The preferred dashboard UI was not found, so a placeholder was generated.</p>
    <p>API health is available at <code>/api/health</code>.</p>
  </body>
</html>
"""


app = FastAPI(title="InnovativeAI-adaad Unified Server")


def _resolve_ui_paths(*, create_placeholder: bool) -> tuple[Path, Path, Path, str]:
    if APONI_DIR.exists() and INDEX.exists():
        return APONI_DIR, INDEX, APONI_DIR / "mock", "aponi"
    if ENHANCED_DIR.exists() and ENHANCED_INDEX.exists():
        return ENHANCED_DIR, ENHANCED_INDEX, ENHANCED_DIR / "mock", "enhanced"

    if create_placeholder:
        APONI_DIR.mkdir(parents=True, exist_ok=True)
        if not INDEX.exists():
            INDEX.write_text(PLACEHOLDER_HTML, encoding="utf-8")
        return APONI_DIR, INDEX, APONI_DIR / "mock", "placeholder"

    # Keep module import safe in cold-clone/minimal environments.
    return APONI_DIR, INDEX, APONI_DIR / "mock", "missing"


def _current_ui() -> tuple[Path, Path, Path, str]:
    ui_dir = getattr(app.state, "ui_dir", None)
    ui_index = getattr(app.state, "ui_index", None)
    mock_dir = getattr(app.state, "mock_dir", None)
    ui_source = getattr(app.state, "ui_source", None)
    if isinstance(ui_dir, Path) and isinstance(ui_index, Path) and isinstance(mock_dir, Path) and isinstance(ui_source, str):
        return ui_dir, ui_index, mock_dir, ui_source
    return _resolve_ui_paths(create_placeholder=False)


@app.on_event("startup")
def _startup_checks() -> None:
    ui_dir, ui_index, mock_dir, ui_source = _resolve_ui_paths(create_placeholder=True)
    app.state.ui_dir = ui_dir
    app.state.ui_index = ui_index
    app.state.mock_dir = mock_dir
    app.state.ui_source = ui_source
    logging.getLogger(__name__).info("ADAAD server UI source=%s index=%s", ui_source, ui_index)


def _load_mock(name: str) -> Any:
    _, _, mock_dir, _ = _current_ui()
    p = mock_dir / f"{name}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"mock '{name}' not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=500, detail=f"mock '{name}' parse error: {e}")


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    ui_dir, ui_index, mock_dir, ui_source = _current_ui()
    return {
        "ok": True,
        "ui_source": ui_source,
        "ui_dir": str(ui_dir.relative_to(ROOT)),
        "ui_index": str(ui_index.relative_to(ROOT)),
        "mock_present": mock_dir.exists(),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return api_health()


MOCK_ENDPOINTS = ["status", "agents", "tree", "kpis", "changes", "suggestions"]

for endpoint_name in MOCK_ENDPOINTS:
    app.add_api_route(
        f"/api/{endpoint_name}",
        endpoint=lambda n=endpoint_name: _load_mock(n),
        methods=["GET"],
    )


@app.get("/{full_path:path}", include_in_schema=False)
def serve_dashboard(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    ui_dir, ui_index, _, _ = _current_ui()
    if full_path:
        requested = (ui_dir / full_path).resolve()
        try:
            requested.relative_to(ui_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=404, detail="path outside dashboard root")

        if requested.is_file():
            return FileResponse(str(requested))

    return FileResponse(str(ui_index))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the ADAAD dashboard server.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for local development.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    ui_dir, ui_index, _, ui_source = _resolve_ui_paths(create_placeholder=True)
    print(f"🚀 ADAAD Unified Server running at http://{args.host}:{args.port}")
    print(f"📊 Dashboard source: {ui_source} ({ui_dir.relative_to(ROOT)})")
    print(f"📄 Dashboard index: {ui_index.relative_to(ROOT)}")

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit("uvicorn is required. Install with: pip install -r requirements.server.txt") from exc

    uvicorn.run("server:app", host=args.host, port=args.port, reload=args.reload)
