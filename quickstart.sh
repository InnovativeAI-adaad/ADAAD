#!/usr/bin/env bash
set -euo pipefail

RUN_PYTEST=1
for arg in "$@"; do
  case "$arg" in
    --skip-pytest) RUN_PYTEST=0 ;;
    *)
      echo "unknown argument: $arg" >&2
      echo "usage: $0 [--skip-pytest]" >&2
      exit 2
      ;;
  esac
done

echo "🚀 ADAAD Quick Start"
export ADAAD_ENV="${ADAAD_ENV:-dev}"
export CRYOVANT_DEV_MODE="${CRYOVANT_DEV_MODE:-1}"

echo "[1/4] validate governance schemas"
PYTHONPATH=. python scripts/validate_governance_schemas.py

if [[ "$RUN_PYTEST" == "1" ]]; then
  echo "[2/4] run fast confidence tests"
  PYTHONPATH=. pytest -q \
    tests/test_policy_signing_scripts.py \
    tests/test_aponi_dashboard_e2e.py \
    tests/test_forensic_retention_script.py
else
  echo "[2/4] skip pytest (requested)"
fi

echo "[3/4] run deterministic simulation runner sample"
mkdir -p reports/quickstart
cat > reports/quickstart/simulation_candidate.json <<'JSON'
{"candidate_id":"quickstart-sample","stages":[{"name":"canary-1","pass":true},{"name":"cohort-25","pass":true}]}
JSON
PYTHONPATH=. python scripts/run_simulation_runner.py --input reports/quickstart/simulation_candidate.json --output reports/quickstart/simulation_verdict.json

echo "[4/4] verify federation/founders-law imports"
if PYTHONPATH=. python - <<'PYCHK' >/dev/null 2>&1
import importlib
importlib.import_module("runtime.governance.founders_law_v2")
PYCHK
then
  PYTHONPATH=. pytest -q tests/test_founders_law_v2.py tests/governance/test_federation_coordination.py
else
  echo "⚠ founders_law_v2 module unavailable; skipping federation compatibility tests (pending merge)"
fi

echo "✅ Quick start checks complete"
echo "   - Simulation verdict: reports/quickstart/simulation_verdict.json"
echo "   - Start dashboard: PYTHONPATH=. python -m ui.aponi_dashboard --host 127.0.0.1 --port 8080"
