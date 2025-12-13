# tools

Tools are auxiliary pipelines.
They can generate proposals, run sandboxes, and validate diffs.
They are not allowed to own promotion or certification.

## Governance boundaries

1) Tools must not write to security/keys/ or security/ledger/.
2) Tools may emit metrics to reports/metrics.jsonl.
3) Tools may validate allowed_paths/forbidden_paths for their own operation.
4) Tools must not bypass policy enforcement in core modules.

## Codex

tools/codex is a smoke-test oriented pipeline.
It records stage events to reports/metrics.jsonl.
Cryovant certification and promotion remain orchestrator-owned and must be marked as skipped.
