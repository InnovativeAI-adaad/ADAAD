# ADAAD

ADAAD — Autonomous Device-Anchored Adaptive Development. This repository
contains a lightweight, Android-friendly core with append-only telemetry,
a safe sandbox runner, and a promotion/quarantine pipeline modeled after
ADAAD's Beast Mode flows.

## Layout

- `adad_core/` — core modules (IO, evaluation, cryovant, evolution, runtime)
- `adad_core/agents/` — built-in agents ready for evaluation
- `apps/adad_cli/` — CLI entry point for one evaluation cycle
- `scripts/` — helper scripts for local runs and log syncing
- `data/` — append-only metrics, fitness, and lineage logs (created at runtime)

## Quick start

Run a single evaluation cycle (respects CPU/battery gates):

```bash
./scripts/run_local.sh
```

Execute the fast unit tests:

```bash
pytest
```

## Notes

- Logging is append-only JSONL to stay deterministic and mobile-friendly.
- Cryovant signature helpers use SHA-256/HMAC without extra dependencies.
- The sandbox uses stdlib `runpy` with minimal surface area.
