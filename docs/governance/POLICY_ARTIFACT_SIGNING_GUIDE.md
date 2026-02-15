# Policy Artifact Signing Guide

This guide provides a copy-paste-ready deterministic signing flow for `governance_policy_artifact.v1` envelopes.

## Preconditions

- Set the signing secret in environment (never commit plaintext secrets).
- Keep envelope payload deterministic (canonical JSON key ordering).
- Validate schema and signature before deployment.

## Quick signing example

```bash
# 1) Configure signer inputs (example values)
export ADAAD_POLICY_ARTIFACT_SIGNING_KEY='replace-with-kms-exported-secret'
export ADAAD_POLICY_SIGNER_KEY_ID='policy-signer-prod-1'

# 2) Sign existing governance envelope using shell wrapper
./scripts/sign_policy_artifact.sh \
  governance/governance_policy_v1.json \
  governance/governance_policy_v1.signed.json

# 3) Verify the signed artifact with runtime loader (fail-closed)
./scripts/verify_policy_artifact.sh governance/governance_policy_v1.signed.json
```

### Script internals (reference)

The shell wrappers call deterministic runtime signing helpers (`security/cryovant.sign_hmac_digest` + `policy_artifact_digest`) and exist to avoid requiring operators to author Python snippets during incident/deploy windows.

## Deployment

- Promote signed artifact to `governance/governance_policy_v1.json` only after verification succeeds.
- Keep `previous_artifact_hash` chain valid for linear governance history.
- Record operational change control in your environment-specific release process.
