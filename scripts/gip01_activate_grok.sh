#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="gip01_activate_grok"
DEFAULT_VAULT_FILE="security/ledger/credentials/grok_pat.vault"
VAULT_FILE="${GIP01_VAULT_FILE:-$DEFAULT_VAULT_FILE}"

fail() {
  local code="$1"
  echo "${SCRIPT_NAME}_failure code=${code}" >&2
  exit 1
}

if [[ -z "${GITHUB_PAT:-}" ]]; then
  if ! read -r -s -p "Enter GitHub PAT (input hidden): " GITHUB_PAT; then
    GITHUB_PAT=""
  fi
  echo
fi

if [[ -z "${GITHUB_PAT:-}" ]]; then
  fail "TOKEN_MISSING"
fi

mkdir -p "$(dirname "$VAULT_FILE")"

if ! git check-ignore -q "$VAULT_FILE"; then
  fail "VAULT_PATH_NOT_IGNORED"
fi

if [[ -e "$VAULT_FILE" ]]; then
  mode_existing="$(stat -c '%a' "$VAULT_FILE")"
  group_existing=$(((10#${mode_existing} / 10) % 10))
  other_existing=$((10#${mode_existing} % 10))
  if (( group_existing != 0 || other_existing != 0 )); then
    fail "VAULT_FILE_INSECURE_MODE"
  fi
fi

umask 077
printf '%s\n' "$GITHUB_PAT" > "$VAULT_FILE"
chmod 600 "$VAULT_FILE"

mode_written="$(stat -c '%a' "$VAULT_FILE")"
group_written=$(((10#${mode_written} / 10) % 10))
other_written=$((10#${mode_written} % 10))
if (( group_written != 0 || other_written != 0 )); then
  fail "VAULT_FILE_WORLD_READABLE"
fi

unset GITHUB_PAT

echo "${SCRIPT_NAME}_success vault_file=${VAULT_FILE}"
