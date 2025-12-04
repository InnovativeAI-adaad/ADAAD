# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
log() { printf "[%s] %s\n" "$(date -u +%H:%M:%S)" "$*"; }

log "Creating/activating venv in env/"
python -m venv env || { log "ERROR: python -m venv failed. Install python + venv."; exit 1; }
. env/bin/activate

log "Upgrading pip and installing requirements-mobile.txt"
pip install --upgrade pip
pip install -r requirements-mobile.txt || { log "WARNING: Installation failed. Review requirements-mobile.txt."; }

log "OK: ADAAD environment ready in env/"
