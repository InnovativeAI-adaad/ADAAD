<div align="center">

<!-- ADAAD_VERSION_HERO:START -->
![ADAAD Hero Banner](docs/assets/readme/inline-hero_banner.svg)
<!-- ADAAD_VERSION_HERO:END -->

<br/>

<a href="#quickstart">⚡ Quickstart</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/CONSTITUTION.md">📜 Constitution</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="ROADMAP.md">🗺 Roadmap</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/thesis/ADAAD_THESIS.md">📖 Thesis</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="DORK.md">🕵️ DORK</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="TRUST_CENTER.md">🏛 Trust Center</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/VERIFIABLE_CLAIMS.md">✅ Verifiable Claims</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="CHANGELOG.md">📋 Changelog</a>

<br/>

[![Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-00d4ff?style=flat-square&labelColor=0d1117)](LICENSE)&nbsp;[![Python 3.12](https://img.shields.io/badge/python-3.12-00ff88?style=flat-square&labelColor=0d1117)](https://python.org)&nbsp;[![v9.79.0](https://img.shields.io/badge/version-v9.79.0-a855f7?style=flat-square&labelColor=0d1117)](CHANGELOG.md)&nbsp;[![251 Invariants](https://img.shields.io/badge/invariants-251%20Hard--class-ff4466?style=flat-square&labelColor=0d1117)](docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md)&nbsp;[![52 Innovations](https://img.shields.io/badge/innovations-52%20shipped-f97316?style=flat-square&labelColor=0d1117)](ROADMAP.md)&nbsp;[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/InnovativeAI-adaad/adaad?style=flat-square&labelColor=0d1117&color=00d4ff&label=Commits%2Fmonth)](https://github.com/InnovativeAI-adaad/adaad/commits/main)

</div>

![Section Divider](docs/assets/readme/inline-divider.svg)

<div align="center">

## The only AI system that governs its own evolution — and can prove it.

**Every mutation flows through a 16-step Constitutional Evolution Loop. Every decision is sealed in a hash-chained cryptographic proof. Your GPG key is the only key that unlocks critical changes. That last part is not configurable.**

</div>

![Section Divider](docs/assets/readme/inline-divider.svg)

## What ADAAD is not

ADAAD is **not** an agent framework, not an LLM wrapper, not a dev tool, and not an automation pipeline.

It is a **governance engine** that happens to evolve software. The distinction matters: every other system bolts governance on. ADAAD builds it in — constitutionally, cryptographically, structurally.

![Section Divider](docs/assets/readme/inline-divider.svg)

## Why ADAAD exists

Four problems that no other system solves simultaneously:

| Problem | Why it matters |
|:--------|:---------------|
| AI systems self-modify without constraint | Unauditable, irreversible, dangerous |
| AI systems stagnate without self-improvement | Brittle, expensive to maintain |
| Governance is bolted on, not built in | Bypassable, inconsistent, theatrical |
| No system provides cryptographic proof of its own evolution | Claims without evidence |

**ADAAD solves all four** — in production, with a public ledger and replay instructions for every claim.

![Section Divider](docs/assets/readme/inline-divider.svg)

## In numbers

| Metric | Value |
|:-------|:------|
| Current version | `v9.79.0` · Phase `146` |
| Hard-class constitutional invariants | **251** |
| Shipped innovations | **52** |
| Constitutional Evolution Loop | **16 steps** — deterministic, replayable |
| Specialist agents | **3** — Architect · Dream · Beast |
| HUMAN-0 gate | **1** — structurally non-delegatable |
| Append-only ledger entries | **48,000+** |

![Section Divider](docs/assets/readme/inline-divider.svg)

## Who is ADAAD for?

| Audience | Why ADAAD |
|:---------|:----------|
| **AI safety researchers** | The first cryptographically evidenced autonomous governance loop in production |
| **Autonomous systems engineers** | Reference architecture for constitutional self-modification |
| **Governance architects** | 251 Hard-class invariants mapped to real operational guarantees |
| **Indie devs on Android** | Full governed runtime on a $200 phone — TERMUX_SETUP.md |
| **Constitutional AI contributors** | Open, governed amendment pipeline — all contributions traverse the CEL |

![Section Divider](docs/assets/readme/inline-divider.svg)

## <a id="quickstart"></a>Quickstart

```bash
git clone https://github.com/InnovativeAI-adaad/ADAAD.git
cd ADAAD
python onboard.py
```

`onboard.py` handles environment setup, schema validation, and a governed dry-run.

**What success looks like:**

```
  ✔ Python 3.12.x
  ✔ Virtual environment created (.venv)
  ✔ Dependencies installed
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

**Install from PyPI:**

```bash
pip install adaad
```

**Android / Termux:** Full governed runtime on a $200 phone. See [`TERMUX_SETUP.md`](TERMUX_SETUP.md).

![Section Divider](docs/assets/readme/inline-divider.svg)

## Component map

| Component | Purpose | Where it lives |
|:----------|:--------|:---------------|
| **ADAAD** | Full autonomous evolution engine — 16-step CEL, 3 agents, governance loop | repo root |
| **adaad-core** | Governance-critical primitives, extractable as a standalone PyPI package | `adaad/core/` |
| **DORK** | Governance intelligence layer — natural language interface to the constitutional ledger | `dorkllm/` · `ui/dork.html` |

These are not interchangeable. `adaad-core` can be embedded in any Python project. DORK can be queried standalone. The full ADAAD engine requires both.

![Section Divider](docs/assets/readme/inline-divider.svg)

## The three agents

```
┌──────────────┬──────────────────────────────────────────┬──────────────────────────┐
│    Agent     │               Role                       │       Disposition        │
├──────────────┼──────────────────────────────────────────┼──────────────────────────┤
│  Architect   │  Governance, structure, invariant check  │  Conservative. Blocks    │
│  (blue)      │  Scores every mutation for compliance    │  anything that breaks    │
│              │  with all 251 Hard-class invariants      │  constitutional integrity │
├──────────────┼──────────────────────────────────────────┼──────────────────────────┤
│  Dream       │  Creativity, ideation, novelty           │  Bold. Proposes novelty. │
│  (violet)    │  Explores the mutation possibility space │  Checked by every other  │
│              │  inside constitutional guardrails        │  layer before it ships   │
├──────────────┼──────────────────────────────────────────┼──────────────────────────┤
│  Beast       │  Performance, resource fitness           │  Relentless. Maximizes   │
│  (orange)    │  Benchmark scoring, optimization         │  fitness within          │
│              │  Hardware-adaptive evaluation            │  constitutional bounds   │
└──────────────┴──────────────────────────────────────────┴──────────────────────────┘
```

None of the three can approve their own proposals. The AFRT is structurally prohibited from approving challenges it authored — constitutional invariant `AFRT-0`.

![Section Divider](docs/assets/readme/inline-divider.svg)

<details>
<summary><strong>Constitutional Evolution Loop — 16 Steps (expand)</strong></summary>

```
┌─────────────────────────────────────────────────────────────────────────┐
│              CONSTITUTIONAL EVOLUTION LOOP (CEL) — 16 STEPS             │
│                      Every mutation. No exceptions.                      │
└─────────────────────────────────────────────────────────────────────────┘

  [1]  SPIE proposes innovation        [9]  Live Shadow Mutation Execution
  [2]  Morphogenetic memory consult    [10] Blast radius modelling
  [3]  Dream agent ideation            [11] Constitutional jury verdict (2-of-3)
  [4]  Architect structural review     [12] GovernanceGate final arbiter
  [5]  Beast performance scoring       [13] HUMAN-0 gate (Tier-0 changes only)
  [6]  AFRT adversarial red-team       [14] GPG-signed ledger entry
  [7]  Fitness surface evaluation      [15] Hash-chained CEPD proof
  [8]  251-invariant constitutional    [16] Annotated tag + release evidence
       scoring
```

Every step is deterministic. Every step produces a ledger record. Every ledger record is hash-chained to its predecessor. The entire pipeline is replayable from any point in history:

```bash
python -m app.main --replay strict --verbose
```

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## Security guarantees

These are structural guarantees — not policies, not configuration, not best practices. They are constitutionally enforced and cryptographically evidenced.

| Guarantee | Invariant | What it prevents |
|:----------|:----------|:-----------------|
| No mutation bypasses governance | `GOV-SOLE-0` | GovernanceGate bypass |
| No agent approves its own proposal | `AFRT-0` | Adversarial self-approval |
| No constitutional change without HUMAN-0 | `COMMUNITY-HUMAN0-0` | Autonomous self-amendment |
| No mutation reduces observability | `SELF-AWARE-0` | Blind spots in the governed loop |
| No unpinned Docker images in production | `DAS-DOCKER-0` | Supply chain drift |
| No innovation auto-approved without ratification | `SPIE-HUMAN0-0` | Unapproved capability injection |
| No persistent memory disabled at runtime | `DPM-GATE-0` | Silent memory layer bypass |
| No query bypasses the routing ledger | `DQR-ROUTE-0` | Unlogged subsystem access |
| No route override without constant-time auth | `DQR-AUTH-0` | Timing-attack policy manipulation |

Every invariant violation raises a typed exception, terminates the operation, and generates a ledger entry. There is no silent failure path.

![Section Divider](docs/assets/readme/inline-divider.svg)

## 🌍 World's firsts — verified, replayable, publicly auditable

<details>
<summary><strong>Governance primitives</strong></summary>

| # | Claim | Evidence |
|:---:|:---|:---:|
| **1** | First constitutionally governed autonomous codebase to self-evolve in production | [→ Phase 65](CHANGELOG.md) |
| **2** | First 16-gate Constitutional Evolution Loop with cryptographic proof per mutation | [→ CEL](#the-pipeline) |
| **3** | First non-bypassable GovernanceGate as a constitutional primitive (`GOV-SOLE-0`) | [→ Architecture](#architecture) |
| **7** | First AI system with a meta-governance entropy budget governing its own constitutional change velocity (`CEB-0`) | [→ INNOV-26](ROADMAP.md) |
| **8** | First autonomous governance kernel extractable as a standalone semver-managed package (`adaad-core`) | [→ Phase 124](CHANGELOG.md) |
| **8b** | First constitutionally governed community amendment pipeline — structurally incapable of autonomous constitutional change | [→ Phase 125](CHANGELOG.md) |

</details>

<details>
<summary><strong>Adversarial safety</strong></summary>

| # | Claim | Evidence |
|:---:|:---|:---:|
| **4** | First adversarial red-team agent structurally incapable of approving its own challenges (`AFRT-0`) | [→ INNOV-08](ROADMAP.md) |
| **12** | First autonomous system with deterministic audit sandbox for one-command third-party verification | [→ INNOV-36](ROADMAP.md) |
| **13** | First constitutionally governed Red-Team Response Engine with HUMAN-0-gated amendment routing (`GRRP`) | [→ INNOV-37](ROADMAP.md) |
| **14** | First adversarially-driven constitutional self-amendment engine with cryptographic provenance (`ACSA`) | [→ INNOV-38](ROADMAP.md) |

</details>

<details>
<summary><strong>Constitutional self-awareness</strong></summary>

| # | Claim | Evidence |
|:---:|:---|:---:|
| **5** | First hash-chained identity self-model consulted before every mutation proposal (`MMEM-0`) | [→ INNOV-10](ROADMAP.md) |
| **6** | First constitutional jury requiring 2-of-3 multi-agent verdict for high-stakes mutations (`CJS-0`) | [→ INNOV-14](ROADMAP.md) |
| **9** | First governed AI system with `SELF-AWARE-0`: no mutation may reduce self-monitoring observability | [→ INNOV-28](ROADMAP.md) |
| **10** | First AI to pass its own constitutional self-recognition test before promotion (`mirror_test.py`) | [→ INNOV-30](ROADMAP.md) |
| **16** | First AI system with a Self-Proposing Innovation Engine: system proposes its own next capabilities, HUMAN-0 ratifies | [→ INNOV-35](ROADMAP.md) |

</details>

<details>
<summary><strong>Evolution, memory & replayability</strong></summary>

| # | Claim | Evidence |
|:---:|:---|:---:|
| **11** | First governed AI codebase designed to run fully locally on a $200 Android phone | [→ Android](#platform-support) |
| **15** | First governed agent coalition formation system with proportional stake redistribution (`ACF`) | [→ INNOV-39](ROADMAP.md) |
| **17** | First Retrieval-Augmented Governance Synthesis layer grounding agent responses in constitutional precedent (`RAGS`) | [→ INNOV-50](ROADMAP.md) |
| **18** | First session-agnostic, HMAC-chained persistent memory layer for an autonomous governance agent (`DPM`) | [→ INNOV-51](ROADMAP.md) |
| **19** | First constitutionally governed query router with priority-dispatch, fallback-safe invariant enforcement, and HUMAN-0-gated policy override (`DQR`) | [→ INNOV-52](ROADMAP.md) |

</details>

All claims are independently verifiable. See [docs/VERIFIABLE_CLAIMS.md](docs/VERIFIABLE_CLAIMS.md) for replay instructions.

![Section Divider](docs/assets/readme/inline-divider.svg)

## Shipped capabilities — 52 innovations

<details>
<summary><strong>INNOV-01 through INNOV-20</strong> — Core governance primitives</summary>

| Innovation | Module | What it does |
|:---|:---|:---|
| **INNOV-01 · CSAP** | `constitutional_stress_test.py` | Adversarial stress-testing of constitutional invariants under pathological inputs |
| **INNOV-02 · ACSE** | `self_awareness_invariant.py` | System must recognize its own constitution before being permitted to mutate |
| **INNOV-03 · TIFE** | `temporal_governance.py` | Temporal governance: stale mutation proposals auto-expire; no zombie changes |
| **INNOV-04 · SCDD** | `constitutional_entropy_budget.py` | Entropy budget: constitutional change velocity is itself rate-limited |
| **INNOV-05 · AOEP** | `governance_archaeology.py` | Full excavation of mutation lineage on demand |
| **INNOV-06 · CEPD** | `counterfactual_fitness.py` | Cryptographic Evolution Proof DAG: every fitness decision is hash-chained |
| **INNOV-07 · LSME** | `temporal_regret.py` | Live Shadow Mutation Execution: mutations run against live traffic before promotion |
| **INNOV-08 · AFRT** | `red_team_agent.py` | Adversarial red-team agent structurally incapable of self-approval |
| **INNOV-09 · AFIT** | `aesthetic_fitness.py` | Aesthetic fitness: code quality and elegance as measurable, scored dimensions |
| **INNOV-10 · MMEM** | `morphogenetic_memory.py` | Hash-chained identity self-model consulted before every mutation proposal |
| **INNOV-11 · DSTE** | `dream_state.py` | Dream State Engine: structured creative exploration inside constitutional guardrails |
| **INNOV-12 · MGV** | `mutation_genealogy.py` | Full mutation genealogy — every change traces to its ancestor |
| **INNOV-13 · IMT** | `knowledge_transfer.py` | Inter-agent knowledge transfer with cryptographic provenance |
| **INNOV-14 · CEB** | `constitutional_entropy_budget.py` | Constitutional jury: 2-of-3 multi-agent verdict required for high-stakes mutations |
| **INNOV-15 · CTD** | `constitutional_tension.py` | Surfaces invariant conflicts before they collide in production |
| **INNOV-16 · ERS** | `emergent_roles.py` | Agents adapt their function within constitutional bounds as the system matures |
| **INNOV-17 · APM** | `agent_postmortem.py` | Every failed mutation generates a root-cause ledger entry |
| **INNOV-18 · GJR** | `constitutional_jury.py` | Governance jury protocol with quorum enforcement |
| **INNOV-19 · RST** | `reputation_staking.py` | Agents stake credibility on proposals; losses are permanent and ledger-recorded |
| **INNOV-20 · BRM** | `blast_radius_model.py` | Blast radius modelling: mutation impact surface quantified before approval |

</details>

<details>
<summary><strong>INNOV-21 through INNOV-40</strong> — Advanced autonomy and federation</summary>

| Innovation | Module | What it does |
|:---|:---|:---|
| **INNOV-21 · GBP** | `governance_bankruptcy.py` | Graceful degradation when invariant pressure reaches critical threshold |
| **INNOV-22 · MCF** | `mutation_conflict_framework.py` | Resolves competing simultaneous mutation proposals |
| **INNOV-23 · CES** | `constitutional_epoch_sentinel.py` | Detects constitutional drift across long time horizons |
| **INNOV-24 · SVP** | `semantic_version_enforcer.py` | Version increments are constitutionally mandated and enforced |
| **INNOV-25 · HAF** | `hardware_adaptive_fitness.py` | Fitness scoring adjusts to available compute |
| **INNOV-26 · GDA** | `graduated_invariants.py` | Invariant weight scales with mutation risk tier |
| **INNOV-27 · RCI** | `regulatory_compliance.py` | Maps constitutional invariants to external regulatory standards |
| **INNOV-28 · IPV** | `intent_preservation.py` | Confirms mutations honour original design intent |
| **INNOV-29 · CED** | `curiosity_engine.py` | Systematic exploration of underexplored capability space |
| **INNOV-30 · MIRROR** | `mirror_test.py` | System must recognize its own constitutional signature before promotion |
| **INNOV-31 · IDE** | `invariant_discovery.py` | System identifies new invariants from operational patterns |
| **INNOV-32 · CRTV** | `constitutional_rollback.py` | Any state can be restored from the cryptographic proof DAG |
| **INNOV-33 · KBEP** | `knowledge_bundle_exchange.py` | Structured inter-agent knowledge packages with provenance |
| **INNOV-34 · FGCON** | `federation_governance_consensus.py` | Multi-instance quorum for distributed deployments |
| **INNOV-35 · SPIE** | `self_proposing_innovation_engine.py` | System proposes its own next capabilities; HUMAN-0 ratifies |
| **INNOV-36 · BIRC** | `break_it_challenge.py` | Structured external red-team with governed response pipeline |
| **INNOV-37 · GRRP** | `red_team_response.py` | Governed Red-Team Response Protocol with HUMAN-0-gated constitutional amendment |
| **INNOV-38 · ACSA** | `self_amendment_engine.py` | Adversarial Constitutional Self-Amendment engine with cryptographic provenance |
| **INNOV-39 · ACF** | `coalition_formation.py` | Agent coalition formation with proportional stake redistribution |
| **INNOV-40 · CELT** | `agent_learning_transfer.py` | Governance insights propagate across the agent coalition |

</details>

<details open>
<summary><strong>INNOV-41 through INNOV-52</strong> — DORK Intelligence Stack (complete)</summary>

| Innovation | Module | What it does |
|:---|:---|:---|
| **INNOV-41 · DORK-FLEET** | `dork_living_fleet.py` | Persistent DORK agent pool with constitutional lifecycle management |
| **INNOV-42 · DFSB** | `dork_fleet_server_bridge.py` | Real-time DORK agent state exposed to the operator dashboard |
| **INNOV-43 · CVR** | `constitution_version_ledger.py` | Immutable versioned record of every constitutional amendment |
| **INNOV-47 · LKSE** | `sync_dork_corpus.py` | DORK corpus stays current with the full governance history |
| **INNOV-48 · CSS** | `embedder.py` | Vector-space semantic search over the entire constitutional corpus |
| **INNOV-49 · CMU** | `model_validator.py` | Governed LLM backend rotation with constitutional benchmark gate |
| **INNOV-50 · RAGS** | `grounded_responder.py` | DORK responses grounded in retrieved constitutional precedent (RAGS-GROUND-0) |
| **INNOV-51 · DPM** | `memory_engine.py` | Session-agnostic persistent memory; HMAC-chained ledger; confidence-gated retrieval (DPM-CHAIN-0) |
| **INNOV-52 · DQR** | `query_router.py` | Constitutional priority-dispatch: DPM → RAGS → passthrough; HUMAN-0-gated override (DQR-ROUTE-0) |

**DORK Intelligence Stack: COMPLETE** — query routing (DQR) + grounded responses (RAGS) + persistent memory (DPM) form a fully governed, HMAC-chained, session-agnostic intelligence layer.

</details>

![Section Divider](docs/assets/readme/inline-divider.svg)

## DORK — Governance Intelligence Layer

**DORK** (Developer Operator Runtime Kernel) is not a chatbot. It is the institutional memory and governance brain of ADAAD — the interface through which operators query, audit, and interrogate the entire constitutional history in natural language.

As of Phase 146, DORK operates with a fully governed three-layer intelligence stack:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DORK Intelligence Stack                           │
├─────────────────────────────────────────────────────────────────────┤
│  DQR · Query Router (INNOV-52)                                      │
│    Every query → logged RouteDecision → priority dispatch           │
│    DPM score ≥ 0.35 → DPM  |  RAGS score ≥ 0.25 → RAGS           │
│    All others → passthrough  |  HUMAN-0 override gate              │
├────────────────────┬────────────────────────────────────────────────┤
│  DPM · Persistent  │  RAGS · Grounded Response (INNOV-50)          │
│  Memory (INNOV-51) │    Constitutional corpus retrieval             │
│  Session-agnostic  │    Cosine-scored citation chains               │
│  HMAC-chained      │    Zero-grounding gate (RAGS-GATE-0)          │
│  confidence-gated  │    Hash-chained grounding ledger               │
└────────────────────┴────────────────────────────────────────────────┘
```

Ask DORK why a mutation was blocked two months ago. Ask it which invariants are under the most pressure. Ask it to explain a governance decision in plain English. It answers with citations from the ledger.

**Interface:** `ui/dork.html` — [aponi.adaad.pro](https://aponi.adaad.pro) or locally via `python server.py`  
**Streaming endpoint:** `POST /api/dork/stream`  
**Default model:** `claude-sonnet-4-6`

See [DORK.md](DORK.md) for full documentation.

![Section Divider](docs/assets/readme/inline-divider.svg)

## <a id="architecture"></a>Architecture

```
adaad/
├── adaad/core/              # Governance-critical primitives (adaad-core PyPI package)
├── runtime/evolution/       # 16-step CEL implementation
├── runtime/innovations30/   # 52 innovation registry wrappers
├── dorkllm/                 # DORK intelligence stack
│   ├── query_router.py      #   DQR — constitutional query router     (INNOV-52)
│   ├── memory_engine.py     #   DPM — session-agnostic memory         (INNOV-51)
│   ├── grounded_responder.py#   RAGS — corpus-grounded responses      (INNOV-50)
│   ├── embedder.py          #   CSS — semantic search                 (INNOV-48)
│   └── knowledge_crystallizer.py  # DPM orchestration layer
├── security/ledger/         # Tamper-evident hash-chained evolution ledger
├── app/main.py              # Full autonomous loop orchestrator
├── ui/dork.html             # DORK governance intelligence dashboard
├── server.py                # API server (POST /api/dork/stream)
├── artifacts/governance/    # Per-phase ILA, sign-off, and tier-summary artifacts
└── docs/                    # Full documentation corpus
```

![Section Divider](docs/assets/readme/inline-divider.svg)

## Governance model

ADAAD governs itself through its own [Constitution](docs/CONSTITUTION.md) — a versioned, GPG-signed document tracked in the Constitution Version Registry (INNOV-43 · CVR). Every constitutional amendment traverses the same CEL as every mutation.

**HUMAN-0** (Dustin L. Reid, InnovativeAI LLC) holds exclusive authority over GPG signing, Tier-0 ratification, and patent counsel engagement. This role cannot be delegated. It cannot be automated. It is a constitutional primitive.

![Section Divider](docs/assets/readme/inline-divider.svg)

## <a id="platform-support"></a>Platform support

| Platform | Status | Notes |
|:---------|:-------|:------|
| Linux (x86_64, ARM64) | ✅ Production | Primary target |
| macOS | ✅ Supported | Python 3.12 via Homebrew |
| Windows | ✅ Supported | PowerShell `.venv\Scripts\Activate.ps1` |
| Android (Termux) | ✅ Supported | Full runtime — see [`TERMUX_SETUP.md`](TERMUX_SETUP.md) |
| Docker | ✅ Supported | Pinned digest required — `:latest` prohibited by `DAS-DOCKER-0` |

![Section Divider](docs/assets/readme/inline-divider.svg)

## Verifiable claims

Every claim in this README has a ledger entry. Every ledger entry is hash-chained. Full verification corpus: [docs/VERIFIABLE_CLAIMS.md](docs/VERIFIABLE_CLAIMS.md).

To run the deterministic audit sandbox yourself:

```bash
docker compose up das-demo
```

One command. No configuration. No trust required.

![Section Divider](docs/assets/readme/inline-divider.svg)

## Intellectual property

ADAAD's core mechanisms — the Constitutional Evolution Loop, Cryptographic Evolution Proof DAG, Live Shadow Mutation Execution, Adversarial Fitness Red Team, Self-Proposing Innovation Engine, Retrieval-Augmented Governance Synthesis, DORK Persistent Memory, and Dork Query Router — are novel, patent-pending inventions of InnovativeAI LLC.

The codebase is open source (Apache 2.0). The underlying governance architecture constitutes proprietary IP. See [BRAND_LICENSE.md](BRAND_LICENSE.md) and [TRADEMARKS.md](TRADEMARKS.md).

![Section Divider](docs/assets/readme/inline-divider.svg)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All contributions traverse the CEL — your pull request does not bypass the pipeline.

Community constitutional amendment proposals go through the governed pipeline established in Phase 125. See [CONSTITUTION_PROPOSALS.md](CONSTITUTION_PROPOSALS.md).

![Section Divider](docs/assets/readme/inline-divider.svg)

## Links

| Resource | URL |
|:---------|:----|
| Homepage | [adaad.pro](https://adaad.pro) |
| DORK Dashboard | [aponi.adaad.pro](https://aponi.adaad.pro) |
| API | [api.adaad.pro](https://api.adaad.pro) |
| Documentation | [docs.adaad.pro](https://docs.adaad.pro) |
| PyPI | [pypi.org/project/adaad](https://pypi.org/project/adaad) |
| GitHub | [github.com/InnovativeAI-adaad/ADAAD](https://github.com/InnovativeAI-adaad/ADAAD) |
| LinkedIn | [linkedin.com/in/innovative-ai-a472513b5](https://www.linkedin.com/in/innovative-ai-a472513b5) |
| Telegram | [t.me/InnovativeAI_adaad](https://t.me/InnovativeAI_adaad) |

![Section Divider](docs/assets/readme/inline-divider.svg)

<div align="center">

**Built by [InnovativeAI LLC](https://adaad.pro) · Apache 2.0 · [adaad.pro](https://adaad.pro)**

---

*ADAAD is built on a simple belief:*  
*AI should evolve — but only under a constitution, with evidence, and with a human at the center.*

*The global standard for trustable autonomous AI. Governed, proven, running.*

</div>
