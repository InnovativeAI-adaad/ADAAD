# ADAAD Quick Start (5 Minutes)

> 🎥 Prefer video? A walkthrough is not published yet; this guide is the canonical setup path today.

This guide gives you the fastest path to a working ADAAD run, plus a clean reset path if state drifts.

## What success looks like in under 2 minutes

If you only run one command after setup, run this:

```bash
./quickstart.sh
```

This validates schemas, runs a deterministic simulation sample, checks founders-law/federation tests, and prints the dashboard start command. If the founders-law compatibility module is unavailable, quickstart logs a warning and skips federation compatibility tests.

Then run the governed mutation dry-run:

```bash
python -m app.main --dry-run --replay audit --verbose
```

In this mode ADAAD should boot, evaluate governance/replay state, and print mutation-cycle status without writing file changes.

Illustrative output:

```text
[ADAAD] Starting governance spine initialization
[ADAAD] Replay decision: audit
[DREAM] Candidate discovery complete
[GOVERNANCE] constitution: pass
[MUTATION] dry-run only, no files modified
```

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

### Lightweight / constrained environments

If dependency installation fails in constrained environments, retry without pip cache:

```bash
pip install -r requirements.server.txt --no-cache-dir
```

ADAAD currently expects a full Python environment; Linux/WSL remains the recommended runtime target.

### Hermetic runtime profile (required for audit/strict replay)

Boot-time governance checks read `governance_runtime_profile.lock.json` and fail closed when:

- dependency fingerprint does not match `requirements.server.txt`;
- deterministic provider is not enabled;
- mutable filesystem/network are neither disabled nor explicitly allowlisted.

Recommended environment for governance-critical replay:

```bash
export ADAAD_FORCE_DETERMINISTIC_PROVIDER=1
export ADAAD_DETERMINISTIC_SEED=ci-strict-replay
export ADAAD_DISABLE_MUTABLE_FS=1
export ADAAD_DISABLE_NETWORK=1
```

## 4) Initialize ADAAD workspace

```bash
python nexus_setup.py
python nexus_setup.py --validate-only        # read-only preflight (required checks + optional local port probe)
python nexus_setup.py --validate-only --json # machine-readable preflight report (no workspace writes)
```

## Governance boot-critical artifacts

The following files are required for fail-closed constitutional boot and must exist/parse cleanly:

- `runtime/governance/constitution.yaml`
- `governance/rule_applicability.yaml`

If either file is missing or malformed, ADAAD intentionally halts boot with a constitutional initialization error.

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

## 5.1) Interpret the result quickly

- **Boot + replay signals present, mutation disabled:** environment is healthy; no eligible staged work discovered.
- **Boot + replay signals present, mutation enabled:** system is ready to evaluate governed mutation flow.
- **Replay divergence or policy rejection:** expected fail-closed behavior; inspect logs before retrying.

## 6) Optional replay verification-only mode

For CI-equivalent strict replay behavior, use the deterministic provider + seed used in CI:

```bash
ADAAD_ENV=dev CRYOVANT_DEV_MODE=1 ADAAD_FORCE_DETERMINISTIC_PROVIDER=1 ADAAD_DETERMINISTIC_SEED=ci-strict-replay \
  python -m app.main --verify-replay --replay strict --verbose
```

On first-time setup, run audit mode first to establish a baseline signal:

```bash
python -m app.main --replay audit --verbose
ADAAD_ENV=dev CRYOVANT_DEV_MODE=1 ADAAD_FORCE_DETERMINISTIC_PROVIDER=1 ADAAD_DETERMINISTIC_SEED=ci-strict-replay \
  python -m app.main --verify-replay --replay strict --verbose
```

Depending on local state, the first strict replay check can fail until replay artifacts are stabilized.

## 7) Optional dry-run mutation evaluation

```bash
python -m app.main --dry-run --replay audit --verbose
```

## Launch the dashboard quickly

Start the unified API + dashboard server directly:

```bash
scripts/run_dashboard.sh
```

Equivalent explicit command:

```bash
python server.py --host 0.0.0.0 --port 8000 --reload
```

Then open:

- `http://127.0.0.1:8000/` for the dashboard UI
- `http://127.0.0.1:8000/api/health` for API health (`0.0.0.0` bind still answers on `127.0.0.1`)

UI preload/fallback behavior:

- Preferred: `ui/aponi/index.html`
- Fallback: `ui/enhanced/enhanced_dashboard.html`
- If neither exists, `python server.py` auto-creates `ui/aponi/index.html` placeholder so first launch still works

`python server.py ...` and `uvicorn server:app ...` share the same startup UI resolution behavior.

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

# Dashboard reachability check (defaults to localhost:8000)
curl -sS http://127.0.0.1:8000/state | python -m json.tool
```

## Clean reset (if behavior looks inconsistent)

macOS/Linux:

```bash
rm -rf reports security/ledger security/replay_manifests
python nexus_setup.py                          # re-initialize workspace
python nexus_setup.py --validate-only          # confirm all checks pass
python nexus_setup.py --validate-only --json   # machine-readable output for scripting
```

Windows (PowerShell):

```powershell
Remove-Item -Recurse -Force reports, security\ledger, security\replay_manifests
python nexus_setup.py                          # re-initialize workspace
python nexus_setup.py --validate-only          # confirm all checks pass
python nexus_setup.py --validate-only --json   # machine-readable output for scripting
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

### Policy rejection appears

This is expected fail-closed behavior. Re-run with verbose output and review the rejection reason before changing policy:

```bash
python -m app.main --dry-run --replay audit --verbose
```

### Dashboard does not open

Confirm the process started and the endpoint is reachable:

```bash
python -m app.main --replay audit --verbose
curl -sS http://127.0.0.1:8000/state
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

## Optional UX-first first run

```bash
python tools/interactive_onboarding.py
python tools/enhanced_cli.py --replay audit --verbose
```

The enhanced CLI streams orchestrator output and maps key boot/governance lines to live stage updates.

To view the enhanced dashboard:

```bash
python -m http.server 8081 --directory ui/enhanced
# open http://localhost:8081/enhanced_dashboard.html
```
