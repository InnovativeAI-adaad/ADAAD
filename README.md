# ADAAD (He65 layout)

This repository now surfaces the full He65 ADAAD implementation at the repo
root. It includes Cryovant gatekeeping, append-only telemetry, the
architect/dream/beast orchestration loops, and a lightweight Aponi dashboard.

## Key layout

- `app/` — Wood/Fire: orchestrator entry (`app/main.py`), architect scan,
  dream/beast cycles, agent contract and samples.
- `runtime/` — Earth: invariants, metrics, capability graph, warm pool, root
  paths.
- `security/` — Water: Cryovant gatekeeping and append-only ledger under
  `security/ledger/`.
- `ui/` — Metal: Aponi dashboard (`ui/aponi_dashboard.py`) for state/metrics/
  lineage tails.
- `data/` — runtime data (capabilities, work inbox, etc.).
- `reports/` — append-only JSONL metrics (`reports/metrics.jsonl`).
- `tests/` — unit tests for orchestrator, Cryovant, fitness, capabilities.
- `archives/`, `releases/`, `experiments/`, `brand/`, `tools/`, `scripts/` —
  packaged assets, helpers, and historical material.

## Running the orchestrator

Use Python 3.11+:

```bash
python -m app.main
```

This will:

- Run invariants and element registration.
- Validate Cryovant environment and certify agents via the ledger
  (`security/ledger/lineage.jsonl`).
- Discover architect/dream/beast workloads under `app/agents/`.
- Start the Aponi dashboard on port 8080 for live state/metrics/lineage tails.

Metrics are written to `reports/metrics.jsonl`; ledger events live under
`security/ledger/` and are generated at runtime (ledger JSONL files are not
tracked in git).

Cryovant notes:

- Bundled `cryovant-dev-*` certificates are trusted by default when no signing
  keys are configured (the repo ships only dev certs).
- Set `CRYOVANT_DEV_MODE=1` to explicitly allow dev signatures if you introduce
  custom verification, or wire up `verify_signature` for production keys to
  tighten enforcement.

## Dashboard-only run

If you just want the Metal dashboard without booting the full orchestrator, run
from the repo root so imports resolve:

```bash
python ui/aponi_dashboard.py --host 127.0.0.1 --port 8080
```

You can also set `APONI_HOST` / `APONI_PORT` instead of CLI flags. Endpoints:
`/state`, `/metrics`, `/fitness`, `/capabilities`, `/lineage`, `/mutations`,
`/staging`.

## Tests

Run the suite from the repo root:

```bash
python -m pytest
```
