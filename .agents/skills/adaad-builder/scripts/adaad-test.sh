#!/usr/bin/env bash
# ADAAD Builder Skill — Test Runner
# Aligned to v9.84.0 · Phase 151
# Usage:
#   bash .agents/skills/adaad-builder/scripts/adaad-test.sh               # full suite
#   bash .agents/skills/adaad-builder/scripts/adaad-test.sh phase151       # single phase
#   bash .agents/skills/adaad-builder/scripts/adaad-test.sh spdx           # SPDX only
#   bash .agents/skills/adaad-builder/scripts/adaad-test.sh invariants     # count check
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT"

log()  { echo "[adaad-test] $*"; }
fail() { echo "[adaad-test] ERROR: $*" >&2; exit 1; }

MODE="${1:-full}"

case "$MODE" in
  spdx)
    log "SPDX header compliance check …"
    python3 scripts/check_spdx_headers.py
    log "SPDX OK"
    ;;
  invariants)
    log "Invariant count verification …"
    python3 scripts/check_invariant_count.py
    log "Invariant count OK"
    ;;
  schemas)
    log "Governance schema validation …"
    python3 scripts/validate_governance_schemas.py
    log "Schemas OK"
    ;;
  phase*)
    PHASE="$MODE"
    log "Running phase suite: tests/innovations/test_${PHASE}_*.py …"
    pytest "tests/innovations/" -k "$PHASE" -v \
      --tb=short --no-header \
      || fail "Phase test suite failed."
    log "$PHASE: PASS"
    ;;
  full)
    log "Pre-flight checks …"
    python3 scripts/check_spdx_headers.py      || fail "SPDX check failed."
    python3 scripts/check_invariant_count.py   || fail "Invariant count mismatch."
    python3 scripts/validate_governance_schemas.py || fail "Schema validation failed."
    log "Pre-flight OK — running full test suite …"
    pytest tests/ -v --tb=short --no-header \
      || fail "Test suite failed — see output above."
    log ""
    log "All tests PASS."
    ;;
  *)
    echo "Usage: $0 [full|spdx|invariants|schemas|phase<NNN>]"
    exit 1
    ;;
esac
