# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Codex Briefing — Phase V: Recursive Evolution

- Meta-mutation: `app/dream_mode/meta_mutator.py` tracks mutation operator sets, rates, and emits fingerprints.
- Evolution Kernel: `app/evolution/kernel.py` centralizes pacing, strategy pools, and fail-rate boundaries with a persisted fingerprint at `reports/evolution_kernel.json`.
- Cryovant policy law: signatures now include optional `policy_hash` and `kernel_hash` fields and log entries to `reports/policy_evolution.jsonl`.
- Architect system auditor: governance sweeps now flag missing kernel/meta state and export `system_proposals_*.json` files.
- Aponi meta view: `/meta` endpoint surfaces kernel snapshots, meta-mutator state, and policy evolution lines for operator review.
