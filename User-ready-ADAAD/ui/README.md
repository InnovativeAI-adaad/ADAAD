# ui

Element: METAL

UI is refinement and visibility. It must not own governance or mutation.
Default posture is read-only.

## Responsibilities

1) Read-only dashboards
  - metrics viewer
  - health log viewer
  - ledger viewer

2) Operator visibility
  - surface current state without modifying it
  - help audit policy decisions and mutation behavior

## Aponi dashboard

ui/aponi_dashboard.py provides endpoints:
  /metrics -> reports/metrics.jsonl
  /health  -> reports/health.log
  /ledger  -> security/ledger/events.jsonl

The UI must not write to:
  - security/ledger/
  - security/keys/
  - app/agents/

Promotion and certification remain orchestrator-owned.

## Dependency note

Flask is optional.
If Flask is not installed in the runtime environment, the UI server should not be started.
Core system functionality must not depend on UI.
