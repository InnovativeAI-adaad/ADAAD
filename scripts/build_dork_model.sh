#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# scripts/build_dork_model.sh
# Phase 143 · INNOV-49 · Constitutional Model Upgrade (CMU)
#
# One-command DORK model build pipeline.
# CMU-CTX-0 and CMU-TEMP-0 are validated BEFORE invoking ollama.
# CMU-DETERM-0: build event is appended to data/dork/cmu_ledger.jsonl.
# CMU-HUMAN0-0: model upgrade advisory is printed — HUMAN-0 must ratify.
#
# Usage:
#   bash scripts/build_dork_model.sh [--model MODEL] [--modelfile PATH]
#
# Options:
#   --model       Override base model (default: phi4:14b-q4_K_M)
#   --modelfile   Path to Modelfile (default: dorkllm/Modelfile)
#   --cpu-fallback  Use llama3.2:latest with 16384 ctx (CPU-safe)
#   --dry-run     Validate Modelfile and print plan without building

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Defaults ──────────────────────────────────────────────────────────────────
MODELFILE="dorkllm/Modelfile"
DORK_MODEL_NAME="dork"
DRY_RUN=false
CPU_FALLBACK=false

# ── Arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)       shift; BASE_MODEL_OVERRIDE="$1" ;;
    --modelfile)   shift; MODELFILE="$1" ;;
    --dry-run)     DRY_RUN=true ;;
    --cpu-fallback) CPU_FALLBACK=true ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
  shift
done

# ── CPU fallback: patch Modelfile in-place ────────────────────────────────────
if $CPU_FALLBACK; then
  echo "[CMU] CPU fallback mode: base=llama3.2:latest, num_ctx=16384"
  TMP_MF="$(mktemp)"
  sed 's|^FROM .*|FROM llama3.2:latest|' "$MODELFILE" \
    | sed 's|^PARAMETER num_ctx .*|PARAMETER num_ctx 16384|' > "$TMP_MF"
  MODELFILE="$TMP_MF"
  trap "rm -f $TMP_MF" EXIT
fi

# ── CMU invariant pre-validation (Python) ─────────────────────────────────────
echo "[CMU] Validating Modelfile against CMU-CTX-0 and CMU-TEMP-0..."
python3 - <<PYEOF
import sys
sys.path.insert(0, '.')
from dorkllm.model_validator import validate_modelfile, full_cmu_validation
from pathlib import Path
try:
    result = full_cmu_validation(modelfile_path=Path('${MODELFILE}'), record_event=False)
    print(f"  CMU-CTX-0  : PASS (num_ctx={result['num_ctx']})")
    print(f"  CMU-TEMP-0 : PASS (temperature={result['temperature']})")
    print(f"  base_model : {result['base_model']}")
except Exception as e:
    print(f"  INVARIANT VIOLATION: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

echo ""

if $DRY_RUN; then
  echo "[CMU] Dry run complete. No model was built."
  exit 0
fi

# ── CMU-HUMAN0-0 advisory ─────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  CMU-HUMAN0-0 ADVISORY                                          ║"
echo "║  Model upgrades are constitutional mutations.                    ║"
echo "║  This build requires HUMAN-0 (Dustin L. Reid) ratification.     ║"
echo "║  After build: record ratification in data/dork/cmu_ledger.jsonl ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# ── Check Ollama availability ─────────────────────────────────────────────────
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
if ! curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
  echo "[CMU] ERROR: Ollama is not reachable at ${OLLAMA_URL}"
  echo "      Start Ollama with: ollama serve"
  exit 1
fi
echo "[CMU] Ollama reachable at ${OLLAMA_URL}"

# ── Pull base model if needed ─────────────────────────────────────────────────
BASE_MODEL=$(grep -m1 "^FROM " "$MODELFILE" | awk '{print $2}')
echo "[CMU] Base model: ${BASE_MODEL}"
echo "[CMU] Pulling base model (no-op if already present)..."
ollama pull "${BASE_MODEL}"

# ── Build DORK model ──────────────────────────────────────────────────────────
echo ""
echo "[CMU] Building DORK model from ${MODELFILE}..."
ollama create "${DORK_MODEL_NAME}" -f "${MODELFILE}"
echo ""
echo "[CMU] Build complete. Model name: ${DORK_MODEL_NAME}"

# ── Append CMU ledger entry (CMU-DETERM-0) ────────────────────────────────────
echo "[CMU] Recording build in CMU ledger (CMU-DETERM-0)..."
python3 - <<PYEOF
import sys
sys.path.insert(0, '.')
from dorkllm.model_validator import parse_modelfile, append_cmu_ledger
from pathlib import Path
params = parse_modelfile(Path('${MODELFILE}'))
entry = append_cmu_ledger('model_built', params, ratified_by_human0=False)
print(f"  Ledger seq  : {entry.seq}")
print(f"  Entry hash  : {entry.entry_hash[:16]}...")
print(f"  Modelfile   : {entry.modelfile_digest[:16]}...")
PYEOF

echo ""
echo "[CMU] DORK model build pipeline complete."
echo "      Run: ollama run dork"
echo "      Test: python3 -m dorkllm.model_validator"
echo ""
echo "[CMU-HUMAN0-0] Reminder: ratify this model upgrade in cmu_ledger.jsonl."
