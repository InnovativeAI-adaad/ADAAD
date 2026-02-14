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
- Hardened sandbox isolation primitives: `runtime/sandbox/{executor,policy,manifest,evidence}.py` (missing sandbox syscall telemetry is fail-closed).
- Lineage replay integrity: replay digest paths verify ledger hash-chain integrity before reads; strict replay divergence emits governance fail-closed decisions that block further promotion validation.

- Sandbox hardening guidance: `docs/sandbox/README.md`.
