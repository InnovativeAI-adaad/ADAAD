# Phase 108 Plan — INNOV-23: Constitutional Epoch Sentinel

## Objective
Deliver **INNOV-23 (Constitutional Epoch Sentinel)** as a governed phase increment with deterministic implementation sequencing, constitutional gate coverage, and release evidence alignment.

## Dependency Chain
- Immediate predecessor: **Phase 107** (must be merged before any Phase 108 source writes).
- Innovation lineage: `INNOV-22` → `INNOV-23` per `docs/governance/PHASE_INNOVATION_MAPPING_CANONICAL.md` (Phase 107 → 108).
- Release dependency: target version **v9.41.0** follows predecessor semantic progression.
- Deterministic next-PR linkage: `state_alignment.expected_next_pr` resolves to `Phase 108` only when Phase 107 status is `shipped`.

## Invariants
- **HUMAN-0**: non-delegable governor sign-off required for phase ratification and release promotion.
- **REPLAY-0**: identical inputs produce identical governance and replay outputs.
- **GATE-0**: governance gate remains sole promotion authority.
- **PHASE-108-SEQ-0**: predecessor linkage is explicit and linear (`Phase 107` → `Phase 108`).
- **EVIDENCE-108-0**: no closure without complete claims-evidence row and resolvable artifacts.

## Tier Classification (Gate Applicability)
- **Tier 0 (always-on baseline):** required preflight and per-file verification.
- **Tier 1 (standard gate stack):** full test suite, governance tests, artifact verification, evidence validation.
- **Tier 2 (escalated):** required (critical governance/runtime innovation surface).
- **Tier 3 (PR completeness):** required (evidence row, docs/runbook alignment, CI tier declaration, lane declaration).
- **Tier M (merge-specific):** required only under `DEVADAAD` trigger.

## Acceptance Tests
- Phase-specific pytest module(s) covering innovation behavior and failure-mode assertions.
- Determinism and replay verification for all new ledger/reasoning paths.
- Governance invariant tests proving HUMAN-0 and gate ordering are preserved.
- Regression check: no pre-existing failures introduced versus base SHA.

## Evidence Artifacts Required
- `artifacts/governance/phase108/track_a_sign_off.json`
- `artifacts/governance/phase108/replay_digest.txt`
- `artifacts/governance/phase108/tier_summary.json`
- `docs/comms/claims_evidence_matrix.md` row updated to `Complete` for Phase 108 / INNOV-23.

## HUMAN-0 Checkpoints
1. **Plan ratification checkpoint:** governor approves this plan before PR open.
2. **Pre-merge checkpoint:** governor validates gate stack summary and evidence completeness.
3. **Release checkpoint:** governor records signed ledger attestation for `v9.41.0`.
