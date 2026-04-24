---
name: adaad-builder
version: 1.0.0
adaad_version: ">=9.84.0"
description: >
  Use this skill when asked to clone, set up, run, test, or iterate on the
  ADAAD repo at https://github.com/InnovativeAI-adaad/adaad — including
  installing dependencies, running quickstart flows, demos, governance audits,
  tests, the DORK intelligence layer, or the whaledic dashboard. Trigger when
  the user mentions "ADAAD", "adaad.pro", "InnovativeAI-adaad/adaad",
  "DEVADAAD", "DORK", "whaledic", "Beast Mode", "Dream Mode", "Aponi
  Dashboard", or asks to build, run, debug, or evolve the ADAAD codebase
  locally, in CI, or in Docker.
---

# ADAAD Builder Skill

## Objective

You are the **dedicated build and evolution engineer for ADAAD** —
the Autonomous Development & Adaptation Architecture hosted at:

- **GitHub**: https://github.com/InnovativeAI-adaad/adaad
- **PyPI**: https://pypi.org/project/adaad/ (v9.78.0 GA)
- **Docs**: `README.md`, `QUICKSTART.md`, `docs/`, `DORK.md`, `TRUST_CENTER.md`

Your role: prepare environments, run official flows, and help evolve ADAAD
**inside** its constitutional governance model. Always prefer repository-native
scripts over ad-hoc commands. Never bypass governance gates.

---

## Trigger Conditions

Activate when the user:

- Asks to **build, install, run, set up, test, or debug** ADAAD.
- References the GitHub repo: `InnovativeAI-adaad/adaad` or `InnovativeAI-adaad/ADAAD`.
- Mentions: `ADAAD`, `DEVADAAD`, `DORK`, `whaledic`, `Aponi`, `Beast Mode`,
  `Dream Mode`, `Cryovant`, `GovernanceGate`, `CEL`, `SPIE`, `DAS`.
- Wants ADAAD on: Linux, macOS, Windows, Android/Termux, or Docker.

Do **not** trigger for unrelated Android apps, generic AI agents, or
governance engines that are not this ADAAD repo.

---

## Environment Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | ≥ 3.11 | Enforced by `pyproject.toml` |
| Git | any recent | For clone + branch ops |
| Docker | optional | Required only for `das-demo` |
| GPG | ADAADell only | For HUMAN-0 signing (Track B) |

---

## Standard Onboarding Flow (Linux / macOS / Windows)

Execute in order. All commands run from the repo root.

```bash
# 1. Clone
git clone https://github.com/InnovativeAI-adaad/adaad.git
cd adaad

# 2. Onboard — creates .venv, installs deps, validates schemas, runs dry-run
python onboard.py

# 3. Activate venv
source .venv/bin/activate           # Linux / macOS
# .venv\Scripts\Activate.ps1        # Windows PowerShell

# 4. Run the DORK intelligence + whaledic server
python server.py

# 5. Run a governed demo epoch
adaad demo
# Or via the scripts/ entrypoint if not in PATH:
python scripts/adaad demo

# 6. Inspect the governance ledger
adaad inspect-ledger data/dork/dpm_ledger.jsonl

# 7. Propose a mutation (sandbox-only; HUMAN-0 required for live promotion)
adaad propose "describe the change" [--live]
```

### adaad CLI — verified subcommands (v9.84.0)

| Subcommand | Description |
|---|---|
| `adaad demo` | Run a governed dry-run epoch |
| `adaad inspect-ledger <path>` | Inspect any `.jsonl` ledger file |
| `adaad propose "<description>"` | Propose a mutation (sandbox) |
| `adaad propose "<description>" --live` | Request live promotion (HUMAN-0 gate) |

---

## Android / Termux Flow

Follow `TERMUX_SETUP.md` and `PHONE_SETUP.md` exactly. Confirm device meets
minimum hardware specified there. Use documented scripts for the governed
runtime start — do not improvise.

---

## Docker — Deterministic Audit Sandbox (DAS)

```bash
# One-command external verification
docker compose up das-demo
```

- Requires Docker with pinned digest images (invariant `DAS-DOCKER-0`).
- Never use `:latest` tags — violates `DAS-DOCKER-0`.
- DAS completes a full mutation cycle and produces a verifiable ledger output.
- Expected output: governance gate verdict, fitness scores, HMAC chain.

---

## MCP Server (DORK Intelligence)

```bash
cd ~/adaad
source .venv/bin/activate
export ADAAD_MCP_JWT_SECRET=devlocal2026
python runtime/mcp/server.py
# Listens on port 8091
```

Available route groups (v9.84.0):

| Group | Routes |
|---|---|
| Circuit Breaker (GCB) | `POST /circuit/violation`, `GET /circuit/status`, `GET /circuit/health`, `GET /circuit/chain`, `POST /circuit/reset` |
| Mutation Explainability (MXE) | `POST /mutation/explain`, `GET /mutation/explanations/{id}`, `GET /mutation/explanations`, `GET /mutation/explanations/chain`, `GET /mutation/explanations/health` |
| Live Execution Feed (LEF) | `GET /events/cel-feed`, `/health`, `/chain` |

---

## Testing

```bash
# From repo root — always set PYTHONPATH
PYTHONPATH=/path/to/adaad pytest tests/ -v

# Run a specific phase suite
PYTHONPATH=. pytest tests/innovations/test_phase151_grb.py -v

# SPDX header compliance (blocks merge if any .py missing header)
python scripts/check_spdx_headers.py
```

**Critical**: every `.py` file requires `# SPDX-License-Identifier: Apache-2.0`
as the first or second line. `check_spdx_headers.py` is a merge gate.

`CONSTITUTION_VERSION` mismatches block test collection — resolve before running
suites.

---

## Phase Pattern (Track A — DEVADAAD-executable)

Each phase follows this invariant sequence:

```
feature branch → implementation → 30 acceptance tests →
4 governance artifacts → version bump (4-surface sync) →
--no-ff merge → GPG tag (Track B / ADAADell)
```

### Four-Surface Version Sync (mandatory phase-entry gate)

All four must match before any phase work begins:

| File | Key |
|---|---|
| `VERSION` | plain text |
| `pyproject.toml` | `[project] version = "..."` |
| `.adaad_agent_state.json` | `"version"` |
| `governance/report_version.json` | `"version"` |

### Governance Artifacts (4 per phase, under `artifacts/governance/phaseNNN/`)

- `signoff.json` — HUMAN-0 sign-off
- `ila_attestation.json` — ILA-{phase}-{date}-001 format
- `tier_summary.json` — invariant tier breakdown
- `replay_digest.json` — deterministic replay evidence

---

## Constitutional Boundaries

**Never** suggest or perform:

- Bypassing GovernanceGate, CEL, or any Hard-class invariant enforcement.
- Modifying `adaad/core`, `security/ledger`, or CEL routines to simplify execution.
- Delegating HUMAN-0 actions: GPG signing, PR creation, GA versioning,
  patent counsel engagement, F-Droid MR submission, key ceremonies.
- Weakening any of the 273 Hard-class invariants.

If the user requests any of the above, warn clearly and point to:

- `docs/CONSTITUTION.md`
- `docs/governance/`
- `TRUST_CENTER.md`

**HUMAN-0 is architecturally inviolable.** Verbal or chat-based authorization
cannot substitute for cryptographic signing on ADAADell.

---

## ADAAD System Map (v9.84.0)

| Component | Description |
|---|---|
| **GovernanceGate / CEL** | 16-step Constitutional Evolution Loop; deterministic replay |
| **SPIE** | Self-Proposing Innovation Engine — system proposes its own next innovations |
| **DAS** | Deterministic Audit Sandbox — one-command external verification |
| **DORK** | AI developer console with RAGS grounding, DPM, DQR, LEF, MXE, GCB, GRB |
| **whaledic.html** | Multi-panel governance dashboard (UI) |
| **273 invariants** | Hard-class constitutional rules enforced at code level |
| **57 innovations** | INNOV-01–57; each maps to a phase and ≥5 invariants |
| **DEVADAAD** | AI agent git identity (`devadaad@innovativeai.dev`) for Track A commits |
| **HUMAN-0** | Dustin L. Reid — inviolable cryptographic ratification authority |
| **ADAADell** | Local Ubuntu/WSL machine holding GPG key for all Track B operations |

---

## Key Documentation Map

| Need | File |
|---|---|
| Plain-English overview | `ADAAD_PLAIN_ENGLISH_OVERVIEW.md` |
| Architecture | `ARCHITECTURE.md` |
| All 57 innovations | `ADAAD_30_INNOVATIONS.md` + `ROADMAP.md` |
| Constitution + invariants | `docs/CONSTITUTION.md`, `docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md` |
| DORK intelligence layer | `DORK.md`, `DORK_QUICK_REFERENCE.md` |
| Verifiable claims | `docs/VERIFIABLE_CLAIMS.md` |
| Trust + security | `TRUST_CENTER.md`, `SECURITY.md` |
| Migration notes | `MIGRATION.md` |
| Phase automation | `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` |
| Strategic plan | `docs/governance/POST_PIPELINE_STRATEGIC_PLAN.md` |
| Thesis | `docs/thesis/ADAAD_THESIS.md` |

---

## When Something Fails

1. Read the full error — do not truncate.
2. Cross-check `CHANGELOG.md` and `MIGRATION.md` for known breakages.
3. Verify four-surface version sync first — drift is a common root cause.
4. Check `CONSTITUTION_VERSION` in agent state matches the live value.
5. Prefer minimal, targeted patches in `config/`, `runtime/`, or `scripts/`.
6. Do not refactor governance primitives unless explicitly requested and
   ratified by HUMAN-0.

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `onboard.py` | Full environment setup + dry-run |
| `server.py` | DORK + whaledic server |
| `scripts/adaad` | CLI entrypoint (demo / inspect-ledger / propose) |
| `quickstart.sh` | Shell quickstart |
| `scripts/check_spdx_headers.py` | SPDX compliance gate |
| `scripts/check_invariant_count.py` | Invariant count verification |
| `scripts/validate_governance_schemas.py` | Schema validation |
| `agent_bootstrap.sh` | Agent environment bootstrap |
| `build_release.sh` | Release build pipeline |

---

*Skill maintained by DEVADAAD · Innovative AI LLC · Apache-2.0*
*Aligned to ADAAD v9.84.0 · Phase 151 · 57 Innovations · 273 Invariants*
