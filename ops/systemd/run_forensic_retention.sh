#!/usr/bin/env bash
set -euo pipefail

# Operational wrapper: provide explicit epoch to deterministic retention evaluator.
NOW_EPOCH="$(date +%s)"

cd /workspace/ADAAD
PYTHONPATH=. /usr/bin/python3 scripts/enforce_forensic_retention.py \
  --export-dir reports/forensics \
  --retention-days 365 \
  --now-epoch "${NOW_EPOCH}" \
  --enforce
