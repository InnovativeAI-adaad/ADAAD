# ADAAD — Quickstart

> **First time?** One command: `python onboard.py` — it handles everything.

---

## The fast path

```bash
git clone https://github.com/InnovativeAI-adaad/ADAAD.git
cd ADAAD
python onboard.py
```

`onboard.py` creates your virtual environment, installs dependencies, validates governance schemas, and runs a governed dry-run of the Constitutional Evolution Loop. Safe to re-run any time.

---

## What you'll see

```
  ✔ Python 3.12.x
  ✔ Virtual environment created (.venv)
  ✔ Dependencies installed
  ✔ ADAAD_ENV=dev
  ✔ Workspace valid
  ✔ Governance schemas valid
  ✔ Dry-run complete  (fail-closed behaviour confirmed)

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ADAAD is ready.

  Run the dashboard       python server.py
  Run an epoch            adaad demo
  Inspect the ledger      adaad inspect-ledger data/evolution_ledger.jsonl
  Propose a mutation      adaad propose "upgrade system x"
  Strict replay           python -m app.main --replay strict --verbose
  Verify the audit box    docker compose up das-demo
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## CLI reference

```bash
# Ensure scripts/ is in your PATH, or call directly:
./scripts/adaad --help
./scripts/adaad demo                              # Dry-run the CEL
./scripts/adaad inspect-ledger <path>             # Summarize the evolution ledger
./scripts/adaad propose "<description>"           # Inject a mutation proposal at CEL Step 4
```

All CLI-initiated mutations default to sandbox-only execution (`CLI-SANDBOX-0`). Promote explicitly.

---

## Soulbound key (first run)

You'll see this warning on first run — it's expected:

```
⚠  ADAAD_SOULBOUND_KEY is not set.
   Phase 9+ soulbound ledger writes will be fail-closed without it.
   Generate a dev key: python -c "import secrets; print(secrets.token_hex(32))"
   export ADAAD_SOULBOUND_KEY=<your-key>
```

For local development: generate a key and export it.  
For production: source from a secret manager.

---

## Install from PyPI

```bash
pip install adaad                 # Python ≥ 3.11 required
```

The PyPI package (`adaad-core`) contains the extractable governance kernel. The full runtime requires cloning the repository.

---

## Manual setup (fallback)

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env              # Edit as needed
python -m pytest tests/ -v       # Run the full test suite
```

---

## Platform notes

| Platform | Notes |
|:---------|:------|
| **Linux** | Primary target. Works out of the box. |
| **macOS** | Python 3.12 via Homebrew recommended. |
| **Windows** | PowerShell. Use `.venv\Scripts\Activate.ps1`. |
| **Android / Termux** | See [`TERMUX_SETUP.md`](TERMUX_SETUP.md) for the complete guide. Full governed runtime on commodity hardware. |
| **Docker** | See [`docker-compose.yml`](docker-compose.yml). Pinned image digest mandatory — `:latest` is constitutionally prohibited by `DAS-DOCKER-0`. |

---

## Run the DORK dashboard

```bash
python server.py
# Open ui/dork.html in your browser
# Or access the production instance at https://aponi.adaad.pro
```

DORK gives you natural-language access to the full constitutional history of your ADAAD instance. Ask it anything about the governance ledger.

---

## Verify everything independently

```bash
docker compose up das-demo
```

The Deterministic Audit Sandbox (INNOV-36) runs the full pipeline from scratch and produces a verifiable output. No trust required. See [`BREAK_IT_CHALLENGE.md`](docs/BREAK_IT_CHALLENGE.md) for the formal third-party verification protocol.

---

## Next steps

| Resource | What it covers |
|:---------|:---------------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Full system architecture and module map |
| [`docs/CONSTITUTION.md`](docs/CONSTITUTION.md) | The 241 Hard-class invariants |
| [`DORK.md`](DORK.md) | The governance intelligence layer |
| [`ROADMAP.md`](ROADMAP.md) | All 50 shipped innovations and what's next |
| [`TRUST_CENTER.md`](TRUST_CENTER.md) | Security posture and disclosure policy |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution protocol |
| [`TERMUX_SETUP.md`](TERMUX_SETUP.md) | Android / Termux setup guide |
