#!/usr/bin/env bash
# =============================================================================
#  dork.sh — ADAAD DORK Launcher
#  One command to start, query, and monitor DORK from anywhere.
#
#  USAGE
#    ./dork.sh              Start server, wait for ready, open DORK in browser
#    ./dork.sh phone        Termux/Android safe start (uses requirements.phone.txt)
#    ./dork.sh ask "query"  Fire a single governance query and print the answer
#    ./dork.sh status       Print server health without starting anything
#    ./dork.sh stop         Kill the background server
#    ./dork.sh logs         Tail the server log
#
#  ENVIRONMENT OVERRIDES
#    ADAAD_PORT   Server port (default: 8000)
#    ADAAD_HOST   Bind host  (default: 127.0.0.1)
#    ADAAD_REPO   Path to adaad repo (default: directory containing this script)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${ADAAD_REPO:-$SCRIPT_DIR}"
PORT="${ADAAD_PORT:-8000}"
HOST="${ADAAD_HOST:-127.0.0.1}"
BASE_URL="http://${HOST}:${PORT}"
DORK_URL="${BASE_URL}/dork"
HEALTH_URL="${BASE_URL}/api/health"
DORK_API="${BASE_URL}/api/dork/console/route"
LOG_FILE="${REPO_DIR}/.dork_server.log"
PID_FILE="${REPO_DIR}/.dork_server.pid"
MAX_WAIT=30   # seconds to wait for server readiness

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

_ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
_info() { echo -e "  ${CYAN}→${RESET}  $*"; }
_warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
_err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; }
_head() { echo -e "\n${BOLD}${BLUE}◉ DORK${RESET} — $*\n"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_server_running() {
    curl -sf "${HEALTH_URL}" > /dev/null 2>&1
}

_wait_for_ready() {
    local elapsed=0
    echo -ne "  ${CYAN}→${RESET}  Waiting for server"
    while ! _server_running; do
        if [[ $elapsed -ge $MAX_WAIT ]]; then
            echo ""
            _err "Server did not respond after ${MAX_WAIT}s"
            _err "Check logs: $LOG_FILE"
            exit 1
        fi
        echo -ne "."
        sleep 1
        ((elapsed++))
    done
    echo -e " ${GREEN}ready${RESET}"
}

_open_browser() {
    local url="$1"
    if command -v xdg-open &>/dev/null; then
        xdg-open "$url" &>/dev/null &
    elif command -v open &>/dev/null; then
        open "$url" &>/dev/null &
    else
        # Termux / headless — just print the URL
        _info "Open in browser: ${BOLD}${url}${RESET}"
    fi
}

_pick_python() {
    # Prefer python3, fall back to python
    if command -v python3 &>/dev/null; then echo "python3"; return; fi
    if command -v python  &>/dev/null; then echo "python";  return; fi
    _err "python3 not found. Install Python 3."
    exit 1
}

_check_deps() {
    local py="$1"
    if "$py" -c "import uvicorn, fastapi, sse_starlette" &>/dev/null; then
        return 0
    fi

    _warn "Core deps missing — installing..."

    if [[ "${PHONE_MODE:-0}" == "1" ]]; then
        # Try phone requirements first
        if "$py" -m pip install -r "${REPO_DIR}/requirements.phone.txt" \
                --break-system-packages -q 2>/dev/null; then
            _ok "Phone requirements installed"
            return 0
        fi

        _warn "requirements.phone.txt failed — trying minimal bare install..."
        # Bare minimum: fastapi 0.99.1 + pydantic v1 + uvicorn (no Rust)
        # sse-starlette MUST be 1.6.5 — newer versions pull starlette>=0.49 which
        # breaks fastapi 0.99.1 (Router.__init__ on_startup kwarg removed)
        "$py" -m pip install \
            "fastapi==0.99.1" \
            "pydantic==1.10.26" \
            "starlette==0.27.0" \
            "sse-starlette==1.6.5" \
            "uvicorn==0.23.2" \
            "httpx==0.27.2" \
            "anyio>=3.7.1,<5" \
            "h11>=0.14,<0.15" \
            "click>=8.0.0" \
            --break-system-packages -q
    else
        "$py" -m pip install -r "${REPO_DIR}/requirements.server.txt" \
            --break-system-packages -q
    fi

    if "$py" -c "import uvicorn, fastapi, sse_starlette" &>/dev/null; then
        _ok "Dependencies installed"
    else
        _err "Dependency install failed. Try manually:"
        echo "     pip install fastapi==0.99.1 pydantic==1.10.26 starlette==0.27.0 sse-starlette==1.6.5 uvicorn==0.23.2 --break-system-packages"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_start() {
    local py
    py="$(_pick_python)"
    _head "Starting DORK"

    _check_deps "$py"

    if _server_running; then
        _ok "Server already running at ${DORK_URL}"
        _open_browser "$DORK_URL"
        return 0
    fi

    _info "Starting ADAAD server on port ${PORT}..."
    cd "$REPO_DIR"
    ADAAD_HOST="$HOST" ADAAD_PORT="$PORT" \
        "$py" server.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    _wait_for_ready

    _ok "DORK is live"
    echo ""
    echo -e "  ${BOLD}${CYAN}${DORK_URL}${RESET}"
    echo ""
    _open_browser "$DORK_URL"
}

cmd_phone() {
    export PHONE_MODE=1
    export ADAAD_HOST="${ADAAD_HOST:-0.0.0.0}"
    _head "Termux / Phone Mode"
    _info "Using phone-safe requirements (no Rust extensions)"
    cmd_start
    echo ""
    _info "Access DORK from your browser at:"
    echo -e "  ${BOLD}${CYAN}http://localhost:${PORT}/dork${RESET}"
}

cmd_ask() {
    local query="${1:-}"
    if [[ -z "$query" ]]; then
        _err "Usage: ./dork.sh ask \"your question\""
        exit 1
    fi

    _head "Asking DORK"
    _info "Query: ${query}"
    echo ""

    if ! _server_running; then
        _warn "Server not running — starting it first..."
        cmd_start
    fi

    local response
    response=$(curl -sf -X POST "$DORK_API" \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"${query}\"}" 2>&1) || {
        _err "Query failed. Is the server running?"
        exit 1
    }

    # Extract text response — handle both plain string and JSON envelope
    if command -v python3 &>/dev/null; then
        echo "$response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # Try common response envelope keys
    for key in ('answer','response','text','content','result'):
        if key in data:
            print(data[key])
            sys.exit(0)
    # Fall back: print full JSON pretty
    print(json.dumps(data, indent=2))
except Exception:
    print(sys.stdin.read())
" 2>/dev/null || echo "$response"
    else
        echo "$response"
    fi
}

cmd_status() {
    _head "Server Status"
    if _server_running; then
        local health
        health=$(curl -sf "$HEALTH_URL" 2>/dev/null || echo "{}")
        _ok "Server is UP — ${BASE_URL}"
        _info "DORK: ${DORK_URL}"
        if command -v python3 &>/dev/null; then
            echo "$health" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for k, v in d.items():
        print(f'     {k}: {v}')
except Exception:
    pass
" 2>/dev/null || true
        fi
    else
        _warn "Server is NOT running"
        _info "Start with: ./dork.sh"
        if [[ -f "$LOG_FILE" ]]; then
            _info "Last log entry:"
            tail -3 "$LOG_FILE" | sed 's/^/     /'
        fi
    fi
}

cmd_stop() {
    _head "Stopping DORK"
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill "$pid" 2>/dev/null; then
            _ok "Server (PID $pid) stopped"
            rm -f "$PID_FILE"
        else
            _warn "PID $pid not found — server may have already stopped"
            rm -f "$PID_FILE"
        fi
    else
        # Try pkill fallback
        if pkill -f "server.py" 2>/dev/null; then
            _ok "Server stopped"
        else
            _warn "No running DORK server found"
        fi
    fi
}

cmd_logs() {
    _head "Server Logs"
    if [[ -f "$LOG_FILE" ]]; then
        tail -f "$LOG_FILE"
    else
        _warn "No log file found at $LOG_FILE"
        _info "Start the server first: ./dork.sh"
    fi
}

cmd_help() {
    echo ""
    echo -e "${BOLD}${BLUE}◉ DORK${RESET} — ADAAD Governance Intelligence"
    echo ""
    echo -e "  ${BOLD}./dork.sh${RESET}                Start server + open DORK in browser"
    echo -e "  ${BOLD}./dork.sh phone${RESET}          Termux/Android safe start"
    echo -e "  ${BOLD}./dork.sh ask \"query\"${RESET}    Fire a single governance query"
    echo -e "  ${BOLD}./dork.sh status${RESET}         Check if server is running"
    echo -e "  ${BOLD}./dork.sh stop${RESET}           Stop the background server"
    echo -e "  ${BOLD}./dork.sh logs${RESET}           Tail the server log"
    echo ""
    echo -e "  ${CYAN}ADAAD_PORT=9000 ./dork.sh${RESET}   Run on a custom port"
    echo ""
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

MODE="${1:-start}"

case "$MODE" in
    start)          cmd_start ;;
    phone)          cmd_phone ;;
    ask)            shift; cmd_ask "${1:-}" ;;
    status)         cmd_status ;;
    stop)           cmd_stop ;;
    logs)           cmd_logs ;;
    help|--help|-h) cmd_help ;;
    *)
        _err "Unknown command: $MODE"
        cmd_help
        exit 1
        ;;
esac
