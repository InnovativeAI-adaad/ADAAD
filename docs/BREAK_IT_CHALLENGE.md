# ADAAD Break-It Challenge

**v9.60.0 · Phase 127 · Launched 2026-04-06**

> *If you can bypass a constitutional invariant and prove it, we want to know — and we'll say so publicly.*

---

## The Challenge

ADAAD enforces **167 Hard-class invariants** at runtime. Violating any one of them aborts the epoch immediately. Every decision is SHA-256 hash-chained, deterministically replayable, and independently verifiable without system access.

We are inviting external researchers, auditors, red-teamers, and adversarial thinkers to attempt to bypass these invariants and submit evidence. All valid submissions — whether they find a bypass or confirm a guarantee holds — are published in [`docs/break_it_log/`](break_it_log/README.md).

This is not a bug bounty in the traditional sense. It is a **constitutional stress test conducted in public**.

---

## What You're Trying to Break

### Primary targets — High-value invariants

| Invariant | What it claims | Module |
|:---|:---|:---|
| `GOV-SOLE-0` | No bypass path to production exists — `GovernanceGateV2` is the only route | `runtime/evolution/constitutional_evolution_loop.py` |
| `AFRT-0` | Red Team agent is structurally incapable of approving its own challenges | `runtime/evolution/afrt_engine.py` |
| `CEL-EVIDENCE-0` | Every epoch produces a verifiable SHA-256 hash-chained ledger entry | `runtime/evolution/constitutional_evolution_loop.py` |
| `CEL-REPLAY-0` | Any past epoch is byte-identically reproducible from original inputs | `runtime/evolution/constitutional_evolution_loop.py` |
| `LSME-0` | Shadow harness writes nothing to production — any write is a hard block | `runtime/innovations30/lsme_engine.py` |
| `HUMAN-0` | Tier 0 mutations require GPG-signed governor approval — architecturally, not by policy | `runtime/governance/governance_gate_v2.py` |
| `CJS-QUORUM-0` | High-stakes mutations require 2-of-3 jury verdict — sole evaluator path is blocked | `runtime/innovations30/constitutional_jury.py` |
| `CEB-0` | Constitutional change velocity is capped at 30% — double-HUMAN-0 activates above threshold | `runtime/innovations30/constitutional_entropy_budget.py` |
| `MMEM-0` | Identity gate never silently corrupts — fail-open with injected fallback score | `runtime/memory/identity_ledger.py` |
| `SELF-AWARE-0` | No mutation may reduce self-monitoring observability | `runtime/innovations30/self_awareness_invariant.py` |
| `INNOV-COMPLETE-0` | All 36 innovations importable at boot — `RuntimeError` if any fails | `runtime/innovations30/__init__.py` |
| `COMMUNITY-HUMAN0-0` | HUMAN-0 ratification cannot be delegated or automated via any workflow | `.github/workflows/constitution_amendment_validation.yml` |
| `CORE-SEMVER-0` | Breaking `adaad-core` API changes require major version bump + HUMAN-0 ratification | `adaad_core/__init__.py` |

→ [Full invariants matrix](governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md) — all 167 Hard-class invariants with module paths

---

## Scope

**In scope:**
- Any of the 167 Hard-class invariants listed in [`docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md`](governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md)
- Any governance gate, evidence chain, or replay integrity property
- The `adaad-core` stable API contract (`CORE-SEMVER-0`, `CORE-EXPORT-0`)
- Community governance pipeline (`COMMUNITY-HUMAN0-0`, `COMMUNITY-FGCON-0`)
- The shadow harness zero-write guarantee (`LSME-0`)
- The red-team structural constraint (`AFRT-0`)

**Out of scope:**
- Social engineering (this is a code and architecture challenge, not an operational one)
- Attacks requiring direct access to the governor's GPG private key
- Infrastructure-level exploits (OS, network, Python runtime itself)
- Issues already documented in open findings (see [`docs/governance/`](governance/))
- Denial of service

---

## How to Submit

**Option 1 — GitHub Issue (preferred):**
Use the [Break-It Submission template](.github/ISSUE_TEMPLATE/break_it_submission.md).

**Option 2 — Email:**
Send to `weirdo@innovativeai.llc` with subject `[BREAK-IT] <InvariantID>`. Include the same fields as the issue template.

### Required fields for a valid submission

```
Invariant targeted:   <ID, e.g. GOV-SOLE-0>
Claim being tested:   <what the invariant asserts>
Method:               <how you attempted the bypass>
Reproduction steps:   <exact commands, from a clean clone>
Evidence:             <ledger output, hash, error, or proof of absence>
Result:               BYPASS_CONFIRMED | GUARANTEE_HOLDS | PARTIAL_BYPASS
Environment:          Python version, OS, ADAAD version
```

**Reproduction steps must work from a clean `git clone`** with no credentials beyond the public repository.

---

## What Happens After You Submit

1. HUMAN-0 acknowledges within 5 business days
2. Submission is independently reproduced in a clean environment
3. Finding is classified:
   - **`BYPASS_CONFIRMED`** — invariant violated; immediate remediation + public disclosure with credit
   - **`GUARANTEE_HOLDS`** — attempt fully rebutted; submission published with explanation
   - **`PARTIAL_BYPASS`** — edge case identified; classified as finding, public with credit
   - **`OUT_OF_SCOPE`** — returned with explanation
4. All outcomes (including failed attempts) are published in [`docs/break_it_log/`](break_it_log/README.md) within 10 business days of classification
5. Contributor permanently credited in [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)

---

## Recognition

Every researcher who submits a valid in-scope attempt — regardless of outcome — is permanently recognized in `CONTRIBUTORS.md`.

**`BYPASS_CONFIRMED` submissions additionally receive:**
- Named credit in `CONTRIBUTORS.md` under "Constitutional Auditors — Confirmed Findings"
- The finding ID (`BREAK-<N>`) permanently attached to the invariant's history in the ledger
- Public acknowledgment in the next release CHANGELOG

There is no monetary bounty. Recognition is permanent, public, and governance-linked.

---

## Why We're Doing This

ADAAD makes strong claims. Every claim is backed by a ledger entry, a test file, and a runnable verification command. Publishing this challenge is consistent with those claims. If a bypass exists, we want to know before our users discover it. If every attempt confirms the guarantees hold, that is itself evidence worth publishing.

The adversarial model is not a threat to our governance design. It is the governance design.

> *"Build without limits. Govern without compromise."*

---

## Verification Environment

```bash
# Clean environment for all submissions
git clone https://github.com/InnovativeAI-adaad/adaad.git
cd adaad
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
export ADAAD_SEED=42 PYTHONHASHSEED=0

# Run the full governance pipeline
python -m app.main --replay audit --verbose

# One-command audit sandbox (no credentials needed)
docker compose up das-demo
```

---

## Submission Log

All submissions are published in [`docs/break_it_log/README.md`](break_it_log/README.md).

As of Phase 127 (2026-04-06): **0 bypass attempts submitted. 167 Hard-class invariants active.**

---

*ADAAD v9.60.0 · Phase 127 · Apache 2.0 · InnovativeAI LLC · Governor: Dustin L. Reid · Blackwell, Oklahoma*
