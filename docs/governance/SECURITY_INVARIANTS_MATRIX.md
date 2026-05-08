# SPDX-License-Identifier: Apache-2.0
# Security Invariants Matrix

**Last updated:** 2026-03-06 — PR-CI-02 / H-08 closed: SPDX CI enforcement wired and all Python source files verified compliant

This matrix defines mandatory enforcement invariants for governance-critical execution.

---

## Mode / Tier Invariants

| Replay mode | Recovery tier | Deterministic provider | Network surface | Mutation execution |
| --- | --- | --- | --- | --- |
| `off` | `none` | Optional | Policy-configurable | Allowed when gates pass |
| `off` | `advisory` | Recommended | Policy-configurable | Allowed when gates pass |
| `off` | `conservative` | Recommended | Policy-configurable | Reduced mutation rate |
| `off` | `governance` | **Required** | Denied by recovery policy | Fail-closed if governance checks fail |
| `off` | `critical` | **Required** | Denied by recovery policy | Fail-closed / blocked |
| `strict` | any | **Required** | Denied by strict profile | Fail-closed on divergence |

Backward-compatibility alias: `audit` tier is accepted for deterministic-provider enforcement.

---

## Authentication / Signature Invariants

1. Governance bearer tokens must be cryptographically verifiable (`cryovant-gov-v1`).
2. `CRYOVANT_DEV_TOKEN` override accepted only in explicit dev mode (`ADAAD_ENV=dev` + `CRYOVANT_DEV_MODE`).
3. Payload-bound `cryovant-static-*` signatures accepted only in explicit dev mode.
4. Governance certifier decisions are binding on `import_ok`, `token_ok`, `ast_ok`, and `auth_ok`.
5. **[PR-HARDEN-01]** `ADAAD_ENV` must be a known value at boot; unknown values raise `RuntimeError` in `env_mode()` and `SystemExit` in the boot guard — no silent fallback.
6. **[PR-HARDEN-01]** `CRYOVANT_DEV_MODE` is rejected in `staging`, `production`, and `prod` environments at startup.
7. **[PR-HARDEN-01]** `ADAAD_GOVERNANCE_SESSION_SIGNING_KEY` must be present in strict environments; missing key raises `SystemExit` before any service initialization.

---

## Federation Trust Invariants

1. **[PR-SECURITY-01]** Federation message signatures are verified against `governance/federation_trusted_keys.json` — caller-supplied public keys are never accepted.
2. Any `key_id` not present in the trusted registry raises `FederationTransportContractError`.
3. Registry changes require a governance-impact PR with ≥2 reviewer approvals.
4. Registry is loaded at process start; boot fails closed if the registry is unreadable or empty.

See [FEDERATION_KEY_REGISTRY.md](FEDERATION_KEY_REGISTRY.md) for the key rotation runbook.

---

## Sandbox / Execution Invariants

1. **[C-02 / Phase 0]** Sandbox preflight rejects tokens containing shell control operators: `&&`, `||`, `;`, `|`, `` ` ``, `$(`, `${`, `>`, `<`, `<<`.
2. **[C-02]** IFS word-splitting bypass patterns (`$IFS`, `${IFS}`) are blocked at token-analysis time.
3. **[C-02]** Shell evaluation primitives (`eval `, `exec `, `source `) are blocked.
4. **[C-02]** Null-byte injection (`\x00`, `%00`) is blocked.
5. **[C-02]** Disallowed environment keys include: `LD_PRELOAD`, `PYTHONINSPECT`, `LD_LIBRARY_PATH`.
6. Individual command tokens exceeding 512 bytes are rejected as `oversized_command_token`.

---

## Audit Visibility Invariants

- `boot_env_validated` metric emitted on every clean startup.
- `cryovant_legacy_static_payload_signature_rejected` emitted on blocked legacy signatures.
- `cryovant_legacy_static_payload_signature_accepted` emitted on accepted dev-only static signatures.
- `cryovant_missing_signing_key_strict_env` emitted when signing key is absent in strict env.
- Certifier violations include explicit reason-codes for token and code-scan failures.

---

## SPDX / License Compliance Invariants

- All Python source files carry the exact `# SPDX-License-Identifier: Apache-2.0` header within the first six physical lines. Mixed Python SPDX identifiers are not allowed; `MIT`, proprietary `LicenseRef-*`, and compound expressions fail closed.
- Enforced by `scripts/check_spdx_headers.py`; run with `--fix` to replace conflicting header identifiers or add the required header.
- **[PR-CI-02 / H-08]** `spdx-header-lint` CI job in `.github/workflows/ci.yml` runs on every push and PR — finding H-08 closed 2026-03-06.

---

## Related Documents

- [FEDERATION_KEY_REGISTRY.md](FEDERATION_KEY_REGISTRY.md) — key pinning lifecycle
- [DETERMINISM_CONTRACT_SPEC.md](DETERMINISM_CONTRACT_SPEC.md) — replay determinism guarantees
- [STRICT_REPLAY_INVARIANTS.md](STRICT_REPLAY_INVARIANTS.md) — strict replay enforcement
- [RED_TEAM_THREAT_MODEL_NEXT_PHASE.md](RED_TEAM_THREAT_MODEL_NEXT_PHASE.md) — threat surface

---

## Phase 6 — Roadmap Self-Amendment Security Invariants

Registered by `PR-PHASE6-01` (ArchitectAgent · `ARCHITECT_SPEC_v3.1.0.md`). Effective v3.1.0.

### Authority Invariants

1. **[Phase6-SEC-01]** `authority_level` on every `RoadmapAmendmentProposal` is hardcoded to
   `"governor-review"` in `RoadmapAmendmentEngine.propose()`. This field is never injected by
   the caller. Any proposal record with a different value raises `GovernanceViolation` on load.
2. **[Phase6-SEC-02]** A governor ID must appear in at most one approval record per proposal.
   Double-approval raises `GovernanceViolation` — constitutional fault, not a warning.
3. **[Phase6-SEC-03]** `diff_score` is computed by `_score_amendment()` exclusively. A caller-
   supplied `diff_score` field that diverges from the recomputed value raises `GovernanceViolation`.
4. **[Phase6-SEC-04]** `roadmap_amendment` is a reserved `mutation_type` value. No agent may
   create a mutation payload of this type except via `RoadmapAmendmentEngine.propose()`.

### Storage and Filesystem Invariants

5. **[Phase6-SEC-05]** Proposal files in `runtime/governance/roadmap_proposals/` are governed
   by the `ADAAD_MUTABLE_FS_ALLOWLIST`. The `proposals_dir` path must be within the allowlist
   at boot. Any proposal write to a path outside the allowlist raises `RuntimeError`.
6. **[Phase6-SEC-06]** A proposal file may be overwritten only by `RoadmapAmendmentEngine._persist()`
   to advance its own status. External writes to proposal files are constitutionally prohibited.

### Human Sign-Off Invariants

7. **[Phase6-SEC-07]** No automated path exists from `ProposalStatus.APPROVED` to a ROADMAP.md
   commit. The human operator must execute the edit. No CI job, bot, or merge automation bypasses
   this gate. Violation triggers `FL-ROADMAP-SIGNOFF-V1` blocking rule in Founders Law.
8. **[Phase6-SEC-08]** `verify_replay()` must be executed and pass on every proposal before it is
   referenced in a PR merge message or CHANGELOG entry. A failed replay proof blocks merge. Result
   written to ledger as `roadmap_amendment_committed` with `replay_proof_status = "fail"` halts.

### Anti-Manipulation Invariants

9. **[Phase6-SEC-09]** The M6-03 anti-storm gate (`M6G-04`, `M6G-05`) prevents proposal queue
   flooding. `EvolutionLoop` checks `list_pending()` before emitting; check result stored in
   `EpochTelemetry`. A pending proposal count > 0 suppresses emission silently.
10. **[Phase6-SEC-10]** `ADAAD_ROADMAP_AMENDMENT_TRIGGER_INTERVAL` values < 1 are rejected at
    boot with `ValueError`. The value is read once at epoch start and immutable for that epoch.

### Federated Amendment Invariants

11. **[Phase6-SEC-11]** Federated roadmap amendment proposals must carry HMAC signatures using
    the same key registry contract as Phase 5 federation (`governance/federation_trusted_keys.json`).
    An unsigned or improperly signed federated roadmap proposal is rejected at the receiver.
12. **[Phase6-SEC-12]** Source node approval of a federated roadmap amendment does NOT bind
    destination nodes. Each peer's `GovernanceGate` evaluates independently. Each peer's human
    sign-off gate is non-delegatable.

### Audit Visibility (Phase 6 Extension)

- `roadmap_amendment_proposed` emitted on every `propose()` call regardless of outcome.
- `roadmap_amendment_determinism_divergence` emitted on every `verify_replay()` failure.
- `roadmap_amendment_human_signoff` emitted by the human operator gate before ROADMAP.md is written.
- All Phase 6 events participate in the evidence ledger hash chain — retroactive modification
  of any event invalidates all subsequent chain entries.
