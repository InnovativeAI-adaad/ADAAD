# ADAAD

> **Deterministic, policy-governed autonomous code evolution.**

ADAAD is a governance-first mutation engine designed to make autonomous code changes auditable, reproducible, and policy-bound.

<p align="center">
  <img src="docs/assets/adaad-banner.svg" width="850" alt="ADAAD governed autonomy banner">
</p>

<p align="center">
  <a href="QUICKSTART.md"><img alt="Quick Start" src="https://img.shields.io/badge/Quick_Start-5%20Minutes-success"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
  <img alt="Governance" src="https://img.shields.io/badge/Governance-Fail--Closed-critical">
  <img alt="Last Commit" src="https://img.shields.io/github/last-commit/InnovativeAI-adaad/ADAAD">
</p>

<p align="center">
  <a href="QUICKSTART.md"><strong>Get Started →</strong></a> ·
  <a href="docs/manifest.txt"><strong>Documentation</strong></a> ·
  <a href="examples/single-agent-loop/README.md"><strong>Examples</strong></a> ·
  <a href="https://github.com/InnovativeAI-adaad/ADAAD/issues"><strong>Issues</strong></a>
</p>

## See ADAAD in action

Prefer learning by example? Start with the minimal walkthrough: [Single-Agent Loop Example](examples/single-agent-loop/README.md).

## What is ADAAD?

ADAAD is an autonomous software development system that proposes and executes code changes under constitutional governance.

In plain terms: ADAAD automates code evolution with strict trust, replay, and policy gates so autonomy stays auditable and controlled.

Replay verification ensures governance decisions produce identical outcomes across runs. If replay diverges from the recorded baseline, mutation halts before execution (fail-closed).

ADAAD governs mutation execution and policy enforcement; it does not generate model intelligence itself.

### Start with one concrete story

Given a repository with duplicated parsing helpers, ADAAD can:

1. Discover a low-risk refactor candidate.
2. Simulate the mutation in governed mode.
3. Attach replay and lineage evidence.
4. Block or stage the change based on policy.

Result: teams get a concrete proposed improvement with deterministic governance evidence, not an opaque autonomous rewrite.

Example dry-run output (illustrative):

```text
[DREAM] Candidate: consolidate duplicated parsing helper
[GOVERNANCE] Tier: low-risk refactor | constitution: PASS
[MUTATION] Would move helper into shared module (dry-run)
[REPLAY] divergence=none | deterministic=true
[RESULT] Staged for review (no files modified)
```

### Who ADAAD is for

- **Engineering teams with strict code standards:** reduce review bottlenecks while preserving auditable policy controls.
- **Maintainers handling repetitive refactors:** automate low-risk cleanup with replayable outcomes.
- **Governance and platform operators:** define policy once and enforce deterministic mutation gates consistently.

## What ADAAD is not

- Not a general-purpose LLM coding assistant
- Not an unattended production auto-merge system
- Not a CI/CD replacement
- Not a self-improving model training framework

## Why teams adopt ADAAD

- **Recurring refactor churn in large codebases:** automate low-risk, policy-bounded mutation proposals with deterministic replay evidence.
- **Regulated or audit-heavy environments:** maintain mutation traceability through governance events, lineage, and fail-closed replay controls.
- **High-trust repositories where silent drift is unacceptable:** enforce reproducible decisions and halt on replay divergence before mutation execution.

## Project Status

| Aspect | Status |
|---|---|
| Recommended for | Governed audit workflows, replay verification, staged mutation review |
| Not ready for | Unattended production autonomy |
| Maturity | Experimental / pre-1.0 |
| Recommended environment | Linux / WSL |
| Replay strict | Production-ready |
| Mutation execution | Staging-only |

Mutation execution is limited to controlled environments. Production use should run in dry-run or strict replay modes unless explicitly authorized by policy.

**Practical readiness summary:** ADAAD is currently safe for governed audit/replay workflows and staged mutation review. It is not positioned yet for unattended production autonomy.

### Validated guarantees vs roadmap

- **Validated guarantees (current branch):** deterministic governance primitives, fail-closed replay enforcement, append-only ledger lineage checks, and staged mutation execution under policy gates.
- **Roadmap items (not validated as production guarantees):** deep sandbox isolation hardening beyond current checks, cryptographic replay proof bundles for third-party verification, and federation-level governance orchestration.

## Why ADAAD?

Traditional autonomous systems typically fail in three places:

- **Runaway mutations:** autonomous edits exceed policy boundaries.
- **Weak auditability:** teams cannot explain exactly what changed and why.
- **Non-reproducible decisions:** governance results drift between runs.

ADAAD addresses this with constitutional mutation controls, append-only lineage journals, and replay verification.

| Traditional automation | ADAAD |
|---|---|
| Pipeline-centric | Governance-first autonomy |
| Manual policy checks | Constitution-enforced approvals |
| Limited mutation history | Full lineage + journal trail |
| Risk of silent drift | Replay verification + fail-closed controls |

## Quick start

Use [QUICKSTART.md](QUICKSTART.md) for the full setup, validation, and reset workflow.

If you are running in a lightweight or constrained environment, see the install fallback in [QUICKSTART.md](QUICKSTART.md#lightweight--constrained-environments). ADAAD currently targets a full Python runtime (Linux/WSL recommended).

### 2-minute quick win (first meaningful result)

After setup, run:

```bash
./quickstart.sh
```

Illustrative output:

```text
🚀 ADAAD Quick Start
[1/4] validate governance schemas
governance_schema_validation:ok
[2/4] run fast confidence tests
...
[3/4] run deterministic simulation runner sample
[4/4] verify federation/founders-law imports
✅ Quick start checks complete
```

If founders-law compatibility module is unavailable in your checkout, quickstart logs a warning and skips federation compatibility tests until the module is merged.

Then run a dry-run mutation pass:

```bash
python -m app.main --dry-run --replay audit --verbose
```

What you should get:

- A deterministic replay decision (`audit`) and boot-stage diagnostics.
- Mutation cycle status with governance gate outcomes.
- No file mutations written (`--dry-run`), so you can safely inspect behavior first.

```bash
git clone https://github.com/InnovativeAI-adaad/ADAAD.git
cd ADAAD
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.server.txt
python nexus_setup.py
python -m app.main --replay audit --verbose
```

## Expected Boot Output (Replay Audit)

You should see boot-stage diagnostics including:

- Governance spine initialization
- Replay baseline comparison
- Cryovant validation result
- Capability registration summary
- Mutation cycle status (enabled / disabled)

## Architecture at a glance

ADAAD is organized into three runtime layers:

1. **Trust Layer (Cryovant):** validates environment trust and ancestry signals.
2. **Governance Layer (Constitution):** evaluates whether a mutation can proceed.
3. **Execution Layer (Dream / Beast / Architect):** discovers, scores, and runs approved work.

Text fallback:

```text
app.main
 ├── Orchestrator
 │    ├── Invariants
 │    ├── Cryovant
 │    ├── Replay
 │    ├── MutationEngine
 │    └── GovernanceGate
 └── Aponi Dashboard
```

<p align="center">
  <img src="docs/assets/architecture-simple.svg" width="760" alt="ADAAD simplified architecture diagram">
</p>

<p align="center">
  <img src="docs/assets/adaad-governance-flow.svg" width="960" alt="ADAAD governance flow">
</p>


## Governance surfaces

| Surface | Fail behavior | Evidence |
|---|---|---|
| Invariants | Boot halt | Metrics + journal |
| Cryovant | Boot halt | Journal entry |
| Replay strict | Boot halt | `replay_verified` event |
| Constitution | Mutation reject | Rejection event |
| Ledger integrity | Governance stop | Hash continuity checks |
| Command queue | Intent reject | Queue hash + rejection event |

The Aponi dashboard now also exposes a strict-gated command-intent queue (`/control/queue`) for governance-aligned `create_agent` and `run_task` requests, plus governed skill profile discovery (`/control/skill-profiles`) and normalized compatibility matrix projection (`/control/capability-matrix`), policy envelope summaries (`/control/policy-summary`), and deterministic intent templates (`/control/templates`), environment diagnostics (`/control/environment-health`), and queue continuity verification (`/control/queue/verify`). This surface validates policy profile, skill profile, knowledge-domain and ability membership, plus capability-source allowlists, then records intents for downstream governed processing; queue continuity verification also detects malformed queue records. It does not execute mutations directly. The default dashboard UI includes a draggable floating observation and command-initiator panel for operators, while preserving the same strict gating and queue-only behavior.

## Replay epochs

Replay epochs represent deterministic governance snapshots. Each epoch includes:

- Baseline digest
- Ledger state hash
- Mutation graph fingerprint
- Constitution version

Strict replay requires identical epoch reconstruction.

Example strict replay failure:

```text
[REPLAY] mode=strict baseline=epoch_2026_02_14
[REPLAY] divergence=hash_mismatch
[RESULT] Boot halted (fail-closed)
```


## Canonical governance import paths

Use `runtime.*` as the authoritative implementation path for governance and replay primitives:

- Foundation utilities: `runtime.governance.foundation.{canonical,hashing,clock}`
- Evolution scoring/state machine/checkpoint: `runtime.evolution.{scoring,promotion_state_machine,checkpoint}`
- Replay/governor integrations import only from `runtime.governance.*` and `runtime.evolution.*`
- Runtime deterministic provider abstraction: `runtime.governance.foundation.determinism`

A compatibility package `governance.*` exists only as a thin adapter that re-exports `runtime.governance.*` for external callers. New internal code should not add alternate implementation trees.

## Determinism Scope

ADAAD guarantees deterministic governance decisions given identical:

- Replay baseline
- Mutation inputs
- Fitness scoring configuration
- Trust mode

External nondeterminism (network, time, entropy) must be sandboxed.

## Sovereignty requirements matrix (implemented vs planned)

| Requirement | Current state | Status | Notes |
|---|---|---|---|
| Deterministic substrate | Canonical deterministic foundation (`runtime.governance.foundation.*`) with replay-seed propagation and determinism tests | Implemented | Treated as a validated guarantee for governance/replay paths |
| Sandbox hardening depth | Policy validation + syscall/fs/network/resource enforcement + evidence hashing | Partially implemented | Additional hardening depth remains roadmap (defense-in-depth and broader isolation coverage) |
| Replay proofs | Deterministic replay verification and parity harnesses in-tree | Partially implemented | Cryptographic/exportable replay proof bundles are roadmap |
| Federation | No cross-instance sovereignty federation runtime committed in this branch | Planned | Reserved for PR-6 scope |

## Mutation risk levels

- **Low:** refactor, logging, non-functional changes.
- **Medium:** algorithmic modifications.
- **High:** security, ledger, or governance logic.

High-risk mutations require explicit policy elevation.

## Fail-close example

Example: replay strict divergence.

```text
Expected digest: abc123
Actual digest:   def456
Result: Boot halted before mutation stage.
```

## Real-world use cases

### 1) Governed autonomous refactor
```text
[DREAM] Candidate: simplify duplicated parsing logic
[GOVERNANCE] Tier: low, constitution: pass
[MUTATION] Applied with lineage + replay evidence
```

### 2) Staging-only replay-audited mutation
```text
[REPLAY] mode=audit baseline=epoch_2026_02_14
[REPLAY] divergence=none
[MUTATION] staged for review (dry-run)
```

### 3) Policy-constrained self-improvement
```text
[ARCHITECT] Proposal affects governance path
[CONSTITUTION] Escalate to high-risk controls
[RESULT] blocked pending explicit policy elevation
```

## Aponi dashboard user entry

Aponi exposes a standard user interface at `http://<host>:<port>/` (or `/index.html`) as a read-only governance nerve center.
The UI now highlights intelligence and risk surfaces backed by deterministic APIs:

- **Operational snapshot:** current governance health, replay state, and mutation posture.
- **Risk visibility:** instability indicators, risk summary buckets, and drift-class weighting.
- **Policy simulation:** non-mutating policy outcome previews before applying governance changes.
- **Replay forensics:** divergence and diff endpoints for deterministic incident review.

For an operator, the dashboard should be read as: *"what is the system doing, what risk is rising, and what is blocked by policy right now?"*

### What to look for first

- **Governance health:** healthy signals indicate replay/trust checks are stable; red flags indicate divergence or gate failures.
- **Risk trending:** rising instability velocity suggests mutation outcomes are becoming less stable and should be reviewed.
- **Blocked mutations:** policy rejections provide actionable reasons before any mutation is applied.

Endpoint surface:

- `/system/intelligence`
- `/risk/summary`
- `/risk/instability`
- `/policy/simulate`
- `/alerts/evaluate`
- `/evolution/timeline`
- `/replay/divergence`
- `/replay/diff?epoch_id=...` (includes deterministic `semantic_drift` class counts and per-key assignments)

The existing machine-facing JSON endpoints (`/state`, `/metrics`, `/fitness`, etc.) are preserved for integrations.
For safety-critical stability, Aponi V2 is being delivered incrementally inside the current server before any command surface is introduced.
Aponi intelligence responses include a versioned governance health model for deterministic interpretation.
Thresholds and model metadata are loaded from `governance/governance_policy_v1.json`, and `/system/intelligence` includes a `policy_fingerprint` hash for auditability.
`/risk/instability` exposes a deterministic weighted instability index over replay failure rate, escalation frequency, determinism drift, and **drift-class-weighted** semantic drift density (with `governance_drift` weighted above `config_drift`), plus additive momentum signals (`instability_velocity`, `instability_acceleration`), confidence interval modeling, and velocity-spike anomaly flags on absolute velocity deltas.
`/policy/simulate` provides read-only policy outcome simulation against candidate governance policy artifacts without mutating live governance state.
`/alerts/evaluate` provides deterministic severity-bucketed governance alerts (critical/warning/info) derived from instability and replay indicators.

## Enhanced user experience

ADAAD includes optional UX helpers for transparency and onboarding:

- Interactive onboarding: `python tools/interactive_onboarding.py`
- Enhanced CLI wrapper: `python tools/enhanced_cli.py --replay audit --verbose` (real-time stage parsing from orchestrator output)
- Enhanced dashboard (static): serve `ui/enhanced/enhanced_dashboard.html`
- Error dictionary helper: `python tools/error_dictionary.py` (includes optional automatic exception hook for operator tools)

These features are observer/operator tools and do not change governance mutation authority.

## Documentation map by persona

- **I want to run ADAAD quickly:** [QUICKSTART.md](QUICKSTART.md)
- **I want to understand governance guarantees:** [docs/CONSTITUTION.md](docs/CONSTITUTION.md)
- **I want mutation lifecycle details:** [docs/governance/mutation_lifecycle.md](docs/governance/mutation_lifecycle.md)
- **I want dashboard/runbook operations:** [docs/governance/APONI_ALERT_RUNBOOK.md](docs/governance/APONI_ALERT_RUNBOOK.md)

## FAQ

### Is ADAAD a replacement for code review?
No. ADAAD automates governed mutation workflows and produces auditable artifacts; teams can still require human review where needed.

### Why does ADAAD exit immediately?
If replay mode is off, Dream mode has no discovered tasks, and no staged mutations exist, ADAAD may boot and exit cleanly.

Use diagnostics:

```bash
python -m app.main --replay audit --verbose
```

### Does ADAAD run unsafe mutations automatically?
No. Mutations must pass trust checks, replay checks, and constitutional policy gates before execution.

### Can I run ADAAD without strict replay?
Yes. Use `--replay off` or `--replay audit` in development, then `--replay strict` for high-assurance environments.

### Is dry-run supported?
Yes. Use `--dry-run` to evaluate mutation candidates and governance outcomes without applying file changes.

## Security

Security disclosures: see [docs/SECURITY.md](docs/SECURITY.md). Do not open public issues for vulnerabilities.

## Getting help

- 📖 Docs: [docs/manifest.txt](docs/manifest.txt)
- 🧪 Example loop: [examples/single-agent-loop/README.md](examples/single-agent-loop/README.md)
- 🐛 Issues: [GitHub Issues](https://github.com/InnovativeAI-adaad/ADAAD/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/InnovativeAI-adaad/ADAAD/discussions)

## Community and contribution

- Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## License

Apache 2.0. See [LICENSE](LICENSE).
