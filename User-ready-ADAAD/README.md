# ADAAD He65 Best Core

This repository is the canonical, minimal “Best Core” spine for ADAAD He65.
It enforces Founder’s Law (Five-Element alignment), canonical imports, and Cryovant-first governance.

## Canonical directory spine

User-ready-ADAAD/
  app/          # WOOD + FIRE
  runtime/      # EARTH
  security/     # WATER
  ui/           # METAL
  data/
  reports/
  docs/
  tests/
  scripts/
  tools/
  releases/
  experiments/
  archives/

No new top-level directories may be added without updating the spine spec and imports.

## Five-Element alignment

EARTH (Core Runtime) = runtime/
  - bootstrap, health, scheduling, concurrency pools

WOOD (Architect Growth) = app/architect_agent.py
  - structural audits, planning, governance proposals, tree normalization rules

FIRE (Mutation Engine) = app/dream_mode.py and app/beast_mode_loop.py
  - exploration vs exploitation engines

WATER (Registry Memory) = security/cryovant.py and security/ledger/
  - certification, ancestry, append-only ledger, policy enforcement

METAL (Refinement/UI) = ui/aponi_dashboard.py
  - read-only visibility into system state and metrics

## Canonical import rules

Only these import roots are allowed:
  from app ...
  from runtime ...
  from security ...
  from ui ...
  from data ...
  from reports ...

Forbidden patterns:
  - absolute filesystem paths in imports or strings
  - relative package imports (from .., import ..)
  - importing from legacy folders or non-canonical roots

## Boot order and gating

Boot order is deterministic:
  1) EARTH: runtime bootstrap (dirs + logging)
  2) WATER: Cryovant init + ledger write test + key permissions lock
  3) WOOD: Architect quick scan
  4) FIRE: Dream/Beast only if Cryovant gate passes
  5) METAL: UI readers only, never write by default

Hard gate:
  Dream/Beast cycles must not run unless Cryovant validates agent ancestry and required directories.

## Governance rules (non-negotiable)

1. Cryovant is the gatekeeper. No bypass.
2. No direct writes to security/ledger/ or security/keys/ outside Cryovant helpers.
3. All external side effects must pass security.policy.evaluate().
4. No direct edits inside mutation engine without review.
5. All evolution logs must append to reports/metrics.jsonl.
6. No non-canonical imports. No absolute path imports.
7. Agents must live under app/agents/ and carry meta.json, dna.json, certificate.json.
8. Offspring must be written into app/agents/lineage/.
9. UI is read-only by default. Promotion and certification stay orchestrator-owned.
10. Tests must keep the system bootable on Android (Pydroid3/Termux).

## Runtime outputs

reports/health.log
  - boot and health lines

reports/metrics.jsonl
  - append-only events and stage metrics

security/ledger/events.jsonl
  - Cryovant append-only ledger events

## How to run

From repository root:
  python -m app.main

If running tests:
  python -m compileall app runtime security ui tests
  pytest -q

## UI

ui/aponi_dashboard.py is a read-only Flask server.
It is allowed to read:
  - reports/metrics.jsonl
  - reports/health.log
  - security/ledger/events.jsonl

It must not write state by default.

## Versioning

VERSION contains the He65 semantic version.
CHANGELOG.md records notable changes and architecture transitions.
