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

## Aponi 1.0 dashboard

The Aponi dashboard ships with a FastAPI backend and static front-end for the
ten requested enhancements (trend chart, agent table with source modal,
interactive lineage, promotion/quarantine rollup, mutation diff viewer,
control panel actions, and dark/light themes).

Run locally:

```bash
# 1) Start ADAAD/ADAD so logs exist
python3 -m apps.adad_cli.main

# 2) Backend API (serves /api/*)
uvicorn backend.server:app --reload --port 8088

# 3) Front-end preview (static)
python -m http.server 4173 --directory dashboard
# then open http://localhost:4173
```

GitHub Pages: the static site lives under `dashboard/`. Point Pages to the
repository root (or the `dashboard` folder) to publish without a custom build
step.
