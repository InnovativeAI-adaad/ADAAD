# Cryovant Key Handling

- `security/keys/` is created automatically on first run by Cryovant; if you need to provision it manually, run `mkdir -p security/keys` before setting owner-only permissions (`chmod 700 security/keys`).
- Do not commit private keys to version control.
- Ledger writes are recorded in `security/ledger/lineage.jsonl` and mirrored to `reports/metrics.jsonl`.

## Mutation ledger signing and verification

- Mutation ledger records now include `prev_hash`, `canonical_payload_hash`, `signature_bundle`, and `key_metadata` to enforce append-only lineage and signer-policy traceability.
- Non-test runtime paths must provide production `EventSigner` and `EventVerifier` implementations; deterministic mock signing is reserved for test mode.

### Operational key-rotation workflow

1. Provision a new signing key in the production signer backend (KMS/HSM) and mark it as pending active.
2. Update the governance policy artifact signer metadata (`signer.key_id`, `signer.trusted_key_ids`, and algorithm) so the new key is trusted before cutover.
3. Deploy signer/verifier configuration so runtime writes use the new active key while verifier trusts overlap keys during the rotation window.
4. Run full verification against existing and newly-written ledgers using:
   - `python scripts/verify_mutation_ledger.py --ledger <path-to-ledger.jsonl>`
5. Remove retired keys from trusted sets only after verification confirms no active records require them.

### Verification workflow

1. Export verifier key material for validation runs:
   - `export ADAAD_LEDGER_SIGNING_KEYS='{"<key-id>":"<shared-secret-or-test-key>"}'`
2. Execute the ledger verifier script against each ledger artifact.
3. Treat any chain mismatch, signature failure, or key-policy violation as fail-closed and block release progression.

## Repository plaintext secret guardrails (mandatory)

### Prohibited files and content patterns

The repository is fail-closed for plaintext credentials. The following must never be committed:

- Private key blocks (for example, PEM private key block headers)
- Personal access tokens (GitHub PAT formats such as `ghp_...` or `github_pat_11B...` fine-grained)
- Anthropic/Claude keys (`sk-ant-api03-...`)
- PyPI tokens (`pypi-AgEI...`)
- Provider-specific keys (Gravatar, Ollama, ngrok recovery codes, GitHub App client secrets and private keys for ADAADchat)
- Plaintext API keys and OAuth client secrets in assignments (`API_KEY=...`, `client_secret: ...`, etc.)
- Cloud/provider tokens (for example AWS access key IDs, Slack tokens, Stripe live keys)
- Local scratch secret files (`.env.local`, `*.pem`, `*.key`, `SECRET`, `secrets.local.*`)

### Enforced scanning gates

- Deterministic scanner script: `python scripts/scan_secrets.py --path .`
- Pre-commit hook: local `plaintext-secret-scan` gate in `.pre-commit-config.yaml`
- CI enforcement:
  - Main CI workflow (`.github/workflows/ci.yml`) blocks merges on scanner findings.
  - Dedicated secret workflow (`.github/workflows/secret_scan.yml`) runs both gitleaks and deterministic scanner checks.

Any scanner hit is release-blocking and must be remediated immediately.

### Mandatory rotation and remediation workflow

If a plaintext secret is detected in any branch or commit:

1. Revoke/rotate the exposed credential immediately in the upstream provider.
2. Remove the leaked material from code and history as required by incident policy.
3. Re-run `python scripts/scan_secrets.py --path .` and required CI gates until clean.
4. Record incident evidence and rotation completion per operator runbook.

See the dedicated runbook: `docs/security/SECRET_ROTATION_RUNBOOK.md`.
