# Hardened Sandbox Isolation

This module defines deterministic sandbox governance for mutation test execution.

## Enforcement layers
- **Syscall allowlist**: `runtime.sandbox.syscall_filter`
- **Filesystem write-path allowlist**: `runtime.sandbox.fs_rules`
- **Network egress allowlist**: `runtime.sandbox.network_rules`
- **Resource quotas**: `runtime.sandbox.resources`

## Determinism and replay
- `HardenedSandboxExecutor` builds deterministic manifests from mutation identity + replay seed.
- Evidence fields are canonically hashed (`manifest_hash`, `stdout_hash`, `stderr_hash`, `syscall_trace_hash`, `evidence_hash`).
- Evidence is appended to an append-only JSONL ledger (`security/ledger/sandbox_evidence.jsonl`).
- Replay helper `runtime.sandbox.replay.replay_sandbox_execution` verifies recorded hashes against deterministic reconstruction inputs.

## Integration
- `MutationExecutor` routes test execution through `HardenedSandboxExecutor`.
- `SandboxEvidenceEvent` is appended to lineage and aggregated by checkpoint registry.
