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

Codex behavior is governed by a single system prompt file:

- `tools/codex/prompts/system.txt`

This file is the governing contract for Codex inside ADAAD He65 “Best Core”.
It defines:

- Allowed scope: the `User-ready-ADAAD` spine only.
- Ground truth sources: `codex_context.md` and `core/objectives.json`.
- Founder’s Law constraints: Cryovant gates, Policy, agent contracts, and
  the rule that Codex never promotes or deploys directly.
- Required output format: exactly one JSON object with `plan`, `diff`,
  `verify`, and `blueprint` keys, and no extra text.

Codex must treat `core/objectives.json` as authoritative over any human prompt.
If a human instruction conflicts with `core/objectives.json`, Codex is required
to follow `core/objectives.json` and may describe the conflict in its `plan`
field.

The orchestrator is responsible for:

- Staging Codex output as a `BlueprintProposal` under `reports/proposals/`.
- Running the verification commands declared in `verify.commands`.
- Applying or quarantining the proposed diff under Cryovant governance.
