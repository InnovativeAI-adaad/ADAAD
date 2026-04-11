# Replay Divergence Artifact Report

- Generated at: `2026-04-05T21:16:58Z`
- Replay command: `python -m app.main --verify-replay --replay audit`
- Verify target: `all_epochs`
- Decision: `continue`

## Digest Comparison
- Base digest: `a`
- Current digest: `b`

## Normalized First Divergence
- Epoch: `all_epochs`
- First differing path: `digest`

## Environment Flags
- `ADAAD_CEL_ENABLED=true`
- `ADAAD_DETERMINISTIC_SEED=orchestrator-test-seed`
- `ADAAD_DISABLE_MUTABLE_FS=1`
- `ADAAD_DISABLE_NETWORK=1`
- `ADAAD_ENV=dev`
- `ADAAD_FORCE_DETERMINISTIC_PROVIDER=1`
- `ADAAD_POLICY_ARTIFACT_SIGNING_KEY=test-key`
- `ADAAD_SANDBOX_CONTAINER_ROLLOUT=off`
- `ADAAD_SANDBOX_ONLY=true`
- `ADAAD_SOULBOUND_KEY=9fb9005cafc70250673d48636a7faa77accba30bfd9acadace90744e4fa703fe`
- `CRYOVANT_DEV_MODE=1`

## Determinism Lint Summary
- Command: `python tools/lint_determinism.py runtime/ security/ adaad/orchestrator/ app/main.py`
- Return code: `0`
- Status: `ok`

```text
determinism lint passed
```

## Artifact Files
- JSON: `/home/dustinreid82/adaad/security/replay_artifacts/replay_divergence_2026-04-05T21-16-55Z/replay_divergence_report.json`
- Markdown: `/home/dustinreid82/adaad/security/replay_artifacts/replay_divergence_2026-04-05T21-16-55Z/replay_divergence_report.md`
