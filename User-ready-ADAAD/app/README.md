# app

Element: WOOD + FIRE

This directory contains the orchestrator spine, the Architect agent, and the mutation engines.
It must remain small, explicit, and testable.

## Responsibilities

WOOD (Architect Growth)
  - Structural audits
  - Canonical path normalization checks
  - Governance proposal generation
  - “Keep/Move/Refactor/Delete” decisions based on metrics and policy

FIRE (Mutation Engine)
  - Dream Mode: exploration engine
  - Beast Mode: exploitation engine
  - Mutation loops must be gated by Cryovant

## Required files

app/main.py
  - single source of truth for system startup
  - sets boot order
  - initializes Cryovant and policy context
  - registers engines in an explicit ENGINES registry

app/architect_agent.py
  - quick_scan() must run during boot
  - may read repo structure and reports
  - must not mutate or promote agents directly

app/dream_mode.py
  - exploration engine
  - must not run unless Cryovant gate passes

app/beast_mode_loop.py
  - exploitation engine
  - must not run unless Cryovant gate passes

app/agents/
  - agent contract, builtin agents, lineage store

## Invariants

1) No engine starts before EARTH and WATER are initialized.
2) No Dream/Beast loops run unless Cryovant.gate_cycle() returns True.
3) No module writes to disk without passing security.policy.evaluate().
4) All telemetry goes to reports/metrics.jsonl via the orchestrator metric sink.

## Engine protocol expectation

Engines are expected to be lifecycle-safe:
  - enable()
  - disable()
  - shutdown()
  - background loop methods must exit promptly when disabled

The orchestrator owns scheduling. Engines must not self-spawn untracked threads.

## Canonical imports

Allowed:
  from app ...
  from runtime ...
  from security ...
  from ui ...

Forbidden:
  - from .. or import .. style relative imports
  - importing non-canonical directories
  - absolute filesystem imports

## Policy and Cryovant

All external effects must be routed through security policy and Cryovant utilities.
If a feature needs to write state, it must call policy first, then write via a governed helper.

## Android constraints

Keep dependencies minimal.
Avoid heavy packages in core orchestration.
Prefer standard library and small, explicit modules.
