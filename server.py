from __future__ import annotations

import argparse
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse

from runtime import metrics
from runtime.evolution.evidence_bundle import EvidenceBundleBuilder, FORENSIC_EXPORT_DIR
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay_attestation import REPLAY_PROOFS_DIR, load_replay_proof, verify_replay_proof_bundle
from runtime.governance.deterministic_filesystem import read_file_deterministic
from runtime.governance.review_quality import DEFAULT_REVIEW_SLA_SECONDS, summarize_review_quality
from security.ledger import journal


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    ui_dir, ui_index, mock_dir, ui_source = _resolve_ui_paths(create_placeholder=True)
    app.state.ui_dir = ui_dir
    app.state.ui_index = ui_index
    app.state.mock_dir = mock_dir
    app.state.ui_source = ui_source
    logging.getLogger(__name__).info("ADAAD server UI source=%s index=%s", ui_source, ui_index)
    yield


app = FastAPI(title="InnovativeAI-adaad Unified Server", lifespan=lifespan)

AUDIT_READ_SCOPE = "audit:read"


def _load_audit_tokens() -> dict[str, set[str]]:
    raw_tokens = (os.getenv("ADAAD_AUDIT_TOKENS") or "").strip()
    token_map: dict[str, set[str]] = {}
    if raw_tokens:
        try:
            parsed = json.loads(raw_tokens)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for token, scopes in parsed.items():
                if not isinstance(token, str):
                    continue
                if isinstance(scopes, list):
                    token_map[token.strip()] = {str(scope).strip() for scope in scopes if str(scope).strip()}
    dev_token = (os.getenv("ADAAD_AUDIT_DEV_TOKEN") or "").strip()
    if dev_token:
        token_map.setdefault(dev_token, {AUDIT_READ_SCOPE})
    return token_map


def _authenticate_audit_request(
    authorization: str | None = Header(default=None),
    x_client_cert_subject: str | None = Header(default=None),
) -> dict[str, Any]:
    token_map = _load_audit_tokens()
    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            scopes = token_map.get(token)
            if scopes is not None:
                return {"scheme": "bearer", "principal": "token", "scopes": sorted(scopes)}
            raise HTTPException(status_code=401, detail="invalid_token")

    if x_client_cert_subject:
        mtls_scope = (os.getenv("ADAAD_AUDIT_MTLS_SCOPE") or AUDIT_READ_SCOPE).strip()
        return {
            "scheme": "mtls",
            "principal": x_client_cert_subject.strip(),
            "scopes": [mtls_scope],
        }

    raise HTTPException(status_code=401, detail="missing_authentication")


def _require_scope(auth_ctx: dict[str, Any], required_scope: str) -> None:
    scopes = {str(scope) for scope in auth_ctx.get("scopes", [])}
    if required_scope not in scopes:
        raise HTTPException(status_code=403, detail="insufficient_scope")


def _apply_redaction(payload: Any, redaction: str) -> Any:
    if redaction == "none":
        return payload
    if isinstance(payload, list):
        return [_apply_redaction(item, redaction) for item in payload]
    if not isinstance(payload, dict):
        return payload

    redacted = {k: _apply_redaction(v, redaction) for k, v in payload.items()}
    if redaction in {"sensitive", "strict"}:
        redacted.pop("signature", None)
        redacted.pop("signatures", None)
        redacted.pop("certificate", None)
        if isinstance(redacted.get("export_metadata"), dict):
            signer = dict(redacted["export_metadata"].get("signer") or {})
            signer.pop("signature", None)
            redacted["export_metadata"]["signer"] = signer
    if redaction == "strict":
        redacted.pop("principal", None)
        redacted.pop("sandbox_replay", None)
    return redacted


def _audit_envelope(*, data: Any, auth_ctx: dict[str, Any], redaction: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "authn": {
            "scheme": auth_ctx["scheme"],
            "scope": AUDIT_READ_SCOPE,
            "redaction": redaction,
        },
        "data": _apply_redaction(data, redaction),
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


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


@app.get("/metrics/review-quality")
def metrics_review_quality(
    limit: int = Query(default=500, ge=1, le=5000),
    sla_seconds: int = Query(default=DEFAULT_REVIEW_SLA_SECONDS, ge=1, le=604800),
) -> dict[str, Any]:
    entries = metrics.tail(limit)
    summary = summarize_review_quality(entries, default_sla_seconds=sla_seconds)
    summary["window_limit"] = limit
    summary["sla_seconds"] = sla_seconds
    return summary


@app.get("/api/audit/epochs/{epoch_id}/replay-proof")
def api_audit_replay_proof(
    epoch_id: str,
    redaction: Literal["none", "sensitive", "strict"] = Query(default="sensitive"),
    auth_ctx: dict[str, Any] = Depends(_authenticate_audit_request),
) -> dict[str, Any]:
    _require_scope(auth_ctx, AUDIT_READ_SCOPE)
    bundle_path = REPLAY_PROOFS_DIR / f"{epoch_id}.replay_attestation.v1.json"
    if not bundle_path.exists():
        raise HTTPException(status_code=404, detail="replay_proof_not_found")
    bundle = load_replay_proof(bundle_path)
    verification = verify_replay_proof_bundle(bundle)
    payload = {
        "epoch_id": epoch_id,
        "bundle_path": _display_path(bundle_path),
        "bundle": bundle,
        "verification": verification,
    }
    return _audit_envelope(data=payload, auth_ctx=auth_ctx, redaction=redaction)


@app.get("/api/audit/epochs/{epoch_id}/lineage")
def api_audit_epoch_lineage(
    epoch_id: str,
    redaction: Literal["none", "sensitive", "strict"] = Query(default="sensitive"),
    auth_ctx: dict[str, Any] = Depends(_authenticate_audit_request),
) -> dict[str, Any]:
    _require_scope(auth_ctx, AUDIT_READ_SCOPE)
    ledger = LineageLedgerV2()
    entries = ledger.read_epoch(epoch_id)
    if not entries:
        raise HTTPException(status_code=404, detail="epoch_not_found")
    journal_entries = [entry for entry in journal.read_entries(limit=200) if entry.get("epoch_id") == epoch_id]
    payload = {
        "epoch_id": epoch_id,
        "lineage": entries,
        "lineage_digest": ledger.compute_incremental_epoch_digest(epoch_id),
        "expected_epoch_digest": ledger.get_expected_epoch_digest(epoch_id),
        "journal_entries": journal_entries,
    }
    return _audit_envelope(data=payload, auth_ctx=auth_ctx, redaction=redaction)


@app.get("/api/audit/bundles/{bundle_id}")
def api_audit_bundle(
    bundle_id: str,
    redaction: Literal["none", "sensitive", "strict"] = Query(default="sensitive"),
    auth_ctx: dict[str, Any] = Depends(_authenticate_audit_request),
) -> dict[str, Any]:
    _require_scope(auth_ctx, AUDIT_READ_SCOPE)
    bundle_path = FORENSIC_EXPORT_DIR / f"{bundle_id}.json"
    if not bundle_path.exists():
        raise HTTPException(status_code=404, detail="bundle_not_found")
    bundle = json.loads(read_file_deterministic(bundle_path))
    validator = EvidenceBundleBuilder(export_dir=FORENSIC_EXPORT_DIR)
    validation_errors = validator.validate_bundle(bundle)
    payload = {
        "bundle_id": bundle_id,
        "bundle_path": _display_path(bundle_path),
        "bundle": bundle,
        "validation": {"ok": not validation_errors, "errors": validation_errors},
    }
    return _audit_envelope(data=payload, auth_ctx=auth_ctx, redaction=redaction)


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
