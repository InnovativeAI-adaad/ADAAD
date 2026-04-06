# ADAAD Governance Participation Guide

> **Version:** v9.58.0 · Phase 125
> **Invariants:** `COMMUNITY-FGCON-0` · `COMMUNITY-HUMAN0-0`
> **Authority:** HUMAN-0 — Dustin L. Reid / InnovativeAI LLC

---

## What Is ADAAD Governance?

ADAAD's Constitutional Evolution Loop (CEL) is the operational core of the system. It is not
configurable by convention — it is enforced by cryptographic invariants, shadow execution gates,
and a Hash-Chained Lineage Ledger. Every mutation the system promotes must survive constitutional
scrutiny before it becomes part of the live runtime.

The constitution itself is governed by a small set of Hard-class invariants that define what kinds
of changes are permissible. Community governance participation means contributing to that set of
invariants — proposing, deliberating, and validating new constitutional rules.

What it does not mean: autonomously ratifying changes. That authority is structurally reserved.

---

## The Governance Hierarchy

```
HUMAN-0 (Dustin L. Reid)
    │   Sole ratification authority. GPG-signed merge only.
    │   Cannot be delegated, simulated, or bypassed.
    │
FGCON Quorum
    │   Federation Governance Consensus (Phase 119).
    │   Minimum 2 distinct governance principals required.
    │   Self-ratification structurally blocked.
    │
Community Contributors
        Propose, deliberate, and validate amendments.
        May not ratify. May not self-approve.
```

This is not bureaucracy — it is the architectural guarantee that ADAAD's governance remains
trustworthy. The value of the system depends entirely on the integrity of its constitutional
layer. Community participation strengthens that layer; it does not shortcut it.

---

## How to Propose a Constitutional Amendment (Lifecycle)

### Step 1 — Read the existing constitution

Before proposing a new invariant, review [`CONSTITUTION.md`](../CONSTITUTION.md) and
[`CONSTITUTION_PROPOSALS.md`](../CONSTITUTION_PROPOSALS.md). If your proposed invariant
is already covered by an existing one, your proposal will be rejected for redundancy.

### Step 2 — Draft your invariant precisely

A good invariant is:
- **Specific** — it names the exact failure mode it prevents
- **Testable** — a passing/failing test can be written for it
- **Non-redundant** — it addresses something no existing invariant covers
- **Hard or Soft** — you must decide whether violation blocks promotion or triggers alert

### Step 3 — Open an issue using the amendment template

Navigate to [Issues → New Issue](https://github.com/InnovativeAI-adaad/ADAAD/issues/new/choose)
and select **"Constitutional Amendment Proposal"**. Complete every required field. Partial
proposals are machine-rejected.

Required fields:
- Proposed invariant identifier (unique, snake-case)
- Invariant class (Hard or Soft)
- Rationale (≥ 50 words)
- Affected modules
- Proposed acceptance test
- Conflict analysis
- FGCON quorum confirmation checkboxes

### Step 4 — CI validation

Within minutes of submission, the CI validation workflow fires. It checks:

- All required fields are present and non-empty
- Rationale meets the 50-word minimum
- Invariant identifier is properly formatted
- No auto-ratification path is claimed
- FGCON confirmation checkboxes are checked

If validation fails, the issue is labelled `needs-revision`. Revise the issue body and
the CI re-fires automatically on edit.

### Step 5 — HUMAN-0 triage

Validated proposals enter the HUMAN-0 triage queue. HUMAN-0 reviews the constitutional
merit of the proposal and assigns it to the governance queue or returns it for revision
with feedback.

HUMAN-0 triage is not automated and does not operate on a fixed schedule.
High-quality, well-reasoned proposals move faster.

### Step 6 — FGCON deliberation

Once queued, the FGCON module evaluates whether the quorum conditions are met:
- At least 2 distinct governance principals have reviewed the proposal
- The proposer is not the ratifying principal
- No existing invariant is in conflict

### Step 7 — HUMAN-0 ratification

HUMAN-0 ratifies the amendment via GPG-signed merge to the governance queue. This step
has no automation path. No bot, workflow, or cosignatory arrangement substitutes for
HUMAN-0's GPG signature.

Post-ratification, the amendment is appended to `CONSTITUTION.md` with full provenance
hash, the invariant enters the CEL, and a phase delivery artifact is produced.

---

## What Makes a Good Amendment

The ADAAD constitution exists to make the system's behaviour predictable, verifiable, and
resilient to both internal and external adversarial pressure. A good amendment:

1. **Closes a real gap** — there is a concrete failure mode or governance risk that no
   existing invariant prevents.

2. **Passes the adversarial test** — if a Bad Actor tried to exploit the absence of this
   invariant, what would happen? If the answer is "nothing interesting," the invariant
   probably isn't Hard-class.

3. **Has a crisp test** — if you cannot write a test that deterministically fails when the
   invariant is violated, the invariant is too vague.

4. **Doesn't conflict** — adding an invariant that contradicts an existing one requires
   first proposing a revision or deprecation of the conflicting invariant.

---

## What Community Governance Is Not

- **It is not a shortcut to shipping features.** Proposing an invariant that relaxes
  an existing constraint will be rejected.

- **It is not a voting mechanism.** Quorum is a structural check, not a popularity
  contest. Ten identical proposals do not outweigh one well-reasoned one.

- **It is not autonomous.** The human in HUMAN-0 is not decorative.

---

## Local Validation Tool

Before submitting a proposal, you can validate it locally:

```bash
python scripts/validate_amendment_proposal.py --input my_proposal.md
```

This runs the same checks as CI. Fix any reported issues before opening the issue.

---

## Reference

| Resource | Location |
|----------|----------|
| Constitutional invariant registry | [`CONSTITUTION.md`](../CONSTITUTION.md) |
| Amendment proposal registry | [`CONSTITUTION_PROPOSALS.md`](../CONSTITUTION_PROPOSALS.md) |
| Proposal issue template | [`.github/ISSUE_TEMPLATE/constitution_amendment.md`](../.github/ISSUE_TEMPLATE/constitution_amendment.md) |
| CI validation workflow | [`.github/workflows/constitution_amendment_validation.yml`](../.github/workflows/constitution_amendment_validation.yml) |
| Local validation script | [`scripts/validate_amendment_proposal.py`](../scripts/validate_amendment_proposal.py) |
| Phase 119 FGCON spec | [`artifacts/governance/phase119/`](../artifacts/governance/phase119/) |
| Phase 125 governance artifact | [`artifacts/governance/phase125/`](../artifacts/governance/phase125/) |
