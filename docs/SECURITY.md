# Cryovant Key Handling

- `security/keys/` is created automatically on first run by Cryovant; if you need to provision it manually, run `mkdir -p security/keys` before setting owner-only permissions (`chmod 700 security/keys`).
- Do not commit private keys to version control.
- Ledger writes are recorded in `security/ledger/lineage.jsonl` and mirrored to `reports/metrics.jsonl`.
