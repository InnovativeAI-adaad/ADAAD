# ADAAD UX Enhancement Plan

## Objective

Improve first-run confidence and real-time visibility while preserving deterministic governance behavior.

## Delivered UX package

1. **Enhanced Live Dashboard** (`ui/enhanced/enhanced_dashboard.html`)
   - Live status cards (system, mutation cycle, replay mode, determinism)
   - Activity stream with event classification
   - Governance pipeline stage visualization
   - Mutation and lineage panels
   - 2-second polling cadence against read-only API endpoints

2. **Enhanced CLI** (`tools/enhanced_cli.py`)
   - Rich terminal banner and configuration summary
   - Stage timing and completion reporting
   - Delegates to `python -m app.main` (no orchestration logic replacement)

3. **Error Dictionary** (`tools/error_dictionary.py`)
   - Structured categories (`setup`, `configuration`, `governance`, `replay`, `mutation`, `system`, `network`)
   - Rich formatted diagnostics with actionable command hints
   - Lookup + heuristic suggestion + `handle_adaad_error` decorator

4. **Interactive Onboarding** (`tools/interactive_onboarding.py`)
   - Guided 8-step setup flow
   - Validation checks with retry support
   - Platform-specific setup hints

## Safety and invariants

- No mutation authority added.
- No governance bypass introduced.
- Existing public APIs and governance flow are unchanged.
- UI and tooling remain observer/operator focused.
- Tooling uses Python standard library only.


## Runtime update strategy

- Enhanced dashboard now attempts a WebSocket-first live update channel (`ws://<host>:8080/ws`) when available.
- If unavailable, it falls back deterministically to 2-second polling.
- Onboarding now checks port availability, disk space, git integrity, and minimum package imports.
- Enhanced CLI parses orchestrator output in real time to complete stage markers.
