# Hacker News — Show HN

**Title:**
Show HN: ADAAD – AI agents that improve your code, constitutionally gated and replay-verified (proprietary)

**URL:** https://github.com/InnovativeAI-adaad/ADAAD

**Body text:**
(Leave empty — HN rules for Show HN submissions)

---

## Comment to post immediately after submission:

ADAAD (Autonomous Development & Adaptation Architecture) is an proprietary mutation engine that lets three Claude-powered AI agents (we call them Architect, Dream, and Beast) continuously propose code improvements — but every single change is blocked behind a constitutional governance gate before anything is applied.

The problem I was trying to solve: AI code suggestion tools are great at volume, terrible at accountability. If you're on a team where "who changed this and why" is a real question, or in an industry where you need an audit trail, raw AI code generation is a liability. ADAAD threads the needle.

**How the loop works:**
1. Three agents independently propose mutations each epoch
2. Proposals compete in a BLX-alpha genetic algorithm population
3. Winners face a versioned deterministic constitutional rule set — one blocking failure halts everything
4. Approved changes are SHA-256 hash-chained into an append-only evidence ledger
5. Scoring weights self-calibrate via momentum gradient descent across epochs

**The part I'm most proud of — deterministic replay.** Every governance decision can be re-run later with byte-identical results. If a replay ever diverges from the original, the pipeline halts and raises an alert. This isn't aspirational auditability, it's enforced mechanically.

**What's shipping now (v3.1.0-dev):**
- Phase 6: the engine can now propose amendments to its own roadmap. It evaluates its own telemetry, checks 6 prerequisite gates, and if conditions are met, proposes a governed roadmap update. Human approval required before anything changes — there's no auto-promote path, written as a constitutional invariant.
- Multi-repo federation (v3.0.0): cross-repo mutations with dual-gate enforcement. Source approval never binds destination repos.
- Free Android app — direct APK, Obtainium auto-update, PWA, and F-Droid tracks. No Play Store account required.

**One invariant I want to highlight:**
`GovernanceGate` is the only surface that can approve a mutation. Nothing else — no AI agent, no automated process, no environment variable — has that authority. Architecturally enforced, not just documented.

**Tech stack:** Python 3.11+, Claude API (Anthropic), custom BLX-alpha GA, SHA-256 hash-chained ledger, constitutional rule engine. Android app via standard Android tooling. Zero cost to run.

Would love feedback on the governance model in particular — specifically whether the "fail-closed on replay divergence" approach is the right tradeoff, and whether the three-tier constitutional severity model (blocking / warning / advisory) maps to how people think about code governance in practice.

GitHub: https://github.com/InnovativeAI-adaad/ADAAD
Docs: https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md
Quick start: `git clone https://github.com/InnovativeAI-adaad/ADAAD.git && python onboard.py`

---

## Strategic notes for the submission:

- **Best time to post:** Tuesday–Thursday, 9–11am US Eastern
- **Target subnodes:** Programming, AI, Open Source, DevTools
- **Likely hot threads to engage:** Any active threads on AI coding tools, autonomous agents, AI safety in practice
- **Avoid:** Don't submit same week as a major AI release (GPT-5, Claude 4, etc.) — will get buried
- **Follow-up:** Engage every comment within the first 2 hours. HN rewards genuine technical engagement.
