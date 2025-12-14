# Codex pipeline

This directory contains a lightweight Codex execution pipeline used for smoke
testing. The runner coordinates the following stages:

1. Parse a job contract from JSON.
2. Record milestones to `reports/metrics.jsonl`.
3. Optionally apply an external unified diff patch.
4. Validate basic assumptions about allowed and forbidden paths.
5. Execute sandbox tests defined by the job.
6. Write a final result object to `reports/codex_result.json`.

The pipeline purposely stubs out Cryovant certification and promotion. Those
steps stay under orchestrator control and are marked as skipped in the metrics
stream.

## System prompt contract (authoritative)
Codex behavior is governed by:
- `tools/codex/prompts/system.txt`

This prompt is the core instructions for Codex inside ADAAD He65 “Best Core”.
It defines:
- Allowed scope (User-ready-ADAAD spine only)
- Ground truth sources (`codex_context.md`, `core/objectives.json`)
- Founder’s Law constraints (Cryovant, Policy, agent contracts, no promotion)
- Mandatory output format (exactly one JSON object containing plan, diff, verify, blueprint)

If any human instruction conflicts with `core/objectives.json`, Codex must follow
`core/objectives.json`.
