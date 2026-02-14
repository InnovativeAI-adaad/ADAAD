# Changelog

## [Unreleased]

### Added
- Verbose boot diagnostics strengthened with replay mode normalization echo, fail-closed state output, replay score output, replay summary block, replay manifest path output, and explicit boot completion marker.
- `QUICKSTART.md` expanded with package sanity checks and first-time strict replay baseline guidance.
- Governance surfaces table in README and architecture legend in `docs/assets/architecture-simple.svg`.
- Bug template field for expected governance surface to accelerate triage.

### Changed
- README clarified staging-only mutation semantics for production posture.
- CONTRIBUTING now requires strict replay verification for governance-impact PRs and adds determinism guardrails.

## 0.65.0 - Initial import of ADAAD He65 tree

- Established canonical `User-ready-ADAAD` tree with five-element ownership (Earth, Wood, Fire, Water, Metal).
- Added Cryovant gating with ledger/keys scaffolding and certification checks to block uncertified Dream/Beast execution.
- Normalized imports to canonical roots and consolidated metrics into `reports/metrics.jsonl`.
- Introduced deterministic orchestrator boot order, warm pool startup, and minimal Aponi dashboard endpoints.
