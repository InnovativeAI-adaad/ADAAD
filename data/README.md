# Data (runtime payloads)

This directory holds runtime-generated data:

- `data/logs/` — append-only JSONL logs created at runtime.
- `data/quarantine/` — quarantine artifacts; empty on clean checkouts.

Files here are generated at runtime and are ignored by git; `.gitkeep` files keep
the directory structure intact for boot-time validation.
