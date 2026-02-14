# Contributing

By submitting a contribution, you agree that your work is licensed under the Apache License, Version 2.0 (see `LICENSE`). No trademark rights are granted or implied; see `TRADEMARKS.md` and `BRAND_LICENSE.md`.

## Expectations
- Follow existing code style and keep SPDX headers in source files.
- Do not include brand assets (`brand/`) in code or release artifacts.
- Keep dependencies documented and compatible with the existing tooling.

## How to contribute
1. Fork and create a topic branch.
2. Add tests for functional changes.
3. Run the test suite for the affected areas.
4. Submit a pull request describing the change and its impact.

## Starter example
- Run the minimal single-agent loop: `python examples/single-agent-loop/run.py`.
- Read the walkthrough in `examples/single-agent-loop/README.md` for expected staged lineage and ledger/metrics checkpoints.

## Metrics payload sensitivity
- Treat metrics payloads as potentially exposed operational telemetry.
- Do **not** log secrets, credentials, tokens, full environment dumps, or raw command lines that may include sensitive values.
- Use allowlisted, minimal fields (status, counts, booleans, durations, and explicitly safe identifiers).
- Keep JSONL entries single-line UTF-8 records to preserve parseability under concurrent writes.
