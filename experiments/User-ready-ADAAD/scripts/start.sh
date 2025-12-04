#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export $(grep -v '^#' .env 2>/dev/null | xargs -r) || true
python -m app.main
