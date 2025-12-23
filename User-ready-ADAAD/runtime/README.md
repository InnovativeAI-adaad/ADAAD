# Earth (runtime)

The runtime element owns invariant checks, metrics, warm-pool infrastructure, capability registry, and root paths. It must initialize before any other element. All metrics and capability events are logged to `reports/metrics.jsonl` and persisted under `data/`.
