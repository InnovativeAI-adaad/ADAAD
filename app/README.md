# Wood + Fire (app)

The app layer orchestrates boot order and creative/evaluative cycles. Architect (Wood) scans agents for required metadata, while Dream and Beast (Fire) run mutation and evaluation loops. All operations must honor Cryovant gating and log to `reports/metrics.jsonl`.


## Canonical entrypoint contract

- Canonical platform entrypoint: `python -m app.main` (`app/main.py`).
- `app/mutation_executor.py` is the pure execution engine and should remain UI/entrypoint agnostic.
- `adaad/orchestrator/*` is orchestration/wiring only. Any direct `app.main` coupling is forbidden.
- Legacy module-level compatibility paths are adapter-only and must not grow business logic.
- See `docs/ARCHITECTURE_CONTRACT.md` for ownership and enforcement boundaries.


### Enforcement

These constraints are enforced by `tools/lint_import_paths.py` (rule id: `layer_boundary_violation`) and the always-on CI job `import-boundary-lint`.
Relative imports that resolve to forbidden modules are also blocked.

Legitimate exceptions require updating both `tools/lint_import_paths.py` and `docs/ARCHITECTURE_CONTRACT.md` in the same PR with rationale.
