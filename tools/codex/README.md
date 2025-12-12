Codex execution pipeline (He65)

Scope
- Codex is a tool. It lives under tools/.
- Codex does not bypass Cryovant.
- Codex does not write directly to security/keys/ or security/ledger/.

Job contract
- Input: one JSON object (CodexJob).
- Output: one JSON object (CodexResult).
- Patch format: unified diff.

Stages (emitted to reports/metrics.jsonl)
- CODEX_PLAN
- CODEX_GENERATE_DIFF
- CODEX_APPLY_DIFF
- CODEX_VALIDATE_IMPORTS
- CODEX_SANDBOX_TEST
- CODEX_CRYOVANT_CERT (placeholder, orchestrator-owned)
- CODEX_PROMOTE (placeholder, orchestrator-owned)

Run
python -m tools.codex.runner --job path/to/job.json

Notes
- If CodexJob.diff is empty and no --diff is provided, CODEX_GENERATE_DIFF fails with CODEX_NO_DIFF.
- This pipeline clones a scratch repo subset into runtime/tmp/codex/<task_id>/repo and runs tests there.
