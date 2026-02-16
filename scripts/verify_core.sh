#!/data/data/com.termux/files/usr/bin/env sh

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${ROOT_DIR}"

REQUIRED_DIRS="app runtime security tests docs data reports releases experiments scripts ui tools archives"

for dir in $REQUIRED_DIRS; do
  if [ ! -d "${TARGET}/${dir}" ]; then
    echo "Missing required directory: ${dir}"
    exit 1
  fi
done

python3 "${TARGET}/tools/lint_determinism.py"

if command -v rg >/dev/null 2>&1; then
  SEARCH_PATHS=""
  for dir in app runtime security tests docs data reports scripts ui tools; do
    SEARCH_PATHS="${SEARCH_PATHS} ${TARGET}/${dir}"
  done
  BANNED_IMPORTS="$(rg --no-heading --line-number --glob '*.py' '^(from|import) (core|engines|adad_core|ADAAD22)' ${SEARCH_PATHS} || true)"
  ABSOLUTE_IMPORTS="$(rg --no-heading --line-number --glob '*.py' '^from /' ${SEARCH_PATHS} || true)"
else
  echo "ripgrep (rg) is required for verification."
  exit 1
fi

if [ -n "$BANNED_IMPORTS" ] || [ -n "$ABSOLUTE_IMPORTS" ]; then
  echo "Banned import roots detected:"
  echo "$BANNED_IMPORTS"
  echo "$ABSOLUTE_IMPORTS"
  exit 1
fi

METRICS_FILE="${TARGET}/reports/metrics.jsonl"
touch "$METRICS_FILE"

LEDGER_DIR="${TARGET}/security/ledger"
KEYS_DIR="${TARGET}/security/keys"
if [ ! -d "$LEDGER_DIR" ] || [ ! -w "$LEDGER_DIR" ]; then
  echo "Ledger directory missing or not writable"
  exit 1
fi

if [ ! -d "$KEYS_DIR" ]; then
  echo "Keys directory missing"
  exit 1
fi

echo "Core verification passed."
