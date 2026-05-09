<div align="center">

![ADAAD Hero Banner](docs/assets/readme/inline-hero_banner.svg)
<br/>

<a href="#what-it-does">⚡ What it does</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="#capabilities">🧠 Capabilities</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/CONSTITUTION.md">📜 Constitution</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="ROADMAP.md">🗺 Roadmap</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="DORK.md">🕵️ DORK</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="TRUST_CENTER.md">🏛 Trust Center</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/VERIFIABLE_CLAIMS.md">✅ Verifiable Claims</a>

<br/>

[![Proprietary](https://img.shields.io/badge/license-Proprietary-ff4466?style=flat-square&labelColor=0d1117)](LICENSE)&nbsp;[![Python 3.12](https://img.shields.io/badge/python-3.12-00ff88?style=flat-square&labelColor=0d1117)](https://python.org)&nbsp;[![v9.110.0](https://img.shields.io/badge/version-v9.110.0-a855f7?style=flat-square&labelColor=0d1117)](CHANGELOG.md)&nbsp;[![410 Invariants](https://img.shields.io/badge/invariants-410%20Hard--class-ff4466?style=flat-square&labelColor=0d1117)](docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md)&nbsp;[![82 Innovations](https://img.shields.io/badge/innovations-82%20shipped-f97316?style=flat-square&labelColor=0d1117)](ROADMAP.md)&nbsp;[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/InnovativeAI-adaad/adaad?style=flat-square&labelColor=0d1117&color=00d4ff&label=Commits%2Fmonth)](https://github.com/InnovativeAI-adaad/adaad/commits/main)

</div>

---

## The only AI system that governs its own evolution — and can prove it.

**Every mutation flows through a 16-step Constitutional Evolution Loop.** **Every decision is sealed in a hash-chained cryptographic proof.** **One human key unlocks critical changes. That is not configurable.**

---

## What ADAAD is

ADAAD is a **constitutionally governed autonomous software evolution engine**. It proposes mutations to its own codebase, scores them against a cryptographically enforced constitution, red-teams them adversarially, and delivers the results to the governing human for ratification—all in a closed, auditable loop.

It is not an agent framework. It is a **governance kernel**. The distinction matters: other systems *log* what AI does. ADAAD *prevents* what it's not allowed to do, then proves it.

---

## What ADAAD can do

### 🧠 Govern its own mutations
ADAAD scores every proposed change across five constitutional fitness axes before a single line executes. Proposals that violate invariants are rejected fail-closed: an exception is raised, and a ledger entry is written.

### 🛡️ Red-team itself adversarially
Before any mutation reaches production, the Adversarial Fitness Red Team (AFRT) agent attempts to break it. The AFRT is structurally prohibited from approving its own challenges.

### 🧬 Verify its own fitness after execution
After execution, the Mutation Fitness Verifier grades the result as `CERTIFIED` or `REGRESSED`. Regressed mutations do not promote.

### ⚖️ Self-Amending Feedback Loop
When a human disposition lands, the **CEL Feedback Integrator (INNOV-82)** translates it directly into selection-weight adjustments. Accepted amendments amplify the corresponding fitness axis; rejected ones decay it. Human judgment becomes constitutional calibration signal.

### 🏛️ Reconstruct any past state deterministically
Every ledger entry is hash-chained. Every decision is replayable to verify the integrity of the system's evolution history.

---

## The closed self-improvement loop

```mermaid
graph TD
    A[MSE: Selection Engine] --> B[MRP: Risk Profiler]
    B --> C[MEX: Execution Sandbox]
    C --> D[MFV: Fitness Verifier]
    D --> E[RDP: Human Delivery]
    E -->|HUMAN-0 Ratification| F[CFI: Feedback Integrator]
    F -->|Weight Calibration| A
