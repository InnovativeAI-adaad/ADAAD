# Contributing to ADAAD (He65)

## Governance and ledger rules

- Cryovant (`security/cryovant.Cryovant`) is the only permitted ledger writer. **Do not** call `security/ledger/ledger.py` or write directly to `security/ledger/events.jsonl`.
- All ledger events must carry `schema_version = 1.0` (see `security/schema_versions.py`). Unknown or missing versions are rejected.
- Lineage metadata (`meta.json`, `dna.json`, `certificate.json`) must include `schema_version = 1.0` and remain immutable once promoted.

## Development workflow

- Keep agent metadata in `app/agents/active/` versioned; use the templates in `app/agents/agent_template/`.
- Run the Doctor (`python scripts/he65_doctor.py`) before committing; it is the canonical ship gate.
- Add new logging via the structured logger (`runtime/logger.py`); `print()` is forbidden in `app/` and `runtime/`.

## Branding

- Preserve the InnovativeAI LLC branding and footer text across README, Aponi surfaces, and Doctor output.
