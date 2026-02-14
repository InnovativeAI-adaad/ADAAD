# Hardened Sandbox Isolation

This module defines deterministic sandbox governance for mutation test execution.

## Enforcement layers
- **Syscall allowlist**: `runtime.sandbox.syscall_filter`
- **Filesystem write-path allowlist**: `runtime.sandbox.fs_rules`
- **Network egress allowlist**: `runtime.sandbox.network_rules`
- **Resource quotas**: `runtime.sandbox.resources`

## Determinism and replay
- `HardenedSandboxExecutor` builds deterministic manifests from mutation identity + replay seed and enforces policy using observed sandbox telemetry.
- `TestSandbox` supplies inferred deterministic baseline telemetry (`open/read/write/close`, `reports`) when direct tracing is unavailable; missing syscall telemetry is treated fail-closed by the hardened executor.
- Evidence fields are canonically hashed (`manifest_hash`, `stdout_hash`, `stderr_hash`, `syscall_trace_hash`, `resource_usage_hash`, `evidence_hash`).
- Evidence is appended to an append-only JSONL ledger (`security/ledger/sandbox_evidence.jsonl`).
- Replay helper `runtime.sandbox.replay.replay_sandbox_execution` verifies this canonical contract from persisted fields (`manifest`, `stdout`, `stderr`, `syscall_trace`, `resource_usage`).

## Integration
- `MutationExecutor` routes test execution through `HardenedSandboxExecutor`.
- `SandboxEvidenceEvent` is appended to lineage and aggregated by checkpoint registry.
