# Earth (runtime)

The runtime element owns invariant checks, metrics, warm-pool infrastructure, capability registry, and root paths. It must initialize before any other element. All metrics and capability events are logged to `reports/metrics.jsonl` and persisted under `data/`.


## Canonical import paths

- Authoritative governance foundation modules live in `runtime/governance/foundation/`.
- Authoritative evolution governance helpers live in `runtime/evolution/` (`scoring.py`, `promotion_state_machine.py`, `checkpoint.py`).
- `governance/` at repo root is compatibility-only and must re-export runtime implementations rather than duplicate logic.

Deterministic replay-sensitive entry points now consume a shared provider abstraction from `runtime/governance/foundation/determinism.py` for UTC clock access and ID/token generation.

- Epoch checkpoint registry/verifier: `runtime/evolution/checkpoint_registry.py`, `runtime/evolution/checkpoint_verifier.py`.
- Entropy enforcement primitives: `runtime/evolution/entropy_detector.py`, `runtime/evolution/entropy_policy.py` with declared+observed telemetry accounting and per-epoch durable entropy totals.
- Entropy observability helper: `runtime/evolution/telemetry_audit.py` (`get_epoch_entropy_breakdown`).
- Hardened sandbox isolation primitives: `runtime/sandbox/{executor,policy,manifest,evidence,isolation,preflight}.py` with strict pre-exec enforcement preparation (seccomp/capability/resource profiles) and deterministic preflight blocking before test execution (missing sandbox syscall telemetry is fail-closed).
- Lineage replay integrity now distinguishes two paths: verified replay digests (chain-integrity prevalidated) for strict/production checks, and explicit unverified forensic digest recomputation for tamper analysis workflows.
- Strict replay determinism requires deterministic providers; audit tier enforcement also requires deterministic providers to preserve forensic replay value.
- Strict replay invariants reference: `docs/governance/STRICT_REPLAY_INVARIANTS.md` (verified vs unverified digest policy, provider requirements, and replay-equivalence guarantees).
- Federation coordination primitives: `runtime/governance/federation/` provides deterministic policy version exchange, quorum/consensus decision recording, conflict reconciliation actions, and explicit local-vs-federated governance precedence for replay attestation checks.

- Deterministic promotion simulation runner: `runtime/evolution/simulation_runner.py` with CI entrypoint `scripts/run_simulation_runner.py` (machine-readable canary verdicts; no mutation side effects).

- Canonical governance event taxonomy and normalization live in `runtime/governance/event_taxonomy.py`; UI and analytics consumers should normalize mixed legacy/new event strings through this helper before classification.

- Sandbox hardening guidance: `docs/sandbox/README.md`.

- Replay attestation bundles: `runtime/evolution/replay_attestation.py` builds deterministic `security/ledger/replay_proofs/<epoch>.replay_attestation.v1.json` files, signs them with configured key metadata via `security/cryovant.py` deterministic key-resolution helpers, and exposes offline verification helpers used by Aponi replay endpoints.

- Forensic evidence bundles: `runtime/evolution/evidence_bundle.py` exports canonical immutable bundles with signed export metadata (`digest`, `retention_days`, `access_scope`, signer fields), validates against `schemas/evidence_bundle.v1.json`, and fails closed on malformed evidence/schema inputs.

- Governance signing guide: `docs/governance/POLICY_ARTIFACT_SIGNING_GUIDE.md` (deterministic signing + verification workflow, including `scripts/sign_policy_artifact.sh` and `scripts/verify_policy_artifact.sh`).
- State persistence toggle: governance policy payload now supports `state_backend` (`json` default, optional `sqlite`) for deterministic registry/ledger persistence through `runtime/state/` stores with parity checks and JSON→SQLite migration helpers.
- Forensic retention lifecycle: `docs/governance/FORENSIC_BUNDLE_LIFECYCLE.md` (`scripts/enforce_forensic_retention.py` dry-run/enforce operations + optional `ops/systemd/adaad-forensic-retention.timer`).
- Federation incident response: `docs/governance/FEDERATION_CONFLICT_RUNBOOK.md`.

- Founders-law governance model implementation for federation compatibility: `runtime/governance/founders_law_v2.py` (`docs/governance/founders_law_v2.md`).


## Determinism and boundary enforcement

- Governance-critical paths (`runtime/governance/`, `runtime/evolution/`, `runtime/autonomy/`, `security/`) are enforced by `tools/lint_determinism.py` as a primary verification gate in `scripts/verify_core.py` and `scripts/verify_core.sh`.
- The determinism lint blocks dynamic execution/import primitives (`eval`, `exec`, `compile`, `__import__`, `importlib.import_module`) including importlib alias forms.
- Runtime import boundary blocking uses a PEP 451 `MetaPathFinder`/loader (`runtime/import_guard.py`) and is only activated in explicit strict/test contexts (`ADAAD_RUNTIME_IMPORT_GUARD=strict|test`, `ADAAD_REPLAY_MODE=strict`, or test execution), so normal runtime imports remain unaffected by default.
