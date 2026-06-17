---
title: "We built an AI that improves code continuously — here's the governance layer that makes it safe"
published: true
description: "ADAAD: a constitutional policy engine, deterministic replay, and a hash-chained evidence ledger for governed autonomous code evolution."
tags: ai, devops, opensource, programming
cover_image: https://github.com/InnovativeAI-adaad/ADAAD/raw/main/docs/assets/adaad-banner.svg
---

# We built an AI that improves code continuously — here's the governance layer that makes it safe

The pitch for AI-assisted code improvement is obvious: AI works around the clock, proposes improvements at scale, handles the tedious maintenance work that engineers deprioritize. It's a compelling value proposition.

The problem is equally obvious: unsupervised AI making changes to production code is a liability. AI suggestions can be subtly wrong, introduce security issues, or break things in ways that aren't caught until it's too late.

Most tools solve this by keeping humans in the loop for every suggestion — you review, you decide, you merge. That works but doesn't scale. If a human has to approve every AI suggestion, you're just using a fancier autocomplete.

We took a different approach with [ADAAD](https://github.com/InnovativeAI-adaad/ADAAD). Instead of asking "how do we make AI suggestions safe enough for humans to approve quickly?", we asked: **"what would it take to make autonomous operation safe by construction?"**

## The core design: constitutional gating

ADAAD's mutation pipeline has one and only one approval surface: `GovernanceGate`. It's the only component in the system that can set `approved=True` on a mutation proposal. Everything else — agents, scoring, bandit selection, genetic algorithm — feeds into it, but nothing bypasses it.

This isn't documented policy. It's architectural structure. The rest of the system literally cannot approve mutations; they don't have that code path.

The gate evaluates a versioned deterministic rule set (see Constitution + governance artifact for current count):

```python
# A sample of what the constitutional gate checks
rules = [
    "single_file_scope",        # BLOCKING: reduces complexity
    "ast_validity",             # BLOCKING: no syntax errors
    "no_banned_tokens",         # BLOCKING: no eval/exec
    "signature_required",       # BLOCKING: cryptographic lineage
    "resource_bounds",          # BLOCKING: memory/CPU limits
    "lineage_continuity",       # BLOCKING: traceability chain
    "max_mutation_rate",        # WARNING:  runaway prevention
    "entropy_budget_limit",     # BLOCKING in production
    "federation_dual_gate",     # BLOCKING: cross-repo mutations
    # ... 7 more
]
```

One blocking failure → full halt. No partial approvals. No "mostly passed."

## Deterministic replay: auditability that actually works

Here's the part I'm most interested in from a systems design perspective.

Most systems are auditable in the sense that they log things. ADAAD is auditable in a stronger sense: **any governance decision can be replayed from its logged inputs and will produce byte-identical results.**

This means:
- "Why was this mutation approved in January?" has a provable answer, not just a plausible one
- Compliance audits can verify decisions independently, not just read logs
- If something changes in the underlying system, replaying old decisions will reveal the divergence

The enforcement is strict: if a replay produces different results than the original, the pipeline halts immediately. Divergence isn't a warning you log and investigate later — it's a blocking event.

To make this work, we had to control every source of non-determinism:

```
Controlled inputs:
- Time (frozen at decision time, logged)
- Randomness (seeded deterministically from epoch_id)
- External providers (ADAAD_FORCE_DETERMINISTIC_PROVIDER=1 in audit/strict modes)

What this enables:
- Replay any epoch → identical agent proposals
- Replay any gate evaluation → identical verdict
- Replay any scoring run → identical fitness scores
```

## The evidence ledger

Every governed action produces an entry in the evidence ledger:

```json
{
  "event": "mutation_evaluated",
  "epoch_id": "epoch-042",
  "mutation_id": "mut-7f3a...",
  "agent": "ARCHITECT",
  "fitness_score": 0.73,
  "gate_verdict": "APPROVED",
  "rules_evaluated": 16,
  "blocking_failures": 0,
  "lineage_chain_hash": "sha256:a3f9...",
  "timestamp_frozen": "2026-03-07T14:23:11Z",
  "replay_proof": "sha256:b8d2..."
}
```

Each entry contains the SHA-256 hash of the previous entry. Alter or delete any past record → the chain breaks. The ledger is append-only and the integrity check runs on every CI build.

## How the mutation loop works

```
Epoch N:
  Phase 1: Three agents independently propose mutations
  Phase 2: Proposals seeded into GA population
  Phase 3: BLX-alpha crossover + scoring + ranking
  Phase 4: GovernanceGate evaluates survivors
  Phase 5: Accepted mutations applied; ledger updated

Between epochs:
  WeightAdaptor: momentum gradient descent on scoring weights
  FitnessLandscape: updates win/loss ledger per mutation type
  BanditSelector: UCB1 updates agent selection probabilities
  EpochTelemetry: appends health indicators
```

The scoring formula for fitness:

```
score = base_score
      - (risk_penalty    × risk_score)      # AST-derived
      - (complexity_penalty × complexity_score)  # cyclomatic delta
      + lineage_bonus                        # reward for proven lineage
```

Risk and complexity scores come from `SemanticDiffEngine` — an AST-aware analyzer that computes `ast_depth_delta`, `cyclomatic_delta`, and `import_surface_delta` rather than using regex heuristics.

## Phase 6: the system proposes changes to its own roadmap

This one required careful thought. The capability: ADAAD can now evaluate whether conditions are right (health score ≥ 0.80, prediction accuracy > 0.60, zero federation divergence) and propose an amendment to ROADMAP.md.

The safeguards:
- Same gate. Same versioned constitutional rule set.
- `authority_level = "governor-review"` hardcoded in `RoadmapAmendmentEngine.__init__`. Not configurable.
- Human governor sign-off required. Not delegatable.
- No auto-merge path. Constitutionally prohibited.
- Storm prevention: at most one pending amendment at a time.

The constitutional invariant is called `PHASE6-HUMAN-0`. It lives in `docs/governance/ARCHITECT_SPEC_v3.1.0.md`. The system proposes. Humans decide.

## What we've learned

**The governance layer is the product.** The AI capability is table stakes — Claude can already write decent code improvements. The value is that we can run it unattended without recklessness, and audit everything after the fact.

**Determinism is hard to retrofit.** We had to design for it from the start. Every component that touches governance decisions had to be made deterministic — not just "usually reproducible" but "byte-identical on replay." This eliminates an entire class of AI system bugs.

**Constitutional rules > ML-learned policy.** We could have trained a model to predict which mutations are safe. We didn't. Deterministic rules are auditable, explainable, and stable. A mutation passes or fails for a reason you can read in the rule definition.

---

ADAAD is proprietary and available only under authorized access or written license. The Android dashboard is free (no Play Store needed). The constitution is the best starting point if you want to understand the governance model.

**GitHub:** https://github.com/InnovativeAI-adaad/ADAAD
**Constitution:** https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md

Happy to discuss the determinism model, the constitutional approach, or the Phase 6 roadmap self-amendment design in the comments.
