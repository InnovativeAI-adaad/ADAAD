# Claims-to-Evidence Matrix

This matrix maps major external/public claims to objective, versioned repository artifacts. Release/governance announcements are blocked until every required entry is marked `Complete` with resolvable evidence links.

| Claim ID | External claim | Objective evidence artifacts (must resolve in-repo) | Status |
| --- | --- | --- | --- |
| `ci-status-requirements` | "All required CI checks pass before governance/public-readiness promotion." | [CI workflow definition](../../.github/workflows/ci.yml); [determinism lint workflow](../../.github/workflows/determinism_lint.yml) | Complete |
| `replay-proof-outputs` | "Replay behavior is reproducible and auditable." | [Replay audit boot CI check](../../.github/workflows/ci.yml#L89); [Determinism test suite](../../tests/determinism) | Complete |
| `forensic-bundle-examples` | "Forensic artifacts are available for incident reconstruction." | [Aponi v2 forensics + health model](../governance/APONI_V2_FORENSICS_AND_HEALTH_MODEL.md); [Forensic bundle lifecycle](../governance/FORENSIC_BUNDLE_LIFECYCLE.md) | Complete |
| `codeql-status` | "CodeQL analysis status is published and enforceable." | [CodeQL workflow](../../.github/workflows/codeql.yml) | Complete |
| `versioned-docs-spec-links` | "Public claims are backed by versioned release/spec documentation." | [Versioned release notes](../releases/0.70.0-governance-intelligence.md); [Governance schema versioning spec](../governance/schema_versioning_and_migration.md) | Complete |

## Completion standard

An entry is considered complete only when:

1. Status is exactly `Complete`.
2. Every markdown link in the evidence column resolves to a tracked file path under this repository.
3. Links are specific enough for reviewer verification (no placeholder text such as `TBD`, `TODO`, or `coming soon`).
