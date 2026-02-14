# ADAAD Quick Start (5 Minutes)

> 🎥 Prefer video? A short walkthrough is planned; this guide is the canonical setup path today.

This guide gives you the fastest path to a working ADAAD run, plus a clean reset path if state drifts.

## Prerequisites

- Python 3.10+
- `pip`
- `git`

Verify tooling:

```bash
python --version
pip --version
git --version
```

## 1) Clone and enter the repo

```bash
git clone https://github.com/InnovativeAI-adaad/ADAAD.git
cd ADAAD
```

## 2) Create and activate a virtual environment

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 3) Install dependencies

```bash
pip install -r requirements.server.txt

# Sanity-check active environment packages
pip freeze | rg -i "adaad|aponi|cryovant"
```

## 4) Initialize ADAAD workspace

```bash
python nexus_setup.py
```

## 5) Verify boot works (recommended)

Run with verbose diagnostics:

```bash
python -m app.main --replay audit --verbose
```

`--verbose` prints boot stages (gatekeeper, replay decision, mutation status, dashboard start), which helps diagnose clean exits.

### Expected output signals

You should see output that includes lines similar to:

```text
[ADAAD] Starting governance spine initialization
[ADAAD] Gatekeeper preflight passed
[ADAAD] Runtime invariants passed
[ADAAD] Cryovant validation passed
[ADAAD] Replay decision: ...
[ADAAD] Mutation cycle status: enabled|disabled
[ADAAD] Aponi dashboard started
```

If you see these signals, your installation is functioning.

## 6) Optional replay verification-only mode

```bash
python -m app.main --verify-replay --replay strict --verbose
```

On first-time setup, run audit mode first to establish a baseline signal:

```bash
python -m app.main --replay audit --verbose
python -m app.main --verify-replay --replay strict --verbose
```

Depending on local state, the first strict replay check can fail until replay artifacts are stabilized.

## 7) Optional dry-run mutation evaluation

```bash
python -m app.main --dry-run --replay audit --verbose
```

## Quick health checks

```bash
# Recent telemetry
python - <<'PY'
from pathlib import Path
p=Path('reports/metrics.jsonl')
print('metrics_exists=', p.exists())
if p.exists():
    print('\n'.join(p.read_text(encoding='utf-8').splitlines()[-3:]))
PY

# Replay audit verification
python -m app.main --verify-replay --replay audit --verbose
```

## Clean reset (if behavior looks inconsistent)

macOS/Linux:

```bash
rm -rf reports security/ledger security/replay_manifests
python nexus_setup.py
```

Windows (PowerShell):

```powershell
Remove-Item -Recurse -Force reports, security\ledger, security\replay_manifests
python nexus_setup.py
```

## Troubleshooting

### `ModuleNotFoundError` during startup

Re-activate your virtual environment and reinstall dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.server.txt
```

### Replay strict fails

Inspect divergences first:

```bash
python -m app.main --replay audit --verbose
```

### Boot appears to exit quickly

Run with verbose mode to confirm stage-by-stage completion:

```bash
python -m app.main --replay audit --verbose
```

## Next steps

- Repository overview: [README.md](README.md)
- Minimal runnable example: [examples/single-agent-loop/README.md](examples/single-agent-loop/README.md)
- Governance model: [docs/CONSTITUTION.md](docs/CONSTITUTION.md)
