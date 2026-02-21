# Protocol v1.0: Structured Logging Standard

## Mandate (Stability-First)
1. `app/`, `runtime/`, and `security/` are operational modules: direct `print()` is forbidden; route status through configured loggers.
2. `tools/` is the CLI presentation layer: direct `print()` to stdout/stderr is allowed for user-facing output.
3. Enforce this distinction via `python tools/lint_determinism.py runtime/ security/ app/main.py` (`forbidden_direct_print`).
4. All logs must be structured JSON lines (JSONL).
5. Rotation occurs at 5MB.
6. Callers must redact secrets before logging.

## Canonical Schema
```json
{
  "ts": "ISO-8601 Timestamp",
  "lvl": "INFO|ERROR|DEBUG|AUDIT",
  "cmp": "Component Name",
  "msg": "Human readable message",
  "ctx": { "any": "extra fields" }
}
```
