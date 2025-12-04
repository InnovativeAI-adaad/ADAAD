#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Activate venv if present
if [ -d "env" ]; then
  . env/bin/activate
fi
# Load .env if present
export $(grep -v '^#' .env 2>/dev/null | xargs -r) || true
python -m app.main "$@"
