#!/usr/bin/env bash
# ADAAD Builder Skill — Demo & Inspection Runner
# Aligned to v9.84.0 · Phase 151
# Usage:
#   bash .agents/skills/adaad-builder/scripts/adaad-demo.sh demo           # governed dry-run epoch
#   bash .agents/skills/adaad-builder/scripts/adaad-demo.sh das            # docker DAS demo
#   bash .agents/skills/adaad-builder/scripts/adaad-demo.sh ledger <path>  # inspect a ledger
#   bash .agents/skills/adaad-builder/scripts/adaad-demo.sh mcp            # start MCP server
#   bash .agents/skills/adaad-builder/scripts/adaad-demo.sh server         # start whaledic server
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT"

log()  { echo "[adaad-demo] $*"; }
fail() { echo "[adaad-demo] ERROR: $*" >&2; exit 1; }

MODE="${1:-demo}"

# Activate venv if present and not already active
if [[ -z "${VIRTUAL_ENV:-}" ]] && [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    log "Activated .venv"
fi

case "$MODE" in
  demo)
    log "Running governed demo epoch …"
    python scripts/adaad demo
    ;;
  das)
    log "Launching Deterministic Audit Sandbox (DAS) …"
    docker info > /dev/null 2>&1 || fail "Docker not running."
    docker compose up das-demo
    ;;
  ledger)
    LEDGER_PATH="${2:-data/dork/dpm_ledger.jsonl}"
    if [[ ! -f "$LEDGER_PATH" ]]; then
        log "Available ledgers in data/:"
        find data/ -name "*.jsonl" 2>/dev/null | head -20
        fail "Ledger not found: $LEDGER_PATH"
    fi
    log "Inspecting ledger: $LEDGER_PATH"
    python scripts/adaad inspect-ledger "$LEDGER_PATH"
    ;;
  mcp)
    log "Starting MCP server on port 8091 …"
    log "Requires: export ADAAD_MCP_JWT_SECRET=<secret>"
    [[ -n "${ADAAD_MCP_JWT_SECRET:-}" ]] || fail "ADAAD_MCP_JWT_SECRET not set."
    python runtime/mcp/server.py
    ;;
  server)
    log "Starting DORK + whaledic server …"
    python server.py
    ;;
  propose)
    DESC="${2:-}"
    [[ -n "$DESC" ]] || fail "Usage: $0 propose '<description>' [--live]"
    LIVE="${3:-}"
    if [[ "$LIVE" == "--live" ]]; then
        log "Proposing LIVE mutation (HUMAN-0 gate required): $DESC"
        python scripts/adaad propose "$DESC" --live
    else
        log "Proposing sandbox mutation: $DESC"
        python scripts/adaad propose "$DESC"
    fi
    ;;
  *)
    cat <<EOF
Usage: $0 <mode> [args]

Modes:
  demo                       Run a governed dry-run epoch
  das                        Launch Docker DAS demo (docker compose up das-demo)
  ledger [path]              Inspect a JSONL ledger file
  mcp                        Start MCP server (requires ADAAD_MCP_JWT_SECRET)
  server                     Start DORK + whaledic server
  propose '<desc>' [--live]  Propose a mutation (--live requires HUMAN-0)
EOF
    exit 1
    ;;
esac
