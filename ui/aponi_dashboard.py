#!/usr/bin/env python3
"""
Aponi Dashboard (Metal Layer)
Minimal HTTP server for Termux/Pydroid3.

Exposes read-only endpoints:
  /            -> basic status
  /health      -> reports/health.json if present
  /metrics     -> tail of reports/metrics.jsonl
  /boot        -> tail of data/logs/adaad_boot.jsonl
  /ledger      -> tail of security/ledger/events.jsonl
  /cryovant    -> tail of reports/cryovant.jsonl
  /lineage     -> alias of /cryovant
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

PATHS = {
    "health": ROOT / "reports" / "health.json",
    "metrics": ROOT / "reports" / "metrics.jsonl",
    "boot": ROOT / "data" / "logs" / "adaad_boot.jsonl",
    "ledger": ROOT / "security" / "ledger" / "events.jsonl",
    "cryovant": ROOT / "reports" / "cryovant.jsonl",
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _tail_lines(p: Path, n: int) -> list[str]:
    if n < 1:
        n = 1
    if n > 5000:
        n = 5000
    if not p.exists():
        return []
    # Simple tail: read all lines. Ok for small/medium jsonl files on device.
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-n:]

def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)

def _text_response(handler: BaseHTTPRequestHandler, status: int, body: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        # quiet by default
        return

    def do_GET(self) -> None:
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)
        n = int(qs.get("n", ["200"])[0]) if qs.get("n") else 200

        if path == "/":
            payload = {
                "service": "aponi_dashboard",
                "ts": _now_iso(),
                "root": str(ROOT),
                "endpoints": ["/health", "/metrics?n=200", "/boot?n=200", "/ledger?n=200", "/cryovant?n=200", "/lineage?n=200"],
                "files": {k: {"path": str(v), "exists": v.exists(), "bytes": (v.stat().st_size if v.exists() else 0)} for k, v in PATHS.items()},
            }
            return _json_response(self, 200, payload)

        if path in ("/health",):
            p = PATHS["health"]
            if not p.exists():
                return _json_response(self, 404, {"ok": False, "ts": _now_iso(), "error": "health.json not found", "path": str(p)})
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                return _json_response(self, 500, {"ok": False, "ts": _now_iso(), "error": f"health.json parse error: {e}", "path": str(p)})
            return _json_response(self, 200, {"ok": True, "ts": _now_iso(), "health": data})

        if path in ("/metrics", "/boot", "/ledger", "/cryovant", "/lineage"):
            key = "cryovant" if path in ("/cryovant", "/lineage") else path.lstrip("/")
            p = PATHS.get(key)
            lines = _tail_lines(p, n) if p else []
            return _json_response(self, 200, {
                "ok": True,
                "ts": _now_iso(),
                "kind": key,
                "path": str(p) if p else None,
                "exists": (p.exists() if p else False),
                "n": n,
                "lines": lines,
            })

        return _json_response(self, 404, {"ok": False, "ts": _now_iso(), "error": "not found", "path": path})

def main(argv: list[str]) -> int:
    host = os.environ.get("APONI_HOST", "127.0.0.1")
    port = int(os.environ.get("APONI_PORT", "8787"))
    if len(argv) >= 2:
        try:
            port = int(argv[1])
        except Exception:
            pass

    httpd = HTTPServer((host, port), Handler)
    print(f"[APONI] serving on http://{host}:{port} (root={ROOT})")
    print("[APONI] endpoints: / /health /metrics /boot /ledger /cryovant /lineage")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
