# ADAAD Constitutional Amendment Proposals

> **Governed under:** `COMMUNITY-FGCON-0` · `COMMUNITY-HUMAN0-0`
> **Ratification authority:** HUMAN-0 (Dustin L. Reid) — GPG-signed merge only
> **Version:** v9.58.0 · Phase 125

---

## Overview

This document is the canonical registry for community-originated constitutional amendment proposals
submitted to the ADAAD governance system. It defines the proposal lifecycle, structural requirements,
review criteria, and invariant constraints that govern the amendment process.

Community participation is structurally welcome and architecturally bounded. No proposal becomes
constitutional law without FGCON quorum validation and HUMAN-0 ratification. These are not policy
choices — they are cryptographic and structural invariants enforced by the Constitutional Evolution
Loop (CEL).

---

## Amendment Lifecycle

```
Community opens Issue                     (GitHub Issue template: constitution_amendment.md)
        │
        ▼
CI validation gate fires                  (.github/workflows/constitution_amendment_validation.yml)
        │                                 Checks: required fields, rationale word count ≥50,
        │                                         no auto-ratification path, invariant conflict scan
        │
        ├─ FAIL ──► Issue flagged with label:needs-revision  (proposer must revise)
        │
        ▼
HUMAN-0 reviews and assigns to queue      (manual triage — cannot be automated)
        │
        ▼
FGCON quorum evaluation                   (Phase 119 FGCON-QUORUM-0 enforced)
        │                                 Minimum 2 distinct governance principals required
        │                                 Self-ratification is architecturally blocked
        │
        ├─ QUORUM FAIL ──► Proposal returned to deliberation
        │
        ▼
HUMAN-0 ratification                      (GPG-signed merge to governance queue)
        │                                 No auto-merge path exists or may be added
        │
        ▼
CONSTITUTION.md bump                      (amendment appended with provenance hash)
        │
        ▼
Phase delivery + invariant registration   (new Hard-class invariant enters CEL)
```

---

## Structural Requirements

Every proposal submitted via the issue template **must** include:

| Field                  | Requirement                                                        |
|------------------------|--------------------------------------------------------------------|
| `proposed_invariant`   | Snake-case identifier, e.g. `MY-FEATURE-0`                        |
| `invariant_class`      | `Hard` or `Soft` — Hard blocks promotion, Soft triggers alert      |
| `rationale`            | ≥ 50 words explaining why this invariant is constitutionally necessary |
| `affected_modules`     | List of source files or runtime paths touched                      |
| `proposed_test`        | Name and description of the acceptance test that validates the invariant |
| `conflict_analysis`    | Explicit statement of whether this conflicts with existing invariants |
| `fgcon_quorum`         | Confirmation that proposer is not also the ratifying principal      |

Proposals missing any required field are **automatically rejected** by CI and labelled
`needs-revision`. The proposer must correct and re-submit. No exceptions.

---

## Constitutional Invariants Governing This Process

### `COMMUNITY-FGCON-0` (Hard-class)
Community amendments are subject to `FGCON-QUORUM-0` (Phase 119). A single contributor
cannot propose **and** ratify the same amendment. The governance quorum must include at least
two distinct principals, one of whom must be HUMAN-0 at ratification.

### `COMMUNITY-HUMAN0-0` (Hard-class)
HUMAN-0 ratification cannot be delegated, automated, or bypassed via any community governance
workflow. No CI job, bot account, or cosignatory arrangement constitutes valid ratification.
GPG signature from HUMAN-0's registered key is the only valid ratification signal.

---

## Active Proposals

| ID | Title | Status | Opened | Phase Target |
|----|-------|--------|--------|--------------|
| — | *No proposals currently in queue* | — | — | — |

---

## Ratified Amendments

| Amendment | Ratified In | Invariant | Phase |
|-----------|-------------|-----------|-------|
| Community Governance Infrastructure | v9.58.0 | `COMMUNITY-FGCON-0`, `COMMUNITY-HUMAN0-0` | 125 |

---

## How to Submit a Proposal

1. Navigate to the [ADAAD Issues](https://github.com/InnovativeAI-adaad/ADAAD/issues/new/choose) page.
2. Select **"Constitutional Amendment Proposal"**.
3. Complete **all required fields** — partial proposals are automatically rejected.
4. Submit. CI validation fires within minutes.
5. If validation passes, your proposal enters the HUMAN-0 triage queue.
6. Monitor the issue for feedback from governance principals.

Proposals are evaluated on constitutional merit, not submission order. Quality of rationale and
precision of invariant definition are the primary review criteria.

---

## Related Documents

- [`CONSTITUTION.md`](./CONSTITUTION.md) — the canonical constitutional invariant registry
- [`docs/GOVERNANCE_PARTICIPATION.md`](./docs/GOVERNANCE_PARTICIPATION.md) — contributor governance guide
- [`scripts/validate_amendment_proposal.py`](./scripts/validate_amendment_proposal.py) — local validation tool
- [Phase 119 FGCON specification](./artifacts/governance/phase119/) — quorum enforcement reference
