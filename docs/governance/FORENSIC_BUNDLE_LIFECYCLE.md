# Forensic Bundle Lifecycle

Forensic bundles under `reports/forensics/` are immutable evidence exports. Retention and cleanup must preserve auditability.

## Lifecycle invariants

1. Bundles are canonical JSON and immutable after write.
2. Retention decisions are deterministic for a fixed `--now-epoch` input.
3. Cleanup actions are logged append-only to `retention_disposition.jsonl`.

## Retention automation

Use the deterministic helper script:

```bash
# Dry run (no deletion)
python scripts/enforce_forensic_retention.py \
  --export-dir reports/forensics \
  --retention-days 365 \
  --now-epoch 1700000000 \
  --dry-run

# Enforce deletion of expired bundles + append disposition log
python scripts/enforce_forensic_retention.py \
  --export-dir reports/forensics \
  --retention-days 365 \
  --now-epoch 1700000000 \
  --enforce
```

## Operator notes

- `export_metadata.retention_days` (when present) overrides default retention.
- If a bundle cannot be parsed, the script fails closed and performs no deletion.
- Schedule at least daily in production orchestration with explicit timestamp input.


## Optional systemd scheduling

Use the provided units under `ops/systemd/`:

```bash
sudo cp ops/systemd/adaad-forensic-retention.service /etc/systemd/system/
sudo cp ops/systemd/adaad-forensic-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now adaad-forensic-retention.timer
```

The service invokes `ops/systemd/run_forensic_retention.sh`, which passes an explicit epoch timestamp to the deterministic retention script and appends disposition logs.
