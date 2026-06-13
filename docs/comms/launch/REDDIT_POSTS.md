# Reddit Launch Posts

---

## r/programming

**Title:**
> I built an proprietary system where AI agents compete to improve your codebase — but nothing ships without passing a 16-rule constitutional gate

**Body:**

Been building ADAAD for the past several months. The core idea: AI agents propose code improvements, they compete in a genetic algorithm population, and the survivors face a strict policy gate before anything changes. One rule fails, everything stops.

The part I keep coming back to: the GovernanceGate is architecturally the only thing that can approve a mutation. Not a config flag. Not an agent decision. It's the single approval surface, and the rest of the system is literally structured around it.

**What it does technically:**
- Three Claude-powered agents (Architect/Dream/Beast) propose mutations independently each epoch
- Proposals scored using BLX-alpha genetic algorithm, UCB1 bandit agent selection
- Survivors face a versioned constitutional rule set: AST validity, no banned tokens, cryptographic signature required, resource bounds, lineage continuity, etc.
- Every decision written to a SHA-256 hash-chained evidence ledger — tamper-evident, append-only
- Deterministic replay: any governance decision can be re-run later and produces byte-identical results. Divergence halts the pipeline.
- Phase 6 (active): the system can propose amendments to its own roadmap. Still requires human sign-off. Still goes through the same gate.

**What I'm not claiming:**
- It doesn't replace engineers
- It doesn't guarantee correct code
- It doesn't operate without human oversight — production deployments always need explicit human approval

Governed proprietary access. Android app available at zero cost. Curious what people think about the determinism-first design and the constitutional model.

GitHub: https://github.com/InnovativeAI-adaad/ADAAD

---

## r/MachineLearning

**Title:**
> ADAAD: constitutional gating for autonomous code evolution — deterministic replay, 16-rule policy engine, SHA-256 evidence ledger [Project]

**Body:**

Sharing a project that takes a governance-first approach to autonomous software evolution.

**The architecture problem it's solving:**
Most AI code assistants are reactive — human asks, AI suggests, human decides. ADAAD is designed for unattended/semi-attended operation, which means the governance constraints have to be architectural, not advisory.

**Key design decisions:**

*Determinism as a first principle:* Every governance decision is produced from a deterministic function of its inputs. Time, randomness, and external providers are all controlled. This means any decision can be replayed later and will produce byte-identical results. Replay divergence causes an immediate halt — it's not an error you log and move on from.

*Single approval authority:* `GovernanceGate` is the only code path that sets `approved=True` on a mutation. This is enforced by architecture and tested by 22k+ lines of acceptance criteria. The agent personas, bandit selector, genetic population — none of them have approval authority.

*Constitutional versioning:* The rule set is versioned. The constitution can evolve, but only through a human-approved mutation that goes through the same gate as code changes.

*Phase 6 (current):* The system now proposes changes to its own development roadmap. `authority_level = "governor-review"` is hardcoded and injection-blocked. No auto-merge path exists.

**Fitness function:**
`score = base_score - (risk_penalty × risk_score) - (complexity_penalty × complexity_score) + lineage_bonus`

Weights adapt via momentum gradient descent across epochs. Risk/complexity penalties bounded `[0.05, 0.70]` by constitution. UCB1 bandit allocates exploration budget across agent strategies; Thompson sampling activates when non-stationarity is detected (≥30 epochs).

Interested in discussion on the tradeoffs of determinism-first vs. probabilistic approaches for this class of system.

Repo + constitution: https://github.com/InnovativeAI-adaad/ADAAD

---

## r/androiddev

**Title:**
> Free Android app to monitor and control an AI code-evolution pipeline — APK on GitHub, no Play Store needed

**Body:**

Built an Android dashboard for ADAAD (an AI-assisted code improvement system) and wanted to share it since getting something genuinely useful on Android without Play Store fees is still rarer than it should be.

**The app:**
- Full mutation pipeline dashboard — epoch results, agent scores, governance decisions
- Real-time evidence ledger viewer
- Constitutional gate status
- Works offline for read-only views

**Install options (all free):**
- Direct APK from GitHub Releases — tap, install, done
- Obtainium — paste the GitHub URL, auto-updates from there
- Self-hosted F-Droid repo — reproducible builds
- PWA — add to home screen from Chrome, no install at all

No Play Store account. No fee. Android 8.0+.

The governance invariant for distribution: every APK is built by CI, passes a constitutional lint + Android lint gate before signing, and ships with a SHA-256 integrity hash. Nothing distributed that hasn't cleared the gate.

APK + install instructions: https://github.com/InnovativeAI-adaad/ADAAD/blob/main/INSTALL_ANDROID.md

---

## r/devops

**Title:**
> How do you audit AI-generated code changes at scale? We built a hash-chained evidence ledger with deterministic replay

**Body:**

Working on ADAAD and kept hitting the same question: when AI generates code changes continuously, how do you maintain a meaningful audit trail?

Git history tells you *what* changed. We needed a system that records *why* — the score, the competing proposals, the policy verdicts, the agent that proposed it, the epoch context — and that stays credible over time.

What we landed on:

**Hash-chained evidence ledger.** Every governed action produces an entry. Each entry contains a SHA-256 fingerprint of the previous entry. Alter or delete any past record → the chain breaks → the system knows immediately. Append-only by design, not by convention.

**Deterministic replay.** Any governance decision can be re-run from its logged inputs and produces byte-identical results. This means "what would the gate have decided if we ran it again today?" has a provable answer. If it diverges, that's a finding, not a footnote.

**Release evidence matrix.** Before any version ships, a claims-to-evidence matrix must be complete — every public claim maps to a specific, in-repo artifact. Release is blocked until all rows are `Complete`.

For teams running CI/CD at scale with AI-generated changes, curious what audit approaches others are using and whether the replay-first model resonates.

Repo: https://github.com/InnovativeAI-adaad/ADAAD
Evidence model: https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md

---

## r/LocalLLaMA

**Title:**
> ADAAD: proprietary framework for governed autonomous code evolution — the governance layer is the interesting part

**Body:**

Most "AI coding" tools are prompt-and-suggest. ADAAD is different: it runs a continuous loop where AI agents compete to improve a codebase, and the winners face a constitutional policy gate before any change lands.

The governance layer is what I think is most interesting from an LLM-systems perspective:

**The agents get constrained inputs.** Each agent persona (Architect/Dream/Beast) receives a structured `CodebaseContext` — file summaries, recent failures, epoch ID. The epoch ID is the entropy seed, so proposals are deterministically reproducible from context alone.

**The gate doesn't use LLM judgment.** The constitutional rules are versioned deterministic functions: AST validity check, banned token scan, cryptographic signature verification, resource bounds, lineage hash check, etc. No LLM is asked "is this safe?" — the rules either pass or fail computationally.

**Scoring uses semantic AST diff.** Phase 4 replaced regex heuristics with `SemanticDiffEngine` — AST-based risk scoring: `risk = (ast_depth_delta × 0.3) + (cyclomatic_delta × 0.4) + (import_surface_delta × 0.3)`. Identical AST inputs → identical scores.

**The loop improves itself.** Scoring weights adapt via momentum gradient descent. UCB1 bandit allocates exploration budget. The system can now propose amendments to its own development roadmap (Phase 6) — still human-approved, still gate-evaluated.

Works with Claude API. Architecture is provider-agnostic for proposals (the gate is entirely local).

https://github.com/InnovativeAI-adaad/ADAAD
