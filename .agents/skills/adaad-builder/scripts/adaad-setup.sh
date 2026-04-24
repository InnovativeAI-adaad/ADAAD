#!/usr/bin/env bash
# ADAAD Builder Skill — Environment Setup
# Aligned to v9.84.0 · Phase 151
# Usage: bash .agents/skills/adaad-builder/scripts/adaad-setup.sh [--docker]
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

log()  { echo "[adaad-setup] $*"; }
fail() { echo "[adaad-setup] ERROR: $*" >&2; exit 1; }

# ── Python version gate ────────────────────────────────────────────────────
PY=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJOR=$(echo "$PY" | cut -d. -f1)
MINOR=$(echo "$PY" | cut -d. -f2)
if [[ "$MAJOR" -lt 3 ]] || [[ "$MAJOR" -eq 3 && "$MINOR" -lt 11 ]]; then
    fail "Python ≥ 3.11 required (found $PY). See pyproject.toml."
fi
log "Python $PY — OK"

# ── Onboard (creates .venv, installs deps, validates schemas, dry-run) ──────
log "Running onboard.py …"
python3 onboard.py || fail "onboard.py failed — check output above."
log "Onboard complete."

# ── Docker DAS demo (optional) ─────────────────────────────────────────────
if [[ "${1:-}" == "--docker" ]]; then
    log "Verifying Docker …"
    docker info > /dev/null 2>&1 || fail "Docker not running. Start Docker and retry."
    log "Launching DAS demo …"
    docker compose up das-demo
fi

# ── SPDX compliance check ──────────────────────────────────────────────────
log "Checking SPDX headers …"
python3 scripts/check_spdx_headers.py || fail "SPDX check failed — run: python3 scripts/check_spdx_headers.py --fix"

# ── Four-surface version sync check ───────────────────────────────────────
log "Verifying four-surface version sync …"
python3 - <<'EOF'
import json, sys
from pathlib import Path

root = Path(".")
version_file = (root / "VERSION").read_text().strip()

with open(root / ".adaad_agent_state.json") as f:
    agent_v = json.load(f)["version"]

with open(root / "governance/report_version.json") as f:
    report_v = json.load(f)["version"]

import re
pyproject = (root / "pyproject.toml").read_text()
m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
pyproject_v = m.group(1) if m else "MISSING"

versions = {
    "VERSION": version_file,
    "pyproject.toml": pyproject_v,
    ".adaad_agent_state.json": agent_v,
    "governance/report_version.json": report_v,
}
unique = set(versions.values())
if len(unique) != 1:
    print("DRIFT DETECTED:")
    for k, v in versions.items():
        print(f"  {k}: {v}")
    sys.exit(1)
print(f"Four-surface sync OK — v{version_file}")
EOF
[[ $? -eq 0 ]] || fail "Four-surface version drift — resolve before proceeding."

log ""
log "╔══════════════════════════════════════════════════╗"
log "║  ADAAD environment ready.                        ║"
log "║  Activate: source .venv/bin/activate             ║"
log "║  Server:   python server.py                      ║"
log "║  Demo:     adaad demo                            ║"
log "║  DAS:      docker compose up das-demo            ║"
log "╚══════════════════════════════════════════════════╝"
