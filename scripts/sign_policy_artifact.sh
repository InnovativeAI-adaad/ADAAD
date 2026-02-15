#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <input_policy_json> <output_signed_json>" >&2
  exit 2
fi

INPUT_PATH="$1"
OUTPUT_PATH="$2"

: "${ADAAD_POLICY_SIGNER_KEY_ID:=policy-signer-prod-1}"
: "${ADAAD_POLICY_ARTIFACT_SIGNING_KEY:?ADAAD_POLICY_ARTIFACT_SIGNING_KEY must be set}"

PYTHONPATH=. python - "$INPUT_PATH" "$OUTPUT_PATH" "$ADAAD_POLICY_SIGNER_KEY_ID" <<'PY'
import json
import sys
from pathlib import Path

from runtime.governance.policy_artifact import (
    GovernancePolicyArtifactEnvelope,
    GovernanceSignerMetadata,
    policy_artifact_digest,
)
from security import cryovant

src = Path(sys.argv[1])
out = Path(sys.argv[2])
key_id = sys.argv[3]
artifact = json.loads(src.read_text(encoding="utf-8"))
artifact["signer"] = {"key_id": key_id, "algorithm": "hmac-sha256"}

envelope = GovernancePolicyArtifactEnvelope(
    schema_version=artifact["schema_version"],
    payload=artifact["payload"],
    signer=GovernanceSignerMetadata(key_id=key_id, algorithm="hmac-sha256"),
    signature="",
    previous_artifact_hash=artifact["previous_artifact_hash"],
    effective_epoch=artifact["effective_epoch"],
)
artifact["signature"] = cryovant.sign_hmac_digest(
    key_id=key_id,
    signed_digest=policy_artifact_digest(envelope),
    specific_env_prefix="ADAAD_POLICY_ARTIFACT_KEY_",
    generic_env_var="ADAAD_POLICY_ARTIFACT_SIGNING_KEY",
    fallback_namespace="adaad-policy-artifact-dev-secret",
)
out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
print(out)
PY
