# Product Hunt Launch

---

## Listing Details

**Name:** ADAAD

**Tagline:**
> AI agents that evolve your codebase — governed by a constitution, never without your approval

**Topics:** Developer Tools · Artificial Intelligence · Open Source · DevOps · Productivity

**Website:** https://github.com/InnovativeAI-adaad/ADAAD

---

## Description

ADAAD runs a continuous improvement loop on your codebase. Three AI agents (Architect, Dream, Beast) independently propose code changes every epoch. Those proposals compete in a genetic-algorithm tournament. The survivors face a 16-rule constitutional gate — and nothing ships unless every rule passes.

**The key idea:** the GovernanceGate is the only thing in the system with approval authority. Not an AI agent. Not a config flag. It's the load-bearing wall, not a feature.

**What makes it different from other AI coding tools:**

🔁 **Deterministic replay** — every governance decision can be re-run and produces byte-identical results. Replay divergence halts the pipeline. This is what makes it auditable, not just fast.

🛡️ **Constitutional gating** — a versioned rule set evaluated per mutation (see Constitution + governance artifact for current count). AST validity, banned token scan, cryptographic signature required, resource bounds, lineage continuity. One failure = full halt.

🧾 **Permanent evidence ledger** — every proposal, score, and decision is SHA-256 hash-chained. Tamper-evident, append-only, replay-verifiable.

📝 **Roadmap self-amendment** — the system can now propose changes to its own development roadmap (Phase 6). It still needs a human governor to approve. It cannot self-promote. Ever.

📲 **Free Android app** — full dashboard, APK on GitHub Releases, Obtainium auto-updates, F-Droid, and PWA. No Play Store. No fee.

**Who it's for:** Teams that want AI to handle continuous improvement work without the liability of unsupervised changes. Organizations that need real audit trails. Developers building safe AI-assisted systems.

**Available under governed proprietary licensing.**

---

## Maker Comment (to post on launch day)

Hey PH 👋

I built ADAAD because I kept running into the same problem: AI coding tools are powerful when a human is watching every suggestion, but become liabilities when running autonomously. The solution isn't less AI — it's a governance layer that's architecturally non-bypassable.

The thing I'm most proud of: `GovernanceGate` is literally the only code path that can approve a mutation. I tested this extensively — 22,000+ lines of acceptance criteria in the test suite. The agents, the scoring, the bandit selector — they all feed into it, but none of them hold approval authority.

A few things I'd love feedback on:

1. **The determinism model** — is replay-identical governance the right bar for AI-assisted systems, or is it overkill?

2. **The constitutional approach** — versioned rules with human-approved amendments vs. ML-based policy learning. We went constitutional. Was that the right call?

3. **Phase 6** — the system now proposes changes to its own roadmap. It still needs a human to approve. Does this feel like the right line, or should the system have less/more autonomy here?

Happy to answer anything. The constitution is worth a read if you're interested in the governance model: [docs/CONSTITUTION.md](https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md)

---

## Gallery / Screenshots captions

1. **Pipeline overview** — "The full mutation lifecycle: three agents propose, genetic algorithm scores, constitutional gate decides"
2. **GovernanceGate verdict** — "Versioned constitutional rule set, evaluated in order. One blocking failure halts everything."
3. **Evidence ledger** — "SHA-256 hash-chained. Every decision, permanently recorded."
4. **Android dashboard** — "Free. No Play Store. Install via APK, Obtainium, F-Droid, or PWA."
5. **Phase 6 roadmap amendment** — "ADAAD proposes. Humans approve. Always."
