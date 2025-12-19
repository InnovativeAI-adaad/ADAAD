# Changelog

## He65.1.0
- Added ledger-wide `schema_version=1.0` enforcement and required versioned lineage metadata for `meta.json`, `dna.json`, and `certificate.json`.
- Gatekeeper now emits `promotion.rejected` events with rejection reasons and test summary hashes; safe boot keeps mutation disabled and ledger-logs zero-agent states.
- Cryovant is the sole ledger writer; direct writers are blocked and flagged by Doctor; deterministic `ledger_probe` added.
- Doctor verifies schema versions on ledger events and blocks forbidden direct writers; README and branding updated with local assets.
- Breaking: promotions or metadata without schema_version fail validation and Doctor checks.

## He65.0.5
- Enforced canonical top-level roots (no legacy bundles) and strengthened doctor output schema and invariants.

## He65.0.4
- Hardened doctor invariants (canonical tree, forbidden dirs, import hygiene, silent Cryovant probe) and synchronized nexus bootstrap with full required roots.

## He65.0.3
- Initial import of ADAAD He65 tree with canonical governance and bootstrap compliance.

## He65.0.2
- Added introspection endpoints and engine audit.
- Added Cryovant cert-fail metric emission and policy fidelity tests.

## He65.0.1
- Consolidated to Best Core spine. Cryovant-first gate. Policy-enforced sinks. Canonical imports.

## 0.1.0 - initial mobile pack

# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
