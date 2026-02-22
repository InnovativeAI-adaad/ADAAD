# ADAAD Architecture Contract (Layer Ownership)

This contract defines ownership boundaries for high-churn modules and the canonical execution flow.

## Canonical entrypoints

- **Primary platform entrypoint:** `app/main.py` (`python -m app.main`).
- **Canonical runtime adapter root:** `runtime/__init__.py` (exports stable runtime root symbols and import guard setup only).

## Layer dependency model

Allowed dependency direction is downward only:

`ui/app.main -> app/mutation_executor -> adaad/orchestrator -> runtime -> governance`

## Layer ownership

1. **Platform entrypoints** (`app/main.py`)
   - Own process boot, CLI parsing, and top-level mode selection.
   - May wire orchestrator and execution components.

2. **Orchestration / wiring** (`adaad/orchestrator/*`)
   - Own tool registration, dispatch envelopes, and handler routing.
   - Must remain independent from app entrypoints and UI layer.

3. **Pure execution engine** (`app/mutation_executor.py`)
   - Own deterministic mutation execution, scoring handoff, and post-check orchestration.
   - Must stay independent from `app.main` and UI dependencies.

4. **Governance enforcement boundaries** (`runtime/governance/*`, replay/determinism checks in runtime)
   - Own policy, determinism providers, and enforcement primitives.
   - Root-level `governance/` remains compatibility adapter only.

## Forbidden import edges (CI-enforced)

| Scope | Forbidden imports |
| --- | --- |
| `adaad/orchestrator/` | `app`, `ui` |
| `app/mutation_executor.py` | `app.main`, `ui` |
| `runtime/__init__.py` | `app`, `adaad.orchestrator`, `ui` |

Enforcement: `tools/lint_import_paths.py` + tests in `tests/test_lint_import_paths.py`, executed in CI (`.github/workflows/ci.yml`).
Enforcement covers both absolute and relative imports; directory-scoped boundary rules use trailing `/` path scopes.

## Machine-readable lint output

Use `python tools/lint_import_paths.py --format=json` for machine-readable violation output.

| Rule ID | Meaning |
| --- | --- |
| `governance_direct_import` | Direct `governance.*` import from non-allowlisted code |
| `governance_impl_leak` | Implementation logic detected in root `governance/` adapter layer |
| `layer_boundary_violation` | Forbidden cross-layer import from architecture boundary rules |
| `syntax_error` | Python parse failure while linting |
| `unknown` | Violation message has no registered stable rule ID |

## Exception process (required co-update)

Legitimate boundary exceptions require:

1. updating `tools/lint_import_paths.py` boundary rules,
2. updating this document in the same PR,
3. including explicit rationale in PR description.

## Legacy path policy

- Any non-canonical entrypoint-like path is treated as **adapter-only**.
- Adapter modules may re-export or translate interfaces, but must not accumulate new domain logic.


## Deterministic runtime contract (boot enforcement)

For governance-critical replay modes (`audit`/`strict`), boot must enforce:

- root lock artifact: `governance_runtime_profile.lock.json`;
- dependency fingerprint parity for `requirements.server.txt`;
- deterministic provider requirement (`ADAAD_FORCE_DETERMINISTIC_PROVIDER=1`);
- mutable filesystem/network either disabled or explicitly allowlisted by environment contract.

Enforcement path: `runtime.preflight.validate_boot_runtime_profile(...)` called from `app/main.py` during orchestrator boot before runtime initialization.
