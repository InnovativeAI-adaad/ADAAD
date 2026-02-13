# Single-Agent First Loop (Minimal Runnable Example)

This example runs a tiny ADAAD loop with **one agent** and a constrained `dream_scope`.

## Run

```bash
python examples/single-agent-loop/run.py
```

## What it does

1. Creates a disposable workspace at `examples/single-agent-loop/.run/`.
2. Writes one `solo-agent` with `dream_scope.allow=["mutation"]`.
3. Certifies that single agent through Cryovant.
4. Runs one Dream cycle (discovery + staging + dream manifest).
5. Runs one Beast cycle (fitness + promotion decision).

After execution, inspect:

- `examples/single-agent-loop/.run/agents/lineage/` for staged/promoted mutation bundles.
- `security/ledger/lineage.jsonl` for `ancestry_validated` and `mutation_promoted` events.
- `reports/metrics.jsonl` for `dream_discovery`, `dream_candidate_generated`, and `mutation_promoted` events.
