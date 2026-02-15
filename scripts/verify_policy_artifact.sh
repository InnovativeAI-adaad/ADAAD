#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <signed_policy_json>" >&2
  exit 2
fi

POLICY_PATH="$1"

PYTHONPATH=. python - "$POLICY_PATH" <<'PY'
import sys
from pathlib import Path

from runtime.governance.policy_artifact import load_governance_policy

policy = load_governance_policy(Path(sys.argv[1]))
print(policy.fingerprint)
PY
