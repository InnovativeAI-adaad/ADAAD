# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Runtime Resilience Rules

## Health-First Boot
- `runtime/boot.py` enforces structure checks and writes `reports/health.json`.
- Mutation remains disabled until required directories exist and Cryovant paths are writable.

## Earth Initialization
- `runtime/earth_init.py` initializes Cryovant registry paths under `security/`.
- Recommended to set restrictive permissions for keys and ledger directories.

## Logging
- `runtime/logging.py` appends event records to `runtime/logs/events.jsonl` for boot, mutation, and certification milestones.

## Warm-Pool Policy
- Sandbox workers should retain restored rlimits between tasks to prevent resource leakage.
- Executor pools must be monitored for responsiveness; recycle threads on repeated failures.

## Failure Mitigation
- Block mutation cycles when health indicators fail.
- Quarantine uncertified artifacts and run Architect governance sweeps before retrying.
- Track uptime and sandbox latency to detect regression trends.
