# Reports (append-only metrics)

All metrics and capability events are appended to JSONL files in this directory
at runtime (e.g., `reports/metrics.jsonl`). These files are generated and
ignored by git; `.gitkeep` keeps the directory present for boot-time checks.
