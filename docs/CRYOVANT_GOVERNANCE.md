# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Cryovant Governance Specification v2

## Role
Cryovant acts as ADAAD's gatekeeper and governance authority for all agent lifecycle operations.

## Core Requirements
- **Certification First:** Every mutation output is verified via combined digest checks before execution or promotion.
- **Ledger Integrity:** Dual-write to SQLite ledger and JSONL mirror with append-size validation.
- **Quarantine Enforcement:** Failed verifications move artifacts into `security/quarantine` for manual or automated remediation.
- **Lineage Tracking:** Each registry entry records parent identifiers and mutation signatures for ancestry reconstruction.

## Operational Flow
1. Receive candidate payload from Dream Mode or Beast Loop.
2. Verify signatures and structural metadata (`verify_ctc`).
3. Append to ledger and mirror; raise if mirror growth fails.
4. Certify or quarantine using `certify_or_quarantine(payload, signature, artifact_path)`.
5. Emit lineage records to `reports/cryovant.jsonl`.

## Governance Signals
- **Pass:** Candidate is promoted and made available to orchestrator scheduling.
- **Fail:** Candidate is quarantined; Architect Agent produces proposals for repair.

## Security Notes
- Create `security/ledger` and `security/keys` during earth initialization.
- Apply restrictive permissions (chmod 700) in production deployments.
- Maintain mirror and ledger parity checks during scheduled health runs.
