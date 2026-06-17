# Reddit Launch Posts

---

## r/programming

**Title:**
I built an autonomous AI mutation engine that can't do anything without permission — every change is constitutional-gated, hash-chained, and deterministically replayable (proprietary)

**Body:**

Been working on this for a while and wanted to share with r/programming because it tackles a problem I see discussed here a lot: how do you actually use AI for code changes without losing auditability?

**What ADAAD does:**

Three Claude-powered AI agents (Architect, Dream, Beast) continuously propose code improvements each epoch. They compete in a genetic algorithm population — scored, cross-bred, ranked. The best proposals face a 16-rule constitutional policy engine. One blocking failure and the entire proposal is rejected. Nothing is applied without passing the gate.

Every decision goes into an append-only SHA-256 hash-chained evidence ledger. Every decision is deterministically replayable — given the same inputs, you get byte-identical output. If a replay ever diverges, the pipeline halts automatically.

**The part I think is most novel:**

`GovernanceGate` is the only surface that can approve a mutation. Not the AI agents, not environment variables, not automated shortcuts. This is architecturally enforced, not just a convention. The constitution is a real document with binding rules that the AI cannot modify.

**Latest: Phase 6**

The engine can now propose amendments to its own development roadmap. It checks 6 prerequisite gates (epoch health score, federation divergence count, weight adaptor accuracy, pending amendment count), and if all pass, proposes a governed roadmap update. Human approval required — there's no auto-promote path, it's a constitutional invariant.

**Governed proprietary access:**
- proprietary license
- Free Android app (APK, Obtainium, PWA, F-Droid)
- `python onboard.py` gets you running in ~60 seconds
- Full architecture spec, constitution, and evidence contract in the repo

GitHub: https://github.com/InnovativeAI-adaad/ADAAD

Happy to answer questions about the governance model, the determinism architecture, or why three competing agents outperform a single one.

---

## r/MachineLearning

**Title:**
[Project] ADAAD: Constitutional governance for autonomous code mutation — three competing AI agents, genetic algorithm population, deterministic replay, SHA-256 evidence ledger

**Body:**

**Short version:**
Open-source system where three Claude-powered AI agents compete to improve a codebase each epoch, governed by a 16-rule constitutional policy engine, with every decision deterministically replayable and hash-chained into an append-only ledger.

**Technical summary:**

**Agent layer:** Three AI personas (Architect/Dream/Beast) independently propose mutations using Claude API. Each approaches improvement from a different strategy angle — no coordination.

**Selection layer:** BLX-alpha genetic algorithm population. Proposals compete, cross-breed (good ideas combine), get ranked by a fitness function. UCB1 bandit selects which agent gets more proposal budget. Thompson sampling activates on detected non-stationarity (Page-Hinkley sequential change detection, ≥30 epochs).

**Governance layer:** `GovernanceGate` evaluates a versioned deterministic rule set per mutation (see Constitution + governance artifact for current count) across three tiers (Sandbox/Stable/Production). Rules cover AST validity, banned tokens, cryptographic signature, lineage continuity, resource bounds, entropy budget, and more. Three severity levels: BLOCKING (reject), WARNING (flag), ADVISORY (log).

**Adaptation layer:** `WeightAdaptor` adjusts scoring weights via momentum gradient descent (LR=0.05). `PenaltyAdaptor` adapts risk/complexity penalties based on post-merge outcome data from the evidence ledger. Weights bounded [0.05, 0.70] by constitutional rule.

**Determinism layer:** Every governance decision is computed from deterministic inputs (no system time, seeded RNG anchored to epoch_id). Replay of any past decision produces byte-identical output. Divergence halts the pipeline.

**Phase 6 addition:** `RoadmapAmendmentEngine` — the evolution loop evaluates 6 prerequisite gates every N epochs and can propose governed amendments to ROADMAP.md itself. Constitutional invariant: `authority_level = "governor-review"`, hardcoded, injection-blocked.

**Open questions I'd genuinely appreciate ML perspectives on:**
1. Is BLX-alpha the right choice for this crossover scenario, or would SBX be better?
2. The UCB1→Thompson transition on non-stationarity detection — is Page-Hinkley the right detector here, or something like ADWIN?
3. Is momentum gradient descent for adaptive scoring weights the right algorithm, or would Adam/RMSprop be better?

GitHub: https://github.com/InnovativeAI-adaad/ADAAD
Architecture spec: https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/governance/ARCHITECT_SPEC_v3.1.0.md

---

## relevant governance and AI safety communities

**Title:**
ADAAD: Free, proprietary AI mutation engine with constitutional governance — runs on Android, proprietary license, no cost

**Body:**

Sharing ADAAD with relevant governance and AI safety communities because it hits all the marks I personally care about in governed software:

✅ **Truly free** — proprietary license, $0 to run, no paid tier, no "freemium governance features"
✅ **Free Android app** — four install tracks (APK, Obtainium, PWA, F-Droid), no Play Store account required
✅ **Transparent governance** — the entire constitutional rulebook is in the repo and versioned
✅ **Auditable** — every decision is SHA-256 hash-chained and deterministically replayable
✅ **No lock-in** — bring your own Anthropic API key, all data stays local

**What it does:**

AI agents continuously propose improvements to your codebase. Every change is gated by a constitutional policy engine before anything is applied. Nothing ships without a complete audit trail.

**Why auditability matters here specifically:**

An AI system that modifies code should itself be fully auditable. Closed-source "AI code improvement" tools ask you to trust a black box. With ADAAD, the governance rules, the scoring algorithms, the ledger format, the replay logic — all of it is in the repo. You can read it, fork it, extend it.

GitHub: https://github.com/InnovativeAI-adaad/ADAAD
Docs: https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/ADAAD_PLAIN_ENGLISH_OVERVIEW.md

---

## r/devops

**Title:**
We built an AI that modifies code with full audit trail — every change cryptographically chained, deterministically replayable, and reversible (proprietary)

**Body:**

DevOps folks — this one's for you, because the thing I kept hearing when I described ADAAD to people was "that's basically what we wish our change management process looked like."

**The core problem:**
AI code generation tools create changes fast. Change management requires knowing *why* a change happened, with evidence, traceable to a specific decision point. Those two things don't go together natively.

**What ADAAD adds:**

Every mutation goes through a governance pipeline that produces a cryptographic evidence bundle. The bundle includes: the original proposal, the scoring rationale, the gate evaluation results (versioned rule set, named, with pass/fail for each), the final decision, and a SHA-256 chain linking it to every prior decision.

You can replay any decision later with byte-identical results. "Why did this change happen on March 6th?" → replay the epoch → get the exact same gate verdicts → verify the evidence bundle.

Fails-closed. Divergence halts. Every approval is explicit and logged.

**Not just documentation:**

The audit trail isn't an afterthought you add with a commit message. It's generated mechanically by the governance pipeline. You can't approve a mutation without the trail being created. There's no way to skip it.

**Open source, proprietary license, free Android app:**
GitHub: https://github.com/InnovativeAI-adaad/ADAAD

---

## r/androiddev

**Title:**
ADAAD — free AI governance dashboard for Android, no Play Store account needed, APK + Obtainium + PWA + F-Droid

**Body:**

Built the Android version of ADAAD's governance dashboard and wanted to share with r/androiddev both as a "here's a free app" and as a "here's how we distribute without the Play Store" write-up.

**The app:**

Full Aponi governance dashboard — monitor the AI mutation pipeline, view epoch telemetry, inspect the evidence ledger, check governance gate results. Runs on Android 8.0+.

**Four distribution tracks, all free:**

1. **Direct APK** — GitHub Releases, tap to install. SHA-256 hash in every release.
2. **Obtainium** — paste `github.com/InnovativeAI-adaad/ADAAD`, get automatic updates
3. **PWA** — Add `innovativeai-adaad.github.io/ADAAD` to home screen in Chrome
4. **F-Droid** — Self-hosted repo + official F-Droid submission in progress

**On the distribution strategy:**

We built this after realizing that requiring a Play Store account to distribute a free tool is a barrier we didn't need to create. The GitHub Releases + Obtainium combo gives you essentially the same UX as an app store (automatic updates, version management) without any account requirement.

The APK is signed in CI (governance gate runs before signing), SHA-256 hash published alongside every release asset. `apksigner verify --print-certs` works.

Install page with QR codes: https://innovativeai-adaad.github.io/ADAAD/install
GitHub: https://github.com/InnovativeAI-adaad/ADAAD

Happy to answer questions about the distribution setup, the CI signing pipeline, or the governance gate that runs before every APK is signed.

---

## Posting schedule recommendation:
- r/programming → Tuesday morning (US Eastern)
- r/MachineLearning → Wednesday (engage technical questions same day)
- relevant governance and AI safety communities → Any weekday
- r/devops → Wednesday or Thursday
- r/androiddev → Weekend (Android community is more active)
