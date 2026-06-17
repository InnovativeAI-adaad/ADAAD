# Secret Rotation Runbook (Post-Detection)

## Scope

This runbook is invoked whenever repository secret-scanning gates detect potential plaintext credentials.

## Trigger sources

- `python scripts/scan_secrets.py --path .`
- `.pre-commit-config.yaml` local hook `plaintext-secret-scan`
- `.github/workflows/ci.yml` secret scan step
- `.github/workflows/secret_scan.yml` deterministic + gitleaks scans

## Mandatory operator actions

1. **Contain**
   - Freeze release activity for affected branch/PR.
   - Identify exact credential type and impacted provider/service.
2. **Rotate and revoke**
   - Revoke exposed token/key at provider immediately.
   - Issue replacement credential following least-privilege policy.
3. **Repository remediation**
   - Remove plaintext secret from tracked files.
   - If already committed, execute approved history-remediation process.
4. **Verification**
   - Run scanner: `python scripts/scan_secrets.py --path .`
   - Run required governance/test gates before merge.
5. **Evidence and closure**
   - Record incident summary, rotation timestamp, and verification outcome in operator evidence records.
   - Link remediation evidence in release/PR documentation as required.

## Invariants

- Do not suppress scanner rules to pass CI.
- Do not replace leaked values with alternate real credentials.
- Only placeholder templates may remain in tracked examples.

## Recent high-severity findings (example remediation)
Findings included:
- Multiple GitHub PATs (fine-grained `github_pat_11BGU3ABI...` and classic `ghp_...`)
- Claude/Anthropic key (`sk-ant-api03-tMsC4Rm...`) — **highest priority** (LLM access)
- PyPI token (`pypi-AgEIcHlwaS5vcmc...`)
- Gravatar, Ollama, ADAADchat client secret, ngrok recovery codes
- RSA private keys for ADAADchat GitApp (signing-key.pem and related)

**Actions taken:**
- Revoke/rotate all at source (operator responsibility).
- Removed local key material (e.g. security/keys/signing-key.pem).
- Enhanced `scripts/scan_secrets.py` with explicit rules for `anthropic_claude_key`, `pypi_token`, `gravatar_api_secret`, `adaadchat_client_secret`, etc.
- Updated tests and docs.
- All changes on governed feature branch; preflight gates passed; no main touched.

See also: TRUST_CENTER.md, SECURITY.md, and the project's secret_scan workflow.
