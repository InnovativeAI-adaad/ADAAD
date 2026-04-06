<div align="center">

<!-- ADAAD_VERSION_HERO:START -->
![ADAAD Hero Banner](docs/assets/readme/inline-hero_banner.svg)
<!-- ADAAD_VERSION_HERO:END -->

**[⚡ Quickstart](#quickstart)** &nbsp;·&nbsp; **[📜 Constitution](docs/CONSTITUTION.md)** &nbsp;·&nbsp; **[🗺 Roadmap](ROADMAP.md)** &nbsp;·&nbsp; **[📖 Thesis](docs/thesis/ADAAD_THESIS.md)** &nbsp;·&nbsp; **[🏛 Trust Center](TRUST_CENTER.md)** &nbsp;·&nbsp; **[✅ Verifiable Claims](docs/VERIFIABLE_CLAIMS.md)** &nbsp;·&nbsp; **[📋 Changelog](CHANGELOG.md)**

</div>

![Section Divider](docs/assets/readme/inline-divider.svg)

## What ADAAD is

**ADAAD is a constitutionally governed autonomous code evolution runtime.**

... (rest of What ADAAD is section) ...

![Section Divider](docs/assets/readme/inline-divider.svg)

## Enforced guarantees

These are runtime-enforced invariants. Violating any one aborts the epoch.

| Guarantee | Mechanism | Invariant |
|:---|:---|:---:|
| Every epoch produces a verifiable evidence hash | SHA-256 hash-chained append-only ledger | `CEL-EVIDENCE-0` |
| Mutations are byte-identical replayable from original inputs | No `datetime.now()` or `random.random()` in constitutional paths | `CEL-REPLAY-0` |
| Pipeline step ordering cannot be bypassed | Runtime sequence check — out-of-order aborts immediately | `CEL-ORDER-0` |
| Governance gate is the sole promotion path | `GovernanceGateV2` is the only path — no side channel | `GOV-SOLE-0` |
| Shadow harness writes nothing to production | Zero-write enforcement + egress detection | `LSME-0` |
| Red Team agent cannot approve its own challenges | Structural constraint in code — PASS or RETURNED only | `AFRT-0` |
| Identity check never blocks an epoch | Fail-open with fallback score injection | `MMEM-0` |
| Critical mutations require GPG-signed human approval | Architecturally enforced — not a configuration option | `HUMAN-0` |
| Import boundaries block unauthorized dependencies | Static enforcement — violations block merge | `AST-IMPORT-0` |
| High-stakes mutations require 2-of-3 jury verdict | `ConstitutionalJury.deliberate()` is the sole authority | `CJS-0` |
| Governance drift rate capped at 30% before double sign-off | Meta-governance limits constitutional change velocity | `CEB-0` |
| No mutation may reduce self-monitoring observability | Transparency is structural and non-negotiable | `SELF-AWARE-0` |
| 162 Hard-class invariants enforced at runtime | Epoch aborts on any violation — no silent failures | 162 total |

→ [Full invariants matrix](docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md) · [Constitution](docs/CONSTITUTION.md) · [Verifiable claims](docs/VERIFIABLE_CLAIMS.md)

![Section Divider](docs/assets/readme/inline-divider.svg)

## The pipeline

![ADAAD Autonomy Loop Pipeline](docs/assets/readme/inline-autonomy_loop.svg)

Every proposed change traverses all steps in strict order. There is no skip path, no override flag, no configuration that changes this.

<details>
<summary><b>Step-by-step breakdown</b></summary>
<br/>

**Step 0 — Identity check**
Before any proposal is generated, the `IdentityContextInjector` consults the `IdentityLedger` — a hash-chained, HUMAN-0-attested self-model. First system to ask: *is this mutation consistent with what this system believes itself to be?*

**Phase 1 — Proposal**
Claude-powered agents (Architect · Dream · Beast) generate `MutationCandidate`s. UCB1 bandit selector routes to the highest-performing agent. Agents stake reputation on proposals — failed proposals burn stake.

**Phase 2–3 — Adversarial Red Team**
`AdversarialRedTeamAgent` queries `CodeIntelModel` for uncovered code paths, generates up to 5 targeted adversarial cases. Structurally incapable of approving. PASS or RETURNED only.

**Phase 4 — Constitutional Scoring**
`FitnessEngineV2` scores against 8 fitness signals. All runtime-enforced constitutional rules checked. Rule violation halts epoch immediately.

**Phase 5 — Live Shadow Execution**
Zero-write shadow harness against real traffic patterns. Divergence rate, error delta, P99 latency. Regression on any signal is a hard block.

**Phase 6 — Constitutional Jury**
For high-stakes mutations: `ConstitutionalJury.deliberate()` convenes 3 independent evaluators. 2-of-3 approve required. Dissenting verdicts committed to dissent ledger.

**Phase 7 — Governance Gate**
`GovernanceGateV2` evaluates the full evidence package. All prior gates must pass. Verdict: APPROVED · RETURNED · BLOCKED.

**Phase 8 — Human Sign-off (Tier 0)**
For critical mutations: GPG-signed approval from governor is required. The system is architecturally incapable of promoting Tier 0 mutations without it.

**Phase 9 — Ledger Commit + Cryptographic Proof DAG**
Every decision is SHA-256 hash-chained. Full mutation lineage Merkle-rooted. Every causal ancestor cryptographically linked. Legal-grade provenance.

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Architecture

![ADAAD System Architecture](docs/assets/readme/inline-architecture.svg)

ADAAD runs a **14-step Constitutional Evolution Loop (CEL)** on every proposed change. Three AI agents — **Architect**, **Dream**, and **Beast** — apply constitutional rules at different steps. No single agent can approve a change. The Constitutional Jury gate adds multi-agent adversarial evaluation for high-stakes paths.

<details>
<summary><b>Module map and boundary contracts</b></summary>
<br/>

**Runtime layer** — `runtime/`

| Module | Role |
|:---|:---|
| `evolution/evolution_loop.py` | Orchestrates the 14-phase epoch. Phase 0d MMEM wire lives here. |
| `evolution/constitutional_evolution_loop.py` | 14-step CEL dispatch. Calls GovernanceGate, AFRT, LSME, CJS. |
| `evolution/fitness_v2.py` | `FitnessEngineV2` — 8-signal scoring including identity. |
| `memory/identity_ledger.py` | Hash-chained HUMAN-0-gated `IdentityLedger`. MMEM-0/CHAIN-0/LEDGER-0. |
| `innovations30/__init__.py` | Boot completeness gate — all 36 importable or `RuntimeError` (INNOV-COMPLETE-0). |
| `innovations30/constitutional_jury.py` | INNOV-14 — 2-of-3 quorum, dissent ledger, high-stakes gate. |
| `innovations30/constitutional_entropy_budget.py` | INNOV-26 — governance drift rate limiter, double-HUMAN-0 at 30%. |
| `innovations30/self_awareness_invariant.py` | INNOV-28 — structural observability protection. |
| `innovations30/mirror_test.py` | INNOV-30 — constitutional self-recognition test, pipeline seal. |
| `lineage/lineage_ledger_v2.py` | Second-gen lineage store with MMEM co-commit surface. |
| `capability_graph.py` | Module capability contracts. No `__import__` — enforced. |

**Governance layer** — `security/`

| Module | Role |
|:---|:---|
| `security/ledger/governance_events.jsonl` | Hash-chained HUMAN-0 sign-off events. |
| `security/ledger/scoring.jsonl` | All epoch governance decisions. Append-only. |
| `config/constitution.yaml` | Runtime-enforced constitutional rules. |

**Import boundary contract:** All module-to-module imports must cross defined seams. `AST-IMPORT-0` CI gate blocks violations. Every file must carry `# SPDX-License-Identifier: Apache-2.0`.

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Shipped capabilities

![Core Capabilities — Shipped](docs/assets/readme/inline-capabilities_grid.svg)

<details>
<summary><b>Full innovation index</b></summary>
<br/>

| # | Innovation | Phase | Core claim |
|:---:|:---|:---:|:---|
| INNOV-01 | constitutional_stress_test.py | 87 | AI proposes amendments to its own rules under unconditional HUMAN-0 ratification |
| INNOV-02 | self_awareness_invariant.py | 87 | Dedicated agent stress-tests every constitutional rule by attempting to violate it |
| INNOV-03 | temporal_governance.py | 87 | Predicts which invariants will be violated in future epochs before they fail |
| INNOV-04 | constitutional_entropy_budget.py | 88 | Detects constitutional behaviour drift from historical baseline |
| INNOV-05 | governance_archaeology.py | 89 | Proposes new architectural organs to close capability gaps — HUMAN-0 ratification required |
| INNOV-06 | counterfactual_fitness.py | 90 | Full lineage Merkle-rooted · independently verifiable · legal-grade provenance |
| INNOV-07 | temporal_regret.py | 91 | Zero-write shadow harness · real traffic · hard block on regression |
| INNOV-08 | red_team_agent.py | 92 | Red Team gate before scoring · structurally incapable of approving · PASS or RETURNED only |
| INNOV-09 | aesthetic_fitness.py | 93 | Code readability as constitutionally-bounded first-class fitness dimension |
| INNOV-10 | morphogenetic_memory.py | 94 | Hash-chained self-model consulted pre-proposal · identity drift detection at the root |
| INNOV-11 | dream_state.py | 96 | Offline cross-epoch mutation memory consolidation — constitutionally governed synaptic replay |
| INNOV-12 | mutation_genealogy.py | 97 | Property inheritance vectors on lineage edges · population-genetics-level analysis |
| INNOV-13 | knowledge_transfer.py | 98 | Cryptographically verified cross-instance knowledge transfer |
| INNOV-14 | constitutional_jury.py | 99 | 2-of-3 multi-agent jury for high-stakes mutations · dissent feeds invariant discovery |
| INNOV-15 | reputation_staking.py | 100 | Agents stake reputation on proposals · failed proposals burn stake |
| INNOV-16 | emergent_roles.py | 101 | Agents develop constitutional specializations from evolutionary fitness history |
| INNOV-17 | agent_postmortem.py | 102 | Governed autopsy of failed mutations · extracts constitutional invariants from failure |
| INNOV-18 | temporal_governance.py | 103 | Time-conditional constitutional rules · governance adapts to epoch context |
| INNOV-19 | reputation_staking.py | 104 | Archaeological analysis of constitutional decision history |
| INNOV-20 | blast_radius_model.py | 105 | Systematic adversarial probing of the full constitutional boundary surface |
| INNOV-21 | governance_bankruptcy.py | 106 | Governed constitutional reset under catastrophic governance failure |
| INNOV-22 | mutation_conflict_framework.py | 107 | Fitness signals conditioned on live market and economic context |
| INNOV-23 | constitutional_epoch_sentinel.py | 108 | Constitutional rule mapping to external regulatory frameworks (EU AI Act, NIST RMF) |
| INNOV-24 | semantic_version_enforcer.py | 109 | Constitutional enforcement of semantic versioning across all four canonical files |
| INNOV-25 | hardware_adaptive_fitness.py | 110 | Fitness signals that adapt to available compute and memory constraints |
| INNOV-26 | constitutional_entropy_budget.py | 111 | Meta-governance: rate-limits constitutional drift — 30% rule-change threshold triggers double-HUMAN-0 |
| INNOV-27 | regulatory_compliance.py | 112 | Pre-promotion blast radius estimation · constitutional bound on mutation impact scope |
| INNOV-28 | intent_preservation.py | 113 | No mutation may reduce system self-monitoring observability — transparency is constitutional |
| INNOV-29 | curiosity_engine.py | 114 | Constitutional curiosity drive — governed exploration of under-explored mutation space |
| INNOV-30 | mirror_test.py | 115 | Constitutionally governed self-recognition test — final seal of the Innovations30 pipeline |
| INNOV-31 | invariant_discovery.py | 116 | Autonomous Invariant Discovery — mines failure ledger for patterns |
| INNOV-32 | constitutional_rollback.py | 117 | Governed Constitutional Rollback — versioned chain-linked snapshot ledger |
| INNOV-33 | knowledge_bundle_exchange.py | 118 | Knowledge Bundle Exchange (KBEP) — cryptographically verified capability transfer |
| INNOV-34 | federation_governance_consensus.py | 119 | Federation Governance Consensus — strict majority quorum for amendments |
| INNOV-35 | self_proposing_innovation_engine.py | 120 | Self-Proposing Capability Engine (SPIE) — system identifies its own gaps |
| INNOV-36 | Deterministic Audit Sandbox (DAS) | 121 | One-command external third-party verification of any epoch |

Full specifications: [ADAAD_30_INNOVATIONS.md](ADAAD_30_INNOVATIONS.md)

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Proven milestones — not roadmap promises

![Phase Progress Bar](docs/assets/readme/inline-phase_progress.svg)

<br/>

<details open>
<summary><b>⛓ March 13, 2026 — First autonomous self-evolution (Phase 65) — the founding event</b></summary>
<br/>

ADAAD identified its own highest-priority capability gap, generated a mutation, ran a sandboxed fitness tournament, scored it against constitutional rules, applied it, and sealed the proof in the ledger. Zero human intervention in the execution path. Full human control of the constitutional framework.

**Independent verification — replay it yourself:**
```bash
python -m app.main --replay strict --epoch-id phase65-emergence-001 --verbose
# Must produce byte-identical evidence_hash — divergence is a blocking integrity signal
```

This is the first externally documented instance of a constitutionally governed AI system autonomously modifying its own codebase within a formally verified governance boundary. The ledger entry, evidence hash, and replay instructions are public. An independent auditor can reproduce this without access to any system beyond this repository.

![Phase 65 Milestone](docs/assets/readme/inline-phase_milestone.svg)

![Hash Chain Integrity](docs/assets/readme/inline-hash_chain.svg)
</details>

<details>
<summary><b>🧭 March 23, 2026 — Cryptographic Evolution Proof DAG (Phase 90 · INNOV-06)</b></summary>
<br/>

Every mutation cryptographically bound to all causal ancestors via Merkle root. `CryptographicProofBundle` is self-contained — independently verifiable without system access. Legal-grade provenance for auditors, regulators, and patent counsel.
</details>

<details>
<summary><b>🛡 March 24, 2026 — Live Shadow Mutation Execution (Phase 91 · INNOV-07)</b></summary>
<br/>

Zero-write shadow harness against real traffic. `ShadowFitnessReport`: divergence rate · error delta · P99 latency. `LSME-0`: any write or egress = hard block. Must survive shadow execution *and* governance gate to advance.
</details>

<details>
<summary><b>⚔ March 27, 2026 — Adversarial Red Team as a Constitutional Gate (Phase 92 · INNOV-08)</b></summary>
<br/>

`AdversarialRedTeamAgent` challenges every proposal before governance scoring. `AFRT-0`: structurally incapable of approving — PASS or RETURNED only. Eliminates the single-agent approval failure mode present in all prior autonomous code systems.
</details>

<details>
<summary><b>🧬 March 28, 2026 — Morphogenetic Memory (Phase 94 · INNOV-10)</b></summary>
<br/>

`IdentityLedger` — 8 founding `IdentityStatement`s, hash-chained, HUMAN-0-attested. `IdentityContextInjector` fires Phase 0d before proposals are generated. First system to ask: *is this mutation consistent with what this system believes itself to be?*
</details>

<details>
<summary><b>🌙 March 30, 2026 — Cross-Epoch Dream State Engine (Phase 96 · INNOV-11)</b></summary>
<br/>

Between active epochs, `DreamStateEngine` replays successful past mutations in novel cross-epoch combinations — analogous to offline synaptic replay in biological memory systems.
</details>

<details>
<summary><b>⚖️ April 1, 2026 — Constitutional Jury System (Phase 99 · INNOV-14)</b></summary>
<br/>

High-stakes mutations require 2-of-3 independent agent jury verdict before governance gate. Dissenting verdicts cryptographically committed and fed to `InvariantDiscoveryEngine`.
</details>

<details>
<summary><b>🔭 April 4, 2026 — Innovations36 DAS (Phase 121 · INNOV-36)</b></summary>
<br/>

All 36 constitutional innovations shipped. 121 phases complete. 162 Hard-class invariants. `boot_completeness_check()` confirms all core modules importable at runtime. The Innovations pipeline is architecturally sealed — every innovation enforced, chained, and auditable via `docker compose up das-demo`.
</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Why you can trust the claims

**⛓ Tamper-evident ledger** — SHA-256 hash-chained. Alter one entry and every subsequent hash breaks. History cannot be rewritten.

**♻️ Deterministic replay** — Any prior epoch re-runs from original inputs producing byte-identical results. `PYTHONHASHSEED=0` enforced. `CEL-REPLAY-0`.

**📜 Constitutional gate** — Runtime-enforced rules. Violation halts epoch. No config option changes this.

**⚔️ Adversarial red-team gate** — Every mutation challenged before scoring. Cannot approve. `AFRT-0`.

**🛡 Shadow execution gate** — Zero-write harness before live promotion. `LSME-0`.

**🔬 Identity gate** — Self-model consulted before proposals are generated. `MMEM-0`.

**⚖️ Constitutional jury gate** — 2-of-3 verdict for high-stakes mutations. Dissent feeds invariant discovery. `CJS-QUORUM-0`.

**🌡 Entropy budget gate** — Constitutional change velocity is itself governed. 30% drift cap. `CEB-0`.

**👁 Self-awareness invariant** — No mutation may reduce self-monitoring observability. `SELF-AWARE-0`.

**🗺 Cryptographic lineage** — Merkle-rooted proof DAG. Independently verifiable without system access. `CEPD-0`.

**🔑 Human authority is structural** — GPG key required for Tier 0. Not configurable. `HUMAN-0`.

**🚧 162 Hard-class invariants** — Cannot be disabled, configured around, or violated without epoch abort.

→ [Read the Constitution](docs/CONSTITUTION.md) · [Trust Center](TRUST_CENTER.md) · [Security Invariants Matrix](docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md)

![Section Divider](docs/assets/readme/inline-divider.svg)

## About the versioning

ADAAD uses a **phase-correlated version scheme** by design. Each minor increment in the `v9.x.0` series corresponds to one shipped, HUMAN-0-attested, evidence-linked governance phase.

`v9.56.0` means 123 governed phase milestones have shipped in the v9 series — not 123 traditional semver API additions. Each phase has: a governance ledger event, a HUMAN-0 `session_digest` sign-off, 30 passing acceptance tests, a CHANGELOG entry, and a four-file canonical version sync (`VERSION` · `pyproject.toml` · `CHANGELOG.md` · `.adaad_agent_state.json`).

![Section Divider](docs/assets/readme/inline-divider.svg)

## What you control vs. what the system handles

| **What only you can do** | **What ADAAD handles autonomously** |
|:---|:---|
| 🔑 GPG-sign Tier 0 changes | Generate mutation proposals via Claude agents |
| 🌱 Approve seed promotions | Red-team challenge every proposal before scoring |
| 📜 Set constitutional rules | Shadow-execute mutations in zero-write harness |
| 🏷 Tag version ceremonies | Score against 162 constitutional invariants |
| ⚙️ Ratify new Hard-class invariants | Hash-chain every decision into the ledger |
| 🧬 Amend `IdentityLedger` statements | Consult self-model before every proposal |
| 📋 Patent and IP decisions | Build cryptographic evolution proof DAGs |
| ✅ GA sign-off | Mine failure patterns · propose new invariants |
| 🏛 Jury composition policy | Convene constitutional jury for high-stakes paths |

![Section Divider](docs/assets/readme/inline-divider.svg)

<a name="quickstart"></a>
## Quickstart

```bash
git clone https://github.com/InnovativeAI-adaad/adaad.git
cd adaad
python onboard.py
```

`onboard.py` sets up your environment, validates governance schemas, and runs a governed dry-run. Safe to re-run any time. It will install core dependencies but **not** the `server.py` specific ones.

**What success looks like:**
```
  ✔ Python 3.12.x
  ✔ Dependencies installed
  ✔ Boot completeness: 36/36 innovations importable [INNOV-COMPLETE-0]
  ✔ Dry-run complete  (fail-closed behaviour confirmed)

  Run the dashboard   python server.py
  Run an epoch        adaad demo
  Inspect ledger      adaad inspect-ledger data/evolution_ledger.jsonl
  Propose mutation    adaad propose "upgrade system x"
  Strict replay       python -m app.main --replay strict --verbose
```

### CLI Interface

ADAAD Phase 123 introduces a formal CLI. To use it, ensure `scripts/` is in your PATH or call it directly:

```bash
./scripts/adaad --help
./scripts/adaad demo              # Run a dry-run epoch
./scripts/adaad inspect-ledger    # View ledger summary
./scripts/adaad propose "desc"    # Submit a mutation proposal
```

### Local Development Server

To run the ADAAD API server for local development and access the UI dashboards (Aponi, Whale.Dic), follow these steps:

1.  **Install server dependencies:**
    ```bash
    pip install -r requirements.server.txt
    ```

2.  **Run the server (authentication disabled for dev):**
    For a seamless local development experience, the server can be run with API authentication temporarily disabled via the `ADAAD_AUDIT_TOKENS` environment variable. This allows the UI to fetch data without needing bearer tokens.
    ```bash
    ADAAD_AUDIT_TOKENS="" uvicorn server:app --host 127.0.0.1 --port 8000
    ```
    (You can run this in the background using `nohup ... &` or similar if you need to continue using the terminal.)

3.  **Access the UI dashboards:**
    Open your web browser and navigate to:
    *   **Developer Whale.Dic (Dork):** `http://127.0.0.1:8000/ui/developer/ADAADdev/whaledic.html`
    *   **Aponi Dashboard:** `http://127.0.0.1:8000/ui/aponi/index.html`

    If you wish to use the Dork AI assistant, click the gear icon (⚙) in the UI and provide your Anthropic API key. This key is stored only in your browser's session.


### Deterministic environment (reproducible evidence hashes)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
export ADAAD_SEED=42 PYTHONHASHSEED=0
python nexus_setup.py --validate-only
python -m app.main --replay audit --verbose
```

<details>
<summary><b>Platform support</b></summary>
<br/>

| Platform | Method |
|:---|:---|
| Linux / macOS | `pip install adaad` or clone above |
| Windows | `pip install adaad` (WSL2 for sandbox) |
| Android (Termux) | [TERMUX_SETUP.md](TERMUX_SETUP.md) |
| Android (Pydroid 3) | [INSTALL_ANDROID.md](INSTALL_ANDROID.md) |
| Docker | `docker pull ghcr.io/innovativeai-adaad/adaad` |

*ADAAD's safety properties come from SHA-256 hash chains and the Python runtime — not cloud KMS, Kubernetes, or any third-party service.*

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Replay and audit

### Verify the Phase 65 self-evolution event (the founding milestone)

```bash
python -m app.main --replay strict --epoch-id phase65-emergence-001 --verbose
# Expected: byte-identical evidence_hash, APPROVED verdict, 1 mutation applied
# Divergence = blocking integrity signal. Check: Python version, PYTHONHASHSEED, deps.
```

### Inspect governance event chain

```bash
python -c "
import json
from runtime.memory.identity_ledger import IdentityLedger
ledger = IdentityLedger.load_genesis()
print('Chain valid:', ledger.verify_chain())
print('Statements:', len(ledger))
for s in ledger.statements():
    print(f'  {s.statement_id}: {s.statement[:60]}...')
"
```

### Confirm no unauthorized imports

```bash
python scripts/check_spdx_headers.py
# All files must carry: # SPDX-License-Identifier: Apache-2.0
# Violations are printed and cause CI failure.
```

![Section Divider](docs/assets/readme/inline-divider.svg)

## Governance in 60 seconds

ADAAD evolves through numbered phases. Each phase ships a specific capability, registers findings, resolves them with evidence, and chains a governance ledger entry before merge.

### Recent phases

| Phase | Innovation | Invariants added | Status |
|:---:|:---|:---:|:---:|
| 92 | Adversarial Fitness Red Team (AFRT) | AFRT-0 · GATE-0 · INTEL-0 · LEDGER-0 · CASES-0 · DETERM-0 | ✅ Shipped |
| 93 | Aesthetic Fitness Signal (AFIT) | AFIT-0 · DETERM-0 · BOUND-0 · WEIGHT-0 | ✅ Shipped |
| 94 | Morphogenetic Memory (MMEM) | MMEM-0 · CHAIN-0 · READONLY-0 · WIRE-0 · LEDGER-0 · DETERM-0 | ✅ Shipped |
| 123 | CLI Entry Point | CLI-SANDBOX-0 · CLI-GATE-0 | ✅ Shipped |

### Governance event chain

Every HUMAN-0 sign-off is recorded in `security/ledger/governance_events.jsonl` as a hash-chained event. Chain verification:

```bash
python -c "
import json, hashlib
events = [json.loads(l) for l in open('security/ledger/governance_events.jsonl')]
print(f'Governance events: {len(events)}')
print(f'Latest: {events[-1][\"event_id\"]}')
print(f'Latest hash: {events[-1][\"event_hash\"][:32]}...')
"
```

<details>
<summary><b>How a phase ships (contributor reference)</b></summary>
<br/>

1. ArchitectAgent produces a specification for the phase
2. MutationAgent implements on a `feature/phase<N>-*` branch
3. TIER 0 invariant checks pass + `pytest` green + no regressions
4. HUMAN-0 signs off verbally (`Approved. All signed: Dustin L. Reid`)
5. `--no-ff` merge to main (lineage preserved — mandatory)
6. CHANGELOG entry + VERSION bump + semantic GPG-signed tag
7. Agent state updated + governance ledger event chained
8. Push

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## For contributors

<details>
<summary><b>Required reading before opening any PR</b></summary>
<br/>

- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, PR flow, required checks
- [docs/CONSTITUTION.md](docs/CONSTITUTION.md) — 27 constitutional rules, governance philosophy
- [docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md](docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md) — all Hard-class invariants

</details>

<details>
<summary><b>Local checks before every PR</b></summary>
<br/>

```bash
# 1. Tests — all must pass
pytest --tb=short -q

# 2. SPDX headers — all source files
python scripts/check_spdx_headers.py

# 3. Import boundaries
python scripts/check_dependency_baseline.py

# 4. License check
python scripts/check_licenses.py

# 5. Replay integrity
python -m app.main --replay audit --verbose

# 6. Workspace validation
python nexus_setup.py --validate-only
```

</details>

<details>
<summary><b>PR evidence requirements</b></summary>
<br/>

Every governance-impacting PR must include in its description:
- **Branch name**: `feature/phase<N>-<descriptor>` or `fix/phase<N>-<descriptor>`
- **Test count**: number of new tests added
- **Invariants**: any new Hard-class invariants introduced
- **Evidence hash**: from a local epoch run
- **HUMAN-0 sign-off**: governor approval before merge

PRs without evidence artifacts are returned, not merged.

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Security and trust center

**SPDX enforcement** — Every source file must carry `# SPDX-License-Identifier: Apache-2.0`. Missing headers block merge via CI.

**Import boundary enforcement** — Module seams are defined and enforced. Cross-layer imports without boundary contract updates block merge via `AST-IMPORT-0`.

**Replay divergence** — Any divergence from expected evidence hash is treated as a blocking integrity signal. Not a warning. A block.

**Key management** — HUMAN-0 GPG key (`4C95E2F99A775335B1CF3DAF247B015A1CCD95F6`) signs all release tags and Tier 0 governance events. Key is not stored in this repository.

**IdentityLedger attestation** — ILA-94-2026-03-28-001 attests the genesis seed terminal hash `3f5706...`. External auditors can verify independently.

**Report security issues** via the issue template `SECURITY.md`. Do not open public issues for vulnerability reports.

→ [Full Trust Center](TRUST_CENTER.md) · [Compliance Pack](docs/compliance/)

![Section Divider](docs/assets/readme/inline-divider.svg)

## Live system stats

<!-- AUTO-UPDATED: stats card regenerates on every merge to main -->
![System Stats](docs/assets/readme/inline-stats_card.svg)

<div align="center">

![GitHub commit activity](https://img.shields.io/github/commit-activity/m/InnovativeAI-adaad/adaad?style=flat-square&labelColor=0d1117&color=00d4ff&label=Commits%2Fmonth)&nbsp;![GitHub last commit](https://img.shields.io/github/last-commit/InnovativeAI-adaad/adaad?style=flat-square&labelColor=0d1117&color=00ff88&label=Last%20commit)&nbsp;![GitHub repo size](https://img.shields.io/github/repo-size/InnovativeAI-adaad/adaad?style=flat-square&labelColor=0d1117&color=a855f7&label=Repo%20size)&nbsp;![GitHub issues](https://img.shields.io/github/issues/InnovativeAI-adaad/adaad?style=flat-square&labelColor=0d1117&color=ff4466&label=Open%20issues)

</div>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Mythic identity

The ADAAD system uses named operational roles. These are runtime roles, not marketing.

| Name | Role |
|:---|:---|
| **Architect** | Structural mutation agent. Prioritizes maintainability and constitutional alignment. |
| **Dream** | Exploratory mutation agent. Novel approaches, capability gap identification. |
| **Beast** | Performance mutation agent. Throughput, efficiency, bottleneck pressure. |
| **Cryovant** | Identity and device-anchoring layer. Session tokens, audit signatures, trust anchoring. |
| **Aponi** | Governance dashboard. Audit UI, mutation lineage viewer, live epoch status. |
| **HUMAN-0** | The governor role. Dustin L. Reid. Holds GPG key. Ratifies constitutional changes. |

*ADAAD names clarify runtime roles and UX flows. They are not APIs and not marketing personas.*

![Section Divider](docs/assets/readme/inline-divider.svg)

## Enterprise and commercial use

<details>
<summary><b>Commercial documentation suite</b></summary>
<br/>

| Resource | What it is |
|:---|:---|
| [Pricing Model](docs/commercial/PRICING_MODEL.md) | Seat-based, usage-based, and hybrid SKUs |
| [Procurement Fast-Lane](docs/commercial/procurement_fastlane/DAY0_PROCUREMENT_FASTLANE_CHECKLIST.md) | Day-0 checklist, DPA/MSA fallback clauses, security Q&A — designed for 5-day close |
| [SLO / SLA Sheet](docs/commercial/procurement_fastlane/SLA_SLO_SHEET.md) | Reliability targets and support tier commitments |
| [Compliance Pack](docs/compliance/) | Data handling, access control matrix, incident response |
| [Trust Center](TRUST_CENTER.md) | Security posture and governance assurance artifacts |
| [Certification Program](docs/training/CERTIFICATION_PROGRAM.md) | Operator · Governance Engineer · Enterprise Administrator |
| [Partner Program](docs/commercial/PARTNER_PROGRAM.md) | Integrator and consultancy onboarding |
| [Data Room Index](docs/strategy/DATA_ROOM_INDEX.md) | Due-diligence artifact map |
| [ROI Model](docs/commercial/ROI_MODEL.md) | Value quantification framework for governance automation |

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## What ADAAD is not

- ❌ **Not a code assistant** — it doesn't autocomplete your code or answer questions
- ❌ **Not CI/CD** — it governs the mutation process, not the build pipeline
- ❌ **Not fully autonomous** — your sign-off is constitutionally required for critical changes
- ❌ **Not a security scanner** — it enforces mutation governance, not vulnerability detection
- ❌ **Not magic** — every decision is logged, hash-chained, replayable, and explainable

![Section Divider](docs/assets/readme/inline-divider.svg)

## FAQ

<details>
<summary><b>Is this actually running autonomously?</b></summary>
<br/>

Yes. Phase 65 (March 13, 2026) was the first epoch where ADAAD identified a capability gap, generated a mutation, ran it through all fitness and governance layers, and applied it with zero human intervention in the execution path. Phase 89 activated live LLM proposals in production.

Human oversight is structural, not optional. Dustin L. Reid holds the governor role. Any Tier 0 mutation requires his GPG-signed approval. That is not configurable.
</details>

<details>
<summary><b>What makes this different from just running tests in CI?</b></summary>
<br/>

CI tests whether known code passes known assertions. ADAAD governs whether *changes to the codebase itself* are constitutionally valid, adversarially stress-tested, fitness-improving, and deterministically replayable.

You can delete your CI history. You cannot alter ADAAD's ledger.

ADAAD actively challenges its own proposals via adversarial red-team agents, checks them against its encoded self-model, and runs them through zero-write shadow execution before they reach production. No CI system does this. No CI system has constitutional rules it's bound by. No CI system produces a cryptographic proof of its evolutionary lineage.
</details>

<details>
<summary><b>How does the adversarial Red Team work?</b></summary>
<br/>

Every mutation proposal is handed to `AdversarialRedTeamAgent` before fitness scoring. It queries `CodeIntelModel` for code paths the proposing agent didn't cover, then generates up to five targeted adversarial cases. Each runs in a read-only sandbox.

If any case falsifies the proposal, it's returned with a `RedTeamFindingsReport`. `AFRT-0`: the agent cannot approve — structurally enforced in code, not policy. Its only outputs are PASS or RETURNED.
</details>

<details>
<summary><b>What is Morphogenetic Memory?</b></summary>
<br/>

MMEM (INNOV-10, Phase 94) is a formally encoded architectural self-model: a hash-chained, HUMAN-0-gated, append-only `IdentityLedger` containing founding `IdentityStatement`s that define what ADAAD believes itself to be.

Before every epoch's proposals are generated (Phase 0d), the `IdentityContextInjector` consults the ledger and injects `identity_consistency_score` into `CodebaseContext`. This score is available to all downstream stages.

It answers the question no prior gate could ask: *is this mutation consistent with what this system believes itself to be?*
</details>

<details>
<summary><b>What are the shipped innovations?</b></summary>
<br/>

ADAAD has shipped 36 core innovations across v9.18.0–v9.54.0 (Phases 87–121): Constitutional Self-Amendment (CSAP), Adversarial Constitutional Stress (ACSE), Temporal Invariant Forecasting (TIFE), Semantic Drift Detection (SCDD), Autonomous Organ Emergence (AOEP), Cryptographic Evolution Proof DAG (CEPD), Live Shadow Mutation Execution (LSME), Adversarial Fitness Red Team (AFRT), Aesthetic Fitness Signal (AFIT), Morphogenetic Memory (MMEM), and more.

Full specifications: [ADAAD_30_INNOVATIONS.md](ADAAD_30_INNOVATIONS.md)
</details>

<details>
<summary><b>Why does it run on a $200 Android phone?</b></summary>
<br/>

Constitutional governance should not require enterprise infrastructure. ADAAD's safety properties come from SHA-256 hash chains and the Python runtime — not cloud KMS, Kubernetes, or any third-party service. If those go away, so do your safety guarantees. ADAAD's guarantees are local, deterministic, and yours.
</details>

<details>
<summary><b>How do I evaluate ADAAD for enterprise procurement?</b></summary>
<br/>

Start with the [Trust Center](TRUST_CENTER.md). The [Procurement Fast-Lane package](docs/commercial/procurement_fastlane/DAY0_PROCUREMENT_FASTLANE_CHECKLIST.md) is designed to complete security and legal review within 5 business days. A [Certification Program](docs/training/CERTIFICATION_PROGRAM.md) is available for operators, governance engineers, and enterprise administrators.
</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Roadmap

**Innovations pipeline complete as of Phase 121.** 123 phases complete. 162 Hard-class invariants.
**Short term** — Phase 124 (adaad-core extraction), community governance infrastructure, formal GA release hardening.

**Mid term** — device-anchored mobile runtime graduation, reproducible packaging, cross-device federation.

**Long term** — Full autonomy graduation, v1.1-GA Release.

→ [Full roadmap](ROADMAP.md) · [36 Innovations specification](ADAAD_30_INNOVATIONS.md)

![Section Divider](docs/assets/readme/inline-divider.svg)

<div align="center">

![World's Firsts](docs/assets/readme/inline-worlds_firsts.svg)

<br/><br/>

**Built by [Innovative AI LLC](https://github.com/InnovativeAI-adaad) · Governor: Dustin L. Reid · Blackwell, Oklahoma**

*The next wave of AI isn't AI that writes your code.*
*It's AI that governs itself while writing your code —*
*and can prove it.*

<br/>

**[⚡ Get Started](#quickstart)** &nbsp;·&nbsp; **[📜 Constitution](docs/CONSTITUTION.md)** &nbsp;·&nbsp; **[📖 Thesis](docs/thesis/ADAAD_THESIS.md)** &nbsp;·&nbsp; **[🗺 Roadmap](ROADMAP.md)** &nbsp;·&nbsp; **[🏛 Trust Center](TRUST_CENTER.md)**

<br/>

*Build without limits. Govern without compromise.*

</div>
