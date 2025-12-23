# Cryovant Key Handling

- Keep `User-ready-ADAAD/security/keys/` readable only by the owner (`chmod 700 security/keys`).
- Do not commit private keys to version control.
- Ledger writes are recorded in `User-ready-ADAAD/security/ledger/lineage.jsonl` and mirrored to `reports/metrics.jsonl`.
