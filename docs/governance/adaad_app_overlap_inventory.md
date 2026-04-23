# ADAAD/App Overlap Inventory

## Canonical Namespace

`adaad/` is the canonical implementation namespace for agents, orchestrator modules, and governance API entrypoints.
`app/` is retained only for compatibility shims during migration.

## Overlap Inventory

### Agents

- Canonical: `adaad/agents/*`
- Legacy shim layer: `app/agents/*` (re-export + `DeprecationWarning`)

### Orchestrator

- Canonical: `adaad/orchestrator/{adaad_trigger,boot_config,cli_handlers,contracts,dork_intent_router,mutation_orchestration_service,replay_preflight,runtime_factory}.py`
- Legacy shim layer: `app/orchestration/*` (re-export + `DeprecationWarning`)

### Governance entrypoints

- Canonical: `adaad/api/governance.py`
- Legacy shim layer: `app/api/governance.py` (re-export + `DeprecationWarning`)

## Release-cycle removal plan

1. Maintain shims for one release cycle while telemetry tracks usage.
2. Enforce a CI guard that blocks non-shim logic in `app/` compatibility modules.
3. Remove deprecated `app/` compatibility modules after one release cycle with zero shim usage.
