# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Dream Mode Evolution Protocol

## Purpose
Dream Mode performs controlled, sandboxed mutations that feed ADAAD's evolutionary pipeline.

## Execution Model
- Uses `SandboxExecutor` with CPU and memory rlimits to isolate tasks.
- Supports direct mutation via `mutate()` and file-level mutation via `mutate_file()`.
- Integrates with Beast Loop for scheduled workloads.

## Governance Hooks
- All mutation outputs route to Cryovant for certification before promotion.
- Architect Agent governance sweeps follow each mutation to ensure structural compliance.
- Warm-pool responsiveness and uptime are monitored through runtime logs and metrics.

## Metrics
- Records mutation success/failure traces in `reports/metrics.jsonl`.
- Captures sandbox execution latency for fitness calculations.
- Emits failure signatures to aid retries or quarantines.

## Future Enhancements
- AST-aware mutation strategies.
- Bandit/UCB1 scheduling for adaptive task selection.
- Stress scoring to rank candidate survivability.
