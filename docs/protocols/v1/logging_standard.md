# Protocol v1.0: Structured Logging Standard

## Mandate (Stability-First)
1. No direct use of `print()` in `runtime/` or `app/`.
2. All logs must be structured JSON lines (JSONL).
3. Rotation occurs at 5MB.
4. Callers must redact secrets before logging.

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

