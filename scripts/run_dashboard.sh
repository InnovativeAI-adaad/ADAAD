#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-0.0.0.0}"
PORT="${2:-8000}"

if ! python - <<'PY' >/dev/null 2>&1
import uvicorn  # noqa: F401
PY
then
  echo "uvicorn is required. Install with: pip install -r requirements.server.txt" >&2
  exit 1
fi

exec python server.py --host "$HOST" --port "$PORT" --reload
