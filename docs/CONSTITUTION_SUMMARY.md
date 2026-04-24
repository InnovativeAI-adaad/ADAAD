# SPDX-License-Identifier: Apache-2.0
# ADAAD — Constitutional Summary
**Version:** v0.9.0 · **Hard-class invariants:** 263 (cumulative, enforced) · **Last updated:** 2026-04-24

> This document is the human-readable entry point to ADAAD's constitutional framework.
> Machine-readable sources are canonical:
> - `runtime/governance/constitution.yaml` — rule definitions
> - `governance/constitutional_rule_count.json` — versioned rule count
> - `docs/CONSTITUTION.md` — full constitutional text

---

## What the Constitution Is

ADAAD's Constitution is a versioned, cryptographically-gated ruleset that governs every
mutation the system proposes or executes. It cannot be bypassed, mocked, or hot-patched
at runtime. Every evolution cycle is subordinate to it.

The Constitution does three things:

1. **Blocks** mutations that violate invariants before they touch production code
2. **Logs** every decision — pass or fail — to a tamper-evident, HMAC-chain-linked ledger
3. **Requires human ratification** (HUMAN-0 GPG signature) for any Tier 0 change or
   constitutional amendment

---

## Three-Tier Authority Model

| Tier | Scope | Mutation authority | Rollback |
|------|-------|-------------------|----------|
| **Tier 0 — Production** | `runtime/`, `security/`, `app/main.py`, orchestrator core | HUMAN-0 only — never auto-executed | Manual, GPG-attested |
| **Tier 1 — Stable** | `tests/`, `docs/`, most agents | Auto-execute; human reviews logs within 24 h | Automatic on test failure |
| **Tier 2 — Sandbox** | `app/agents/test_subject/` | Fully autonomous | Automatic; blast-radius contained |

---

## Constitutional Gating Flow

Every proposed mutation traverses this sequence. Failure at any gate is fail-closed —
the mutation is rejected; the rejection is ledgered; no partial state leaks.

```
  Proposal
      │
      ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ Step 1 · ArchitectAgent — goal alignment, tier classification   │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ Step 2 · DreamAgent — mutation design, entropy budget check     │
  │          SCDD drift scan · TIFE multi-epoch pre-validation      │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ Step 3 · BeastAgent — implementation; AST validity; SPDX check  │
  │          no banned tokens (eval/exec); single-file scope        │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ Step 4 · ACSE — ≥ 5 adversarial vectors per invariant class;   │
  │          boundary stress; replay interference; seed-pinned      │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ Step 5 · AFRT (Red-Team Agent) — adversarial fitness gate;     │
  │          AFRT-GATE-0, AFRT-INTEL-0, AFRT-LEDGER-0              │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ Step 6 · GovernanceGate v2 — final constitutional check;       │
  │          signature_required; lineage_continuity;                │
  │          resource_bounds; federation_dual_gate (if federated)   │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
                     ┌─────────────┴──────────────┐
                     │ Tier 0?                     │
                   YES │                           NO │
                     ▼                              ▼
             ┌────────────────┐         ┌──────────────────────┐
             │  HUMAN-0 GPG   │         │  Auto-execute (T1/T2) │
             │  ratification  │         │  Ledger entry written │
             │  required      │         └──────────────────────┘
             └────────────────┘
```

---

## Hard-Class Invariant Categories (263 total)

Hard-class invariants are enforced at the code level. Violation = blocked mutation + ledger event.

| Category | Count | Representative invariants |
|----------|------:|--------------------------|
| Constitutional core | 16 | `single_file_scope`, `ast_validity`, `no_banned_tokens`, `signature_required`, `lineage_continuity` |
| Adversarial / red-team | 12 | `ACSE-0`, `ACSE-1`, `AFRT-0`, `AFRT-GATE-0`, `AFRT-DETERM-0`, `BIRC-0` |
| Temporal / TIFE | 5 | `TIFE-0`, `CES-0`, `TIFE-SIMULATION-NONDETERMINISTIC` |
| Determinism | 18 | `AFRT-DETERM-0`, `MGV-DETERM-0`, `MIRROR-DETERM-0`, `ACSE-SEED-NONDETERMINISTIC` |
| Federation | 7 | `federation_dual_gate`, `federation_hmac_required`, `FGCON-0`, `KBEP-VERIFY-0` |
| Governance & audit | 22 | `GOV-SOLE-0`, `COMMUNITY-HUMAN0-0`, `REPLAY-ALGO-0`, `TEST-ATTEST-0` |
| Evolution engine | 47 | `SPIE-0..HUMAN0-0`, `DSTE-0..6`, `GDA-0..4`, `IDE-0..GATE-0` |
| Entropy & safety | 14 | `entropy_budget_limit`, `max_mutation_rate`, `resource_bounds`, `CEB-0..4` |
| DORK / UX | 19 | `DFLEET-0..4`, `DFSB-0..4`, `CLI-SANDBOX-0`, `RAGS-DISPATCH-0` |
| CSI / Strength Index | 8 | `CSI-SCORE-0`, `CSI-DECAY-0`, `CSI-GATE-0` |
| Other / module-specific | 95 | Per-module invariants introduced across Phases 87–159 |

> Canonical count is machine-derived from `runtime/governance/constitution.yaml`.
> This table is illustrative; do not hard-code totals in downstream tooling.

---

## HUMAN-0 Non-Delegable Actions

The following actions are permanently reserved for the cryptographic key-holder
(Dustin L. Reid, Innovative AI LLC). No agent, CI step, or automation may perform them.

| Action | Mechanism |
|--------|-----------|
| Tier 0 ratification | GPG tag on release commit |
| Constitutional amendment | Signed HUMAN-0 attestation + CEL review |
| GA version promotion | GPG-signed git tag on ADAADell |
| Key ceremony execution | Physical operation on ADAADell |
| PR creation for protected branches | `gh` CLI on ADAADell |
| F-Droid MR submission | Manual submission with signed artefact |

---

## Constitution Version History

| Version | Notable change | Date |
|---------|---------------|------|
| v0.1.0 | Initial 9-rule set | 2025-01 |
| v0.3.0 | Federation rules added (`federation_dual_gate`, `federation_hmac_required`) | 2026-01 |
| v0.9.0 | Current — 23 named rules + 263 hard-class invariants | 2026-04 |

---

## Verification

To verify any ledger produced by this system:

```bash
python verify_ledger.py data/evolution_ledger.jsonl
```

Exit 0 = chain intact. Exit 1 = tampered record at position N (position reported).

To reproduce any epoch deterministically:

```bash
python -m app.main --replay strict --seed <EPOCH_SEED> --verbose
```

---

*This summary is maintained by DEVADAAD and ratified by HUMAN-0 on each constitutional version bump.*
*GPG-signed releases: see git tags `v{major}.{minor}.{patch}` — each carries a signed commit.*
