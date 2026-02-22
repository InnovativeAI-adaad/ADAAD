# Governance Schema Versioning and Migration Policy

## Scope
This policy governs JSON schemas under `schemas/` that define governance artifacts.

## Dialect and `$id` conventions
- **Single dialect**: all governance schemas MUST use JSON Schema draft 2020-12:
  - `$schema`: `https://json-schema.org/draft/2020-12/schema`
- **Canonical URL-style IDs**: each schema MUST use:
  - `$id`: `https://adaad.local/schemas/<filename>`
- Mixed-draft governance schemas are not permitted in the same major line.

## Versioning rules
- Schema filenames follow `<name>.v<major>.json`.
- Backward-compatible changes are patch/minor changes to content with unchanged filename and `schema_version` const.
- Breaking changes require a new major filename (`.v2.json`, `.v3.json`, ...).
- Existing major versions remain immutable once released, except for correctness fixes that do not broaden accepted payloads.

## Migration policy
- New major schemas MUST ship with:
  - A migration note describing source and target major versions.
  - Deterministic migration logic (no network calls, no time-dependent defaults).
  - Validation coverage in tests for both source and target schemas where applicable.
- Runtime validators MUST continue fail-closed behavior for unknown or malformed payloads.

## Validation gate
- All governance schemas are validated through a single helper path:
  - `runtime/governance/schema_validator.py`
- CI/local check entrypoint:
  - `python scripts/validate_governance_schemas.py`

## Regression prevention
- Any schema change MUST run:
  1. `python scripts/validate_governance_schemas.py`
  2. Relevant test targets covering schema consumers and validators.
- Pull requests that introduce mixed drafts or non-canonical `$id` values must be rejected.


## Release gate semantics migration (strict governance release workflow)
- Releases are now gated by `.github/workflows/governance_strict_release_gate.yml` for governance/public-readiness tag flows.
- Migration impact: release candidates must pass determinism lint, entropy discipline checks, governance strict-mode validation (including rule activation assertions), strict replay validation, and constitution fingerprint stability checks before gate completion.
- Operational expectation: any non-success state in a required strict-release job is release-blocking until resolved; there is no permissive skip path for these checks.
