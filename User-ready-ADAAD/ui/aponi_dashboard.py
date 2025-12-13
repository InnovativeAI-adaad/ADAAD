from __future__ import annotations

import json
from pathlib import Path
from flask import Flask, jsonify

BASE = Path(__file__).resolve().parents[1]
REPORTS = BASE / "reports"
LEDGER = BASE / "security" / "ledger"
ROOT_README = BASE / "README.md"

app = Flask(__name__)


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _canonical_tree() -> list[str]:
    # Minimal canonical spine for visibility. This is not a filesystem walk.
    return [
        "app/", "runtime/", "security/", "ui/",
        "data/", "reports/", "docs/", "tests/",
        "scripts/", "tools/", "releases/", "experiments/", "archives/",
    ]


@app.get("/metrics")
def metrics():  # type: ignore[override]
    return jsonify(_read_jsonl(REPORTS / "metrics.jsonl"))


@app.get("/health")
def health():  # type: ignore[override]
    log = REPORTS / "health.log"
    if not log.exists():
        return jsonify([])
    return jsonify(log.read_text(encoding="utf-8").splitlines())


@app.get("/ledger")
def ledger():  # type: ignore[override]
    return jsonify(_read_jsonl(LEDGER / "events.jsonl"))


@app.get("/architecture_spec")
def architecture_spec():  # type: ignore[override]
    # Real-time visibility into the current "Law" and spine spec.
    payload = {
        "version_file": str((BASE / "VERSION").resolve()),
        "canonical_spine": _canonical_tree(),
        "root_readme": _read_text(ROOT_README),
        "app_readme": _read_text(BASE / "app" / "README.md"),
        "security_readme": _read_text(BASE / "security" / "README.md"),
        "reports_readme": _read_text(BASE / "reports" / "README.md"),
    }
    return jsonify(payload)


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    app.run(host=host, port=port)


if __name__ == "__main__":
    serve()
