# experiments

Experiments are disposable.
They exist to validate hypotheses quickly and then be promoted into canonical modules or deleted.

Rules:
  - no new top-level dirs inside repo
  - no non-canonical imports
  - no direct writes to security/keys or security/ledger
  - log results to reports/metrics.jsonl

Promotion path:
  experiment -> proposal -> reviewed diff -> canonical module
