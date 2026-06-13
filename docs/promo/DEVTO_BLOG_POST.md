---
title: "We built an AI that improves code — but can't approve its own changes"
published: true
description: "ADAAD is an proprietary autonomous mutation engine where three AI agents compete to improve your codebase, gated by a constitutional policy engine that the AI itself cannot override."
tags: opensource, ai, devtools, governance
cover_image: https://raw.githubusercontent.com/InnovativeAI-adaad/ADAAD/main/docs/assets/adaad-banner.svg
canonical_url: https://github.com/InnovativeAI-adaad/ADAAD
---

# We built an AI that improves code — but can't approve its own changes

There's a version of "autonomous AI coding" that sounds incredible and a version that sounds reckless. The difference is one word: governance.

ADAAD is our answer to the question: *what does AI code improvement look like when accountability is the constraint, not an afterthought?*

## The problem with most AI dev tools

If you're on a team where "who changed this, when, and why — with proof" is a real question, most AI coding assistants leave you with a gap. They're excellent at generating suggestions. They're terrible at producing verifiable rationale.

ADAAD tries to close that gap.

## What ADAAD does

ADAAD is an proprietary autonomous mutation engine. Every epoch, three Claude-powered AI agents (we call them Architect, Dream, and Beast) independently propose code improvements. They don't coordinate — they compete.

Those proposals then go through a genetic algorithm population: cross-bred, mutated, ranked. The best candidates advance to the **GovernanceGate**: a 16-rule constitutional policy engine that evaluates each proposal deterministically. One blocking failure? The entire proposal is rejected. Nothing proceeds.

Every approved change is SHA-256 hash-chained into an append-only evidence ledger. Every decision is **deterministically replayable** — given the same inputs, you get byte-identical output. If a replay ever diverges from the original, the pipeline halts automatically and alerts.

## The constitutional gate

This is the part I'm most proud of.

The `GovernanceGate` is the **only** surface in ADAAD that can approve a mutation. Not the AI agents. Not environment variables. Not a clever automated workaround. This is architecturally enforced — not just documented in a README.

The constitution is a real document with binding rules at three severity levels:

- **BLOCKING**: violation = full rejection, no exceptions
- **WARNING**: proposal proceeds, violation is flagged for human review
- **ADVISORY**: informational, goes into the audit record

Rules cover: AST validity, banned tokens (no `eval`, no `exec`), cryptographic signature requirements, lineage continuity, resource bounds, entropy budget, and more.

The constitution itself can evolve — but only through a formal process requiring human sign-off. The AI cannot modify the rules it operates under.

## Deterministic replay: real auditability, not theater

Every governance decision is computed from deterministic inputs. We seed randomness from the epoch ID. We don't use system time in governance logic. The result: any past decision can be re-run and produces byte-identical output.

This is mechanically enforced: if replay ever diverges, the pipeline halts immediately. The divergence is logged and must be resolved before anything continues.

"But you can audit our AI decisions" means nothing if you can't actually reproduce them. Replay makes it real.

## Phase 6: the engine proposes changes to its own roadmap

The latest feature is genuinely interesting to think about.

Every N epochs (configurable, default 10), the evolution loop evaluates six prerequisite gates:

1. Epoch health score ≥ 0.80 (rolling last-10 average)
2. Federation divergence count = 0
3. Weight adaptor prediction accuracy > 0.60
4. No pending amendments already in progress
5. Trigger interval ≥ 5 epochs (misconfiguration guard)
6. All six gates pass → proposal emitted

If all six pass, `RoadmapAmendmentEngine.propose()` is called and a governed roadmap amendment is submitted.

A human governor must approve before anything changes. There is no auto-promote path. This is a **constitutional invariant** — `authority_level = "governor-review"`, hardcoded, injection-blocked.

ADAAD proposes. Humans decide.

## Multi-repo federation

Starting in v3.0.0, ADAAD can operate across multiple codebases. A change approved in repo A is **not** automatically approved in repo B. Each repo's GovernanceGate evaluates independently. Source approval never binds the destination. This is the dual-gate invariant.

Cross-repo proposals also require HMAC key validation at boot — absent key material halts the node before any federation operations can run.

## The Android app

The full governance dashboard runs on Android — free, no Play Store account required. Four install tracks:

1. Direct APK from GitHub Releases
2. Obtainium auto-update (paste the repo URL)
3. PWA (Chrome → Add to Home Screen)
4. F-Droid (self-hosted repo, official submission pending)

Every APK is built in CI after passing the governance gate, then signed. SHA-256 hash published alongside every release asset.

## Getting started

```bash
git clone https://github.com/InnovativeAI-adaad/ADAAD.git
cd ADAAD
python onboard.py
```

Requirements: Python 3.11+, pip, git. The `onboard.py` script handles everything: environment setup, workspace initialization, schema validation, and a governed dry-run. About 60 seconds.

You'll need an Anthropic API key to run the AI mutation loop (`ADAAD_CLAUDE_API_KEY`). Everything else works without it.

## Where to dig deeper

- **Plain English overview** (no technical background needed): [docs/ADAAD_PLAIN_ENGLISH_OVERVIEW.md](https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/ADAAD_PLAIN_ENGLISH_OVERVIEW.md)
- **The constitution**: [docs/CONSTITUTION.md](https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md)
- **Architecture contract**: [docs/ARCHITECTURE_CONTRACT.md](https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/ARCHITECTURE_CONTRACT.md)
- **ArchitectAgent spec v3.1.0**: [docs/governance/ARCHITECT_SPEC_v3.1.0.md](https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/governance/ARCHITECT_SPEC_v3.1.0.md)

---

ADAAD is proprietary licensed, free to use, and the whole thing is in the repo. Questions, feedback, and contributions are genuinely welcome.

If you're working in a context where AI code changes need to be auditable, reversible, and justifiable — this was built for you.

GitHub: https://github.com/InnovativeAI-adaad/ADAAD
