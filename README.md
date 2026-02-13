# 🧬 ADAAD

## Autonomous Device-Anchored Adaptive Development

<p align="center">
  <img src="docs/assets/adaad-banner.svg" width="850" alt="ADAAD Governed Autonomy Engine banner">
</p>

<p align="center">
<b>Deterministic Orchestrator • Constitutional Mutation • Cryovant Trust • Aponi Observability</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Governance-Fail--Closed-critical">
  <img src="https://img.shields.io/badge/Replay-Strict%20Mode-blue">
  <img src="https://img.shields.io/badge/Ledger-Hash--Linked-success">
  <img src="https://img.shields.io/badge/Mutation-Constitutional-orange">
  <img src="https://img.shields.io/badge/Lineage-Append--Only-informational">
</p>

---

## 🚀 Overview

**ADAAD** is a governed, lineage-anchored autonomous development environment built to ensure that code mutation and evolution are:

- **Deterministic**
- **Auditable**
- **Tamper-evident**
- **Constitutionally bounded**

Mutations only execute when all trust and governance criteria are met. ADAAD evolves under law, not impulse.

---

## 🧠 Core Guarantees

| Property          | Enforcement Mechanism                         |
| ----------------- | --------------------------------------------- |
| **Determinism**   | Ordered boot spine + replay strict fail-close |
| **Governance**    | Constitutional mutation tiering + evaluation  |
| **Trust**         | Cryovant environment + certification checks   |
| **Lineage**       | Append-only event + hash-linked journal       |
| **Isolation**     | Fail-closed gates at boot + mutation boundary |
| **Observability** | Aponi dashboard + runtime metrics             |

---

## 🏗 Architecture

### Execution Spine

```text
┌──────────────────────────────┐
│ Gatekeeper Preflight         │
├──────────────────────────────┤
│ Runtime Invariants (Fail)    │
├──────────────────────────────┤
│ Cryovant Trust Validation    │
├──────────────────────────────┤
│ Architect / Dream / Beast    │
├──────────────────────────────┤
│ Replay Verification          │
├──────────────────────────────┤
│ Governance Gate              │
├──────────────────────────────┤
│ Mutation Cycle (Optional)    │
├──────────────────────────────┤
│ Capability Registration      │
├──────────────────────────────┤
│ Aponi Dashboard              │
├──────────────────────────────┤
│ Ledger Ready Event           │
└──────────────────────────────┘
```

<p align="center">
  <img src="docs/assets/adaad-governance-flow.svg" width="960" alt="ADAAD He65 execution spine and ledger evidence flow infographic">
</p>

---

### 🛡 Trust Layer vs Policy Layer

| Layer                           | Responsibility                                            |
| ------------------------------- | --------------------------------------------------------- |
| **Trust Layer (Cryovant)**      | Environment validation, certification, ancestry integrity |
| **Policy Layer (Constitution)** | Tier determination, mutation pass/reject                  |

Both layers are required to authorize any mutation.

---

### 🚧 Fail Boundaries

ADAAD enforces fail-closed behavior on:

* Invariant violations
* Cryovant validation failure
* Agent certification failure
* Replay strict divergence
* Ledger integrity mismatch
* Constitutional mutation rejection

---

## 🔄 Mutation Pipeline

Mutation executes only if all governance conditions pass:

* `mutation_enabled=True`
* Replay strict passes
* Cryovant gate passes
* Architect produces proposals
* MutationEngine selects candidate
* Constitutional evaluation passes

### Decision Path

```text
Dream Enabled?
   ├─ No → Safe Boot
   └─ Yes
        ↓
Replay Strict Pass?
        ↓
Cryovant Trust Pass?
        ↓
Architect Proposals?
        ↓
Constitutional Pass?
        ↓
Dry Run / Execute
```

### Outcomes

| Outcome            | Action                                                 |
| ------------------ | ------------------------------------------------------ |
| Rejected           | Emit telemetry + append rejection event                |
| Approved + Dry-Run | Simulate + append `mutation_dry_run`                   |
| Approved + Execute | Apply via `MutationExecutor` + append `mutation_cycle` |

---

## 🔐 Ledger Integrity Model

ADAAD maintains two governance artifacts:

```text
security/ledger/lineage.jsonl
security/ledger/cryovant_journal.jsonl
```

### Cryovant Journal Structure

Each record contains:

* `prev_hash`
* `hash` (SHA-256 over canonicalized record material)
* `tx`, `ts`, `type`, `payload`

### Integrity Enforcement

* JSON parse validation
* `prev_hash` continuity verification
* Hash recomputation consistency
* Integrity mismatch blocks governance gate

---

## 🔁 Replay & Determinism

```bash
python -m app.main --replay off
python -m app.main --replay full
python -m app.main --replay strict
python -m app.main --replay-epoch <epoch_id>
```

| Mode     | Behavior                 |
| -------- | ------------------------ |
| `off`    | No replay check          |
| `full`   | Verification signal only |
| `strict` | Fail-close on divergence |

Replay outcomes are journaled (`replay_verified`).

### Determinism Scope

Determinism is enforced at control-flow and governance boundaries.
Outcome reproducibility depends on replayable scoring inputs,
fitness behavior, and runtime state discipline.

---

## 🏛 Governance Surfaces

| Surface          | Fail Behavior    | Evidence           |
| ---------------- | ---------------- | ------------------ |
| Invariants       | Boot stop        | Metrics + journal  |
| Cryovant         | Boot stop        | Metrics + journal  |
| Constitution     | Mutation reject  | Rejection journal  |
| Replay Strict    | Boot stop        | `replay_verified`  |
| Ledger Integrity | Governance block | Journal continuity |

---

## 🖥 Aponi Observability

Default host: `http://localhost:8080`

Endpoints:

* `/state`
* `/metrics`
* `/fitness`
* `/capabilities`
* `/lineage`
* `/mutations`
* `/staging`

Telemetry surfaces through runtime metrics and ledger/journal records. A canonical `ILogger` is recommended.

---

## 🧩 He65 Elemental Model

| Element  | Directory                                                                 | Responsibility                |
| -------- | ------------------------------------------------------------------------- | ----------------------------- |
| 🌳 Wood  | `app/`                                                                    | Architect + orchestration     |
| 🔥 Fire  | `app/dream_mode.py`, `app/beast_mode_loop.py`, `app/mutation_executor.py` | Mutation flow                 |
| 🌍 Earth | `runtime/`                                                                | Invariants + capability graph |
| 🌊 Water | `security/`                                                               | Cryovant + ledger             |
| ⚙ Metal  | `ui/`                                                                     | Aponi dashboard               |

---

## ⚙ Quickstart

```bash
git clone https://github.com/InnovativeAI-adaad/ADAAD
cd ADAAD
pip install -r requirements.txt
python -m app.main
```

---

## 🛑 Safe Boot Mode

If Dream discovers no tasks:

* `safe_boot=True`
* mutation disabled
* telemetry + dashboard remain active

---

## 🧪 CI Enforcement (Recommended)

Minimum governance parity:

```bash
python -m pytest
python -m app.main --replay strict
```

Also enforce:

* Invariant validation
* Cryovant certification checks

---

## 📜 Rules of Engagement

* Do not modify ledger files manually
* Do not bypass constitutional evaluation
* Do not introduce nondeterministic mutation without governance review
* Governance-impacting behavior must remain auditable

---

## 🛣 Roadmap

* Deterministic mutation entropy discipline (seed control)
* Multi-agent Dream parallelization
* Hardware-backed Cryovant signing
* Replay visualization in Aponi
* Distributed ADAAD topology

---

## 🧬 Conceptual Model

ADAAD is a bounded autonomous software organism:

| Role       | Component                  |
| ---------- | -------------------------- |
| Cognition  | Architect + MutationEngine |
| Law        | Constitution + Cryovant    |
| Metabolism | Fitness scoring            |
| Memory     | Append-only ledger         |
| Eyes       | Aponi dashboard            |
| Body       | He65 repository            |

**It evolves under law, not impulse.**
