# ADAAD Strategic Build Suggestions

This document defines a conservative, safety-first build strategy for ADAAD.
It is intentionally aligned with ADAAD's deterministic, fail-closed governance
model and is designed to improve delivery confidence without changing runtime
behavior, public APIs, or governance contracts.

> **Living document:** this strategy is grounded in the Deep Dive Audit
> (baseline commit `0df3d3f`, 2026-03-02), the Strategic Change PR Plan
> (19 PRs · 4 phases), and the IP Valuation Report (February 2026).
> Update this document whenever the audit or PR plan changes materially.

---

## Executive Direction

ADAAD build strategy optimizes for four invariants, in priority order:

1. **Deterministic reproducibility** — same input commit → same governed outcome.
2. **Governance integrity** — no path bypasses constitutional controls.
3. **Audit-grade evidence** — machine-readable artifacts + operator-readable summaries.
4. **Operational clarity** — fast, scoped diagnosis when gates fail.

---

## Safety-Critical Baseline Assumptions

- ADAAD is safety-critical by default.
- Fail-closed behavior is mandatory for contract, determinism, and security failures.
- Public APIs and schemas are compatibility-managed; drift must be explicit and versioned.
- Documentation is part of the control plane: behavior changes require docs and runbooks
  in the same change set.
- All hardening work targets **canonical** implementation surfaces. Specifically:
  - Session/governance token validation → `security/cryovant.py` (not `runtime/governance/auth/`)
  - Boot env validation → `app/main.py`
  - Any PR targeting deprecated paths is rejected in review.

---

## Version Alignment Baseline

| Reference | Value |
| --- | --- |
| Version source of truth | `VERSION` file (currently `1.0.0`) |
| Stable release notes baseline | `docs/releases/1.0.0.md` |
| Governance closure target | `v1.1-GA` → `docs/governance/ADAAD_7_GA_CLOSURE_TRACKER.md` |
| Audit baseline commit | `0df3d3f7a3befe91faf6b327505a8f3e9ae31d49` (2026-03-02) |

Build and documentation changes must keep these references synchronized to prevent
operator ambiguity during release gating.

---

## Build Architecture: Control Lanes

Use explicit quality lanes so failures are scoped and triage is deterministic.
Every lane has a named owner who responds when the gate fails.

| Lane | Primary objective | Canonical controls | Fail policy |
| --- | --- | --- | --- |
| **Contract** | Preserve interface/governance contracts | `scripts/validate_governance_schemas.py`, `scripts/validate_architecture_snapshot.py`, policy artifact validation | Fail closed; no merge |
| **Determinism** | Preserve replay and state transition parity | `scripts/verify_core.py` / `scripts/verify_core.sh`, `tools/lint_determinism.py` (covers `runtime/` + `adaad/orchestrator/`) | Fail closed; no merge |
| **Security** | Preserve artifact authenticity and key hygiene | `scripts/verify_critical_artifacts.py`, `scripts/validate_key_rotation_attestation.py`, signature/attestation checks | Fail closed; no merge |
| **Secret-scanning** | Prevent credential/key leakage in commits | Committed tool config (`.gitleaks.toml` or `.trufflehog.yml`) + dedicated CI workflow on all PRs; config drift is gated identically to governance schema drift | Fail closed; no merge |
| **Evidence** | Preserve release auditability | `scripts/validate_release_evidence.py`, `scripts/validate_release_hardening_claims.py`, checklist conformance | Fail closed for release branches |
| **Documentation** | Preserve operator comprehension and implementation alignment | `scripts/validate_readme_alignment.py`, `scripts/validate_architecture_snapshot.py` | Fail closed for protected branches |

> **Lane ownership rule:** each lane must have an identified owner (name or team)
> recorded in a committed `docs/governance/LANE_OWNERSHIP.md`. Lane ownership
> is a Phase 1 deliverable, not optional documentation.

---

## Existing Repository Controls Mapped to Lanes

| Script / Workflow | Lane | Purpose | Status |
| --- | --- | --- | --- |
| `scripts/validate_governance_schemas.py` | Contract | Validate governance schema conformance | Present |
| `scripts/validate_architecture_snapshot.py` | Contract / Documentation | Detect architecture-contract drift | Present |
| `scripts/verify_core.py` / `scripts/verify_core.sh` | Determinism | Validate core deterministic/governance invariants | Present |
| `tools/lint_determinism.py` | Determinism | AST lint for non-deterministic calls in `runtime/` and `adaad/orchestrator/` | Present |
| `scripts/verify_critical_artifacts.py` | Security | Verify required critical artifacts exist | Present |
| `scripts/validate_key_rotation_attestation.py` | Security | Enforce key rotation attestation integrity | Present |
| `scripts/validate_release_evidence.py` | Evidence | Validate release evidence completeness | Present |
| `scripts/validate_readme_alignment.py` | Documentation | Ensure README/docs align with implementation | Present |
| `.github/workflows/determinism_lint.yml` | Determinism | Path-scoped determinism lint in CI | Present; **use as template for risk-tier routing in Phase 3** |
| `.github/workflows/governance_strict_release_gate.yml` | Evidence / Release | Strict gate for governance/public-readiness tags | Present |
| `.github/workflows/post_merge_doc_sync.yml` | Documentation / Evidence | Enforce post-merge roadmap/procession/release/evidence sync contract | Present |

---

## Recommended Gate Order

Run gates in this order to maximize early failure and assurance depth:

1. **Contract lane** — reject interface/policy drift earliest.
2. **Determinism lane** — reject replay and invariant regressions.
3. **Security lane** — reject authenticity and key integrity failures.
4. **Secret-scanning lane** — reject credential/key leak risk before merge.
5. **Evidence + Documentation lanes** — reject incompleteness and operator drift.
6. **Packaging/signing** — only after all governance lanes pass.

---

## Implementation Roadmap

> **Sequencing note:** Roadmap phases are synchronized to the Strategic Change
> PR Plan phases. Do not advance a window without closing prerequisite PRs
> per the dependency-safe merge sequence in `ADAAD_DEEP_DIVE_AUDIT.md §8`.
>
> | Roadmap phase | PR Plan phase | Core PRs |
> | --- | --- | --- |
> | Phase 1 (0–30 days) | P0 + hardening PRs | PR-01–04, PR-CI-01/02, PR-HARDEN-01, PR-LINT-01 |
> | Phase 2 (31–60 days) | P1 | PR-05–09, PR-SECURITY-01, PR-OPS-01 |
> | Phase 3 (61–90 days) | P2 + P3 | PR-10–19, PR-PERF-01, PR-DOCS-01 |

### Phase 1 — Foundation Hardening (0–30 days)

**Goal:** eliminate environment-induced failures; establish lane model; close all 🔴 critical audit findings.

- **Python version pin** (`PR-CI-01`): pin all CI workflows to `python-version: "3.11.9"` (exact patch). `ci.yml` uses 3.11; `ci-generated.yml` uses 3.10.14 — divergence is a determinism risk.
- **SPDX header enforcement** (`PR-CI-02`): add CI step that fails closed if new Python files lack `# SPDX-License-Identifier: Apache-2.0`.
- **Determinism lint coverage** (`PR-LINT-01`): add `adaad/orchestrator/` to `TARGET_DIRS` and `ENTROPY_ENFORCED_PREFIXES` in `tools/lint_determinism.py`. Orchestrator dispatch envelopes feed mutation audit records and are replay-sensitive.
- **Boot environment validation** (`PR-HARDEN-01` / `C-01`): in `security/cryovant.py` and `app/main.py`, reject startup when `ADAAD_ENV` is unset or outside canonical enum `{dev, staging, production}`; staging/production must reject `CRYOVANT_DEV_MODE` tokens unconditionally and assert expiry even in dev.
- **Governance signing key boot assertion** (`H-02`): if `ADAAD_ENV != dev` and neither `ADAAD_GOVERNANCE_SESSION_KEY_<KEY_ID>` nor `ADAAD_GOVERNANCE_SESSION_SIGNING_KEY` is set, fail closed with `missing_governance_signing_key:critical`. Log `governance_signing_key_source` metric at boot.
- **Sandbox preflight injection fix** (`C-02`): replace substring-only `_DISALLOWED_TOKEN_FRAGMENTS` check in `runtime/sandbox/preflight.py::analyze_execution_plan` with structured token allowlisting + pattern validation. Add `${IFS}`, `$IFS`, `eval `, `exec `, `source `, `\x00`, `%00` to fragment list; add per-token length cap (`_MAX_TOKEN_LENGTH = 4096`).
- **Write-path allowlist validation** (`H-03`): add `_validate_write_allowlist()` in `runtime/sandbox/preflight.py` — reject non-absolute paths and any entry containing `..`. Fail closed before processing mounts.
- **Federation key pinning** (`C-03` / `PR-SECURITY-01`): implement `runtime/governance/federation/key_registry.py`; reject federation messages whose `$.signature.key_id` is not in `governance/federation_trusted_keys.json`. Fail closed on unreadable or empty registry.
- **Lineage ledger O(n) fix** (`C-04` / `PR-PERF-01`): maintain `_verified_tail_hash` in `LineageLedgerV2`; skip full re-scan on every `append_event()`. Implement streaming line-by-line verification in `verify_integrity()` to prevent OOM on large ledgers.
- **Secret-scanning workflow**: commit `.gitleaks.toml` (or `.trufflehog.yml`) and a dedicated GitHub Actions workflow; add as required branch-protection check for all mergeable PRs.
- **Formalize lane ownership**: publish `docs/governance/LANE_OWNERSHIP.md` mapping each lane to an owner.
- **Standardize gate output formatting** for deterministic triage.
- **Lock CI/runtime baselines** (toolchain/version pinning beyond Python).
- **Enforce policy/schema validation** for all governance-surface changes.
- **Ensure release artifacts include deterministic metadata** (runtime version, policy hash, schema/version set).

**Expected result:** all 🔴 critical audit findings closed; no environment-induced CI failures; lane model operational.

---

### Phase 2 — Contract-First Delivery (31–60 days)

**Goal:** close 🟠 high audit findings; establish compatibility snapshots; rationalize release gates.

- **CI timeout hardening** (`M-03`): add `timeout-minutes: 3` to the `classify` job in `ci.yml` to prevent hung jobs from blocking all dependent work.
- **Snapshot atomicity** (`M-02` / `PR-OPS-01`): in `runtime/recovery/ledger_guardian.py`, write snapshot files to `<snapshot_id>.tmp/` staging then atomic `os.rename()` to `<snapshot_id>/`; add `snapshot_complete` sentinel; `get_latest_valid_snapshot` must use `creation_sequence` from `metadata.json` (not `st_mtime`) for ordering.
- **Federation HMAC key validation** (`M-05`): at federation subsystem initialization, assert `len(ADAAD_FEDERATION_MANIFEST_HMAC_KEY) >= 32`; emit `federation_hmac_key_weak` boot warning and fail closed when federation mode is enabled.
- **Federation HMAC key rotation runbook**: document rotation procedure for `ADAAD_FEDERATION_MANIFEST_HMAC_KEY` in `docs/governance/FEDERATION_KEY_REGISTRY.md`. Absence of this runbook is a `v1.1-GA` **No-Go** criterion.
- **Release gate rationalization**: converge `governance_strict_release_gate.yml` and legacy `release_evidence_gate.yml` (currently scoped only to the `v0.70.0` tag) into one canonical release gate surface for all future milestones.
- **Orchestrator lazy-import resolution** (`H-04`): evaluate whether `runtime/api/__init__.py` lazy import via `importlib.import_module` in `__getattr__` is necessary; if retained, add it to `ENTROPY_ALLOWLIST` in `lint_determinism.py` with explicit rationale comment.
- **Split CI output by lane** with clear ownership labels and structured diagnostics.
- **Add compatibility snapshots** for key API/schema outputs.
- **Require explicit migration notes** whenever a governed contract changes.
- **Enforce branch protection** requiring all applicable lanes to pass.
- **Require invariant notes** in PR templates for mutation/governance logic changes.
- **Establish weekly reporting** for strategy scorecard metrics.

**Expected result:** all 🟠 high audit findings closed; mean time to diagnose gate failures reduced; release gate surface unified.

---

### Phase 3 — Risk-Tiered Scaling (61–90 days)

**Goal:** increase throughput without weakening governance guarantees; close remaining medium findings.

- **Risk-tier routing**: classify PRs by change surface; route checks accordingly:
  - docs-only: lightweight docs alignment checks only
  - runtime/governance: full contract + determinism + security + evidence stack
  - Risk tier path triggers **must** be defined in committed workflow config, mirroring the path-scope pattern in `.github/workflows/determinism_lint.yml`. Prose-only tier definitions are non-deterministic and not permitted.
- **Red-team evidence retention policy** (`M-06`): add configurable retention (`ADAAD_REDTEAM_EVIDENCE_RETENTION_DAYS`, default 90) and automated rotation for `reports/redteam/`. Add a size-cap sentinel; fail nightly harness if cap is exceeded without operator acknowledgment.
- **API rate limiting** (`H-06`): add token-bucket rate limiter at `POST /api/mutations/proposals` (`ADAAD_PROPOSAL_RATE_LIMIT`, default 10 req/min per source IP); emit `governance_proposal_rate_limited` ledger event on breach.
- **Metrics fan-out**: implement `MetricsSink` abstraction with JSONL + stdout backends; add optional OpenTelemetry export.
- **Test isolation**: add `pytest` fixture patching all canonical ledger/filesystem paths to `tmp_path` equivalents.
- **Error budget tracking**: add `ADAAD_ERROR_BUDGET_WINDOW` config counting fail-closed decisions over a rolling window; alert when budget threshold is exceeded.
- **Signed release-candidate provenance bundles** as first-class build outputs.
- **Periodic replay audits** against archived evidence bundles.
- **Tune risk-tier routing** with observed false-positive/false-negative data.
- **Import path linter improvement** (`M-01`): add `# adaad: import-boundary-ok:<reason>` inline suppression with audit log, plus `--fix` mode for obvious violations.

**Expected result:** higher throughput; all 🟡 medium audit findings closed; governance guarantees unchanged.

---

## Value Acceleration Gates

The following build milestones directly affect ADAAD's commercial and IP value
positioning (grounded in IP Valuation Report, February 2026). Each requires
passing the full contract + determinism + evidence stack before being considered
complete — they are not separate from the lane model.

| Lever | Required build action | Value impact |
| --- | --- | --- |
| **Any revenue** | Validate `GET /economic/market-fitness` (PR-04); confirm Aponi dashboard reflects real AppStore/Analytics signal (PR-03) | Single largest valuation lever: transitions income approach from speculative to grounded; potential 2× base case |
| **ADAAD-7 shipment** | Close PR-05 (Reviewer Reputation Ledger) + PR-06 (Scoring Engine) + PR-07 (Tier Calibration) + PR-08 (Advisory Rule) + PR-09 (Aponi Panel) with full ledger events and constitutional floor | Demonstrates roadmap execution; introduces feedback loop enterprise buyers require; material acquirer pricing signal |
| **Patent filing readiness** | Prepare constitutional mutation governance method documentation as a standalone IP artifact, reviewable by IP counsel before `v1.1-GA` | Transforms governed source assets into defensible novel IP; qualitative shift in how acquirers price the asset |
| **Governance Key Ceremony** (PR-01) | Execute 2-of-3 Ed25519 signature threshold; write `governance/attestations/canonical_engine_declaration.json` | Converts the canonical engine declaration from a document to a governance event; required for any enterprise audit presentation |

---

## Governance Change Protocol

### Mandatory implementation sequencing for governed mutation work

When change sets touch planning/governance mutation execution, the implementation
sequence is mandatory and must run in-order:

1. taxonomy + annotation
2. duplicate assertion audit/merge
3. constitutional-domain split
4. endpoint parametrization
5. full verification

Additional controls:
- Each sequence step lands as an isolated commit to preserve rollback safety.
- Governance checks must block steps (2)-(4) whenever taxonomy coverage is incomplete.
- Final validation must report both a full-suite pass summary and an
  `autonomous_critical` lane pass summary before completion.


When changing mutation or governance execution logic, require all of the following
in the same PR:

- **Rationale:** what risk or failure mode is being addressed.
- **Canonical path verification:** confirm the PR targets active implementation surfaces, not deprecated paths (see Safety-Critical Baseline Assumptions above).
- **Invariants:** explicit preconditions/postconditions + fail-closed fallback behavior.
- **Determinism proof path:** replay verification checks showing no unintended divergence (run locally before PR open):
  ```bash
  ADAAD_ENV=dev CRYOVANT_DEV_MODE=1 \
  ADAAD_FORCE_DETERMINISTIC_PROVIDER=1 \
  ADAAD_DETERMINISTIC_SEED=ci-strict-replay \
    python -m app.main --verify-replay --replay strict
  ```
- **Operator impact note:** runbook/doc updates describing changed expectations.
- **Merge sequencing discipline:** when multiple hardening PRs are open, follow the dependency-safe sequence:
  ```
  1. PR-CI-01        (Python version pin)         — no deps
  2. PR-CI-02        (SPDX enforcement)            — no deps
  3. PR-LINT-01      (orchestrator determinism)    — no deps
  4. PR-HARDEN-01    (boot env validation)         — no deps
  5. PR-SECURITY-01  (federation key pinning)      — depends on transport.py audit
  6. PR-PERF-01      (streaming lineage verify)    — no deps
  7. PR-OPS-01       (snapshot atomicity)          — no deps
  8. PR-DOCS-01      (federation registry docs)    — depends on PR-OPS-01
  ```
  Out-of-sequence merges on security/determinism surfaces require explicit PR justification and lane-owner sign-off.

---


## Phase 5 canonical PR IDs (alignment note)

For all planning, review, and release-gating references, Phase 5 uses the canonical **3-PR merged-scope** sequence:

1. `PR-PHASE5-01`
2. `PR-PHASE5-02`
3. `PR-PHASE5-03`

Legacy references to `PR-PHASE5-04` or `PR-PHASE5-05` are superseded and should be interpreted as scope now folded into `PR-PHASE5-03`. Canonical control lives in `docs/governance/ADAAD_PR_PROCESSION_2026-03.md`.

---

## Evidence Lane Output Contract

Evidence updates are mandatory in the same change set as any hardening or
capability item:

- The corresponding row in `docs/comms/claims_evidence_matrix.md` must be
  appended or updated in the same PR.
- `python scripts/validate_release_evidence.py --require-complete` is the
  enforcement gate for release-grade completeness.
- Missing evidence updates for completed controls are treated as release-readiness blockers.

**Pending evidence rows** (to be added upon PR completion):

| Claim ID | External claim | Evidence artifacts | Pending |
| --- | --- | --- | --- |
| `federation-key-pinning` | Federation messages accepted only from registered, trusted key IDs | `governance/federation_trusted_keys.json`; `runtime/governance/federation/key_registry.py`; `tests/governance/federation/test_key_registry.py` | PR-SECURITY-01 |
| `boot-env-validation` | ADAAD rejects startup with unknown or misconfigured env values | `security/cryovant.py` boot guard; `app/main.py`; `tests/test_boot_env_validation.py` | PR-HARDEN-01 |
| `streaming-ledger-verification` | Lineage ledger integrity verification does not require full-file memory load | `runtime/evolution/lineage_v2.py` streaming verifier | PR-PERF-01 |
| `spdx-header-compliance` | All Python source files carry SPDX license headers, enforced in CI | `.github/workflows/ci.yml` spdx-header-lint job; `scripts/check_spdx_headers.py` | PR-CI-02 |
| `sandbox-injection-hardening` | Sandbox preflight rejects word-splitting bypasses and oversized tokens | `runtime/sandbox/preflight.py` allowlist + pattern validator; `tests/test_preflight_injection.py` | C-02 inline fix |
| `snapshot-atomicity` | Ledger snapshots are written atomically with creation-sequence ordering | `runtime/recovery/ledger_guardian.py` atomic rename + sentinel | PR-OPS-01 |

---

## Release Evidence Expectations

A release candidate must contain both machine and human evidence:

- Machine-readable validation outputs (schema checks, core verification, critical artifact checks).
- Policy/signature provenance metadata.
- Deterministic environment metadata (Python pin, toolchain versions, policy hash).
- Operator-facing release summary and checklist outcome references.
- For `v1.1-GA` specifically:
  - `GateCertifier.passed` requires `token_ok` in `runtime/governance/gate_certifier.py`.
  - No production caller depends on deprecated `verify_session(...)` in `security/cryovant.py`.
  - Federation HMAC key rotation runbook exists and is validated by security owner.
  - Patent filing readiness artifact reviewed by IP counsel.

---

## Operational Metrics (Strategy Scorecard)

| Metric | Target | Reporting cadence |
| --- | --- | --- |
| Reproducibility rate (same commit, same outcome) | 100% | Per release |
| Mean time to deterministic failure diagnosis | < 15 min | Weekly |
| Merge-block cause distribution by lane | Tracked (no target — visibility metric) | Weekly |
| Release evidence completeness score | 100% before GA | Per release candidate |
| Replay drift incidents per release window | 0 | Per release |
| % of behavior-changing PRs with synchronized docs/runbook | 100% | Weekly |
| Error budget (fail-closed decisions per rolling window) | < threshold (configurable) | Daily when `ADAAD_ERROR_BUDGET_WINDOW` set |

---

## Decision Rubric for Accepting Build-System Changes

Accept a build-system or process change only if **all** are true:

- It does not weaken fail-closed governance behavior.
- It preserves existing contracts or introduces an explicit versioned migration.
- It improves determinism, security, evidence quality, or diagnosability.
- It includes rollback steps and operator-documentation alignment.
- It has an identified lane owner who responds when the gate fails.
- It targets canonical implementation surfaces (not deprecated paths).

---

## Recommended Next Actions

1. Ratify this strategy as the canonical build-hardening baseline.
2. Publish `docs/governance/LANE_OWNERSHIP.md` mapping lanes to owners.
3. Open hardening PRs in dependency-safe sequence (see Governance Change Protocol above).
4. Add pending claims-evidence rows as PRs complete.
5. Review metrics weekly; adjust only with evidence-backed changes.
6. Prepare patent filing readiness artifact before `v1.1-GA` tag.
