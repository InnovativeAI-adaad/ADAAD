# Show HN: ADAAD – AI agents that improve your code, constitutionally gated

**Submission title:**
> Show HN: ADAAD – proprietary AI that evolves your codebase, with a non-bypassable governance layer

**URL:** https://github.com/InnovativeAI-adaad/ADAAD

---

## Post body (text field)

Three AI agents (Architect, Dream, Beast) continuously propose code improvements. Those proposals compete in a genetic-algorithm population, get scored, and the survivors face a 16-rule constitutional gate before anything changes. One blocking failure = full halt. The GovernanceGate is the only thing in the system with approval authority — architecturally, not just by convention.

What I think is technically interesting:

**Deterministic replay.** Every governance decision can be re-run later and produces byte-identical output. If replay diverges from the original, the pipeline halts immediately. This makes the system genuinely auditable rather than theoretically auditable.

**Constitutional tiers.** Three deployment tiers (Sandbox / Stable / Production) with different rule severities per tier. Blocking in Production, warning in Sandbox. The constitution itself is versioned and can evolve — but only through a human-approved mutation.

**Roadmap self-amendment (Phase 6).** The system can now propose changes to its own development roadmap. The proposal goes through the same gate as any code change. Human governor sign-off is required and cannot be delegated. `authority_level = "governor-review"` is hardcoded and injection-blocked.

**Free Android app.** Full dashboard runs on Android, installable from GitHub Releases, F-Droid, or as a PWA. No Play Store account, no fee.

**Multi-repo federation.** Cross-repo mutations require GovernanceGate approval in both source and destination repos independently. Source approval never binds the destination.

Stack: Python 3.11+, Anthropic Claude API, SHA-256 hash-chained evidence ledger, cgroup v2 sandboxes, HMAC-signed mutation transport.

The thing I'm most proud of: the governance layer isn't bolted on. It's the load-bearing wall. You can't ship anything that hasn't passed through it.

Would be curious what people think about the determinism-first approach and whether the constitutional model is the right abstraction for safe AI-assisted development.

Repo: https://github.com/InnovativeAI-adaad/ADAAD
Docs: https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md

---

## Anticipated top comments / prepared responses

**"This is just Cursor/Copilot with extra bureaucracy"**
> The difference is what happens when the AI is wrong. Cursor suggests; you decide. ADAAD is designed for unattended or semi-attended operation where a human isn't watching every suggestion in real time. The governance layer is what makes that possible without it being reckless. The audit trail is what makes it viable in regulated environments.

**"The 'constitutional gate' sounds like security theater"**
> Fair skepticism. The gate is enforced at the architecture layer: `GovernanceGate` is the only code path that can set `approved=True` on a mutation. There's no environment variable, no API endpoint, no agent flag that bypasses it. The tests for this are in `tests/test_mutation_guard.py` — 22k lines of acceptance criteria. The determinism CI job verifies it on every PR.

**"Why not just use git hooks / CI?"**
> CI checks pass/fail a PR. ADAAD generates the PR in the first place, scores it against alternatives, and produces a governed evidence bundle that tells you not just "did this pass" but "why was this chosen over 47 other proposals, what was its fitness score, and what would happen if you replayed the decision tomorrow."

**"Is this actually running in production anywhere?"**
> The loop is running on itself — ADAAD is used to develop ADAAD. v3.0.0 shipped via the governed pipeline. The evidence matrix for each release is in `docs/comms/claims_evidence_matrix.md`.
