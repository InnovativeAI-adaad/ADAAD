---
name: Constitutional Amendment Proposal
about: Propose a new Hard-class or Soft-class constitutional invariant for ADAAD
labels: constitutional-amendment, governance-review
assignees: ''
---

<!--
IMPORTANT: This template is machine-validated by CI.
All required fields must be filled in. Proposals with missing fields are
automatically labelled `needs-revision` and returned to the proposer.

Review CONSTITUTION_PROPOSALS.md before submitting.
HUMAN-0 ratification is required for all amendments — this cannot be delegated.
A single contributor cannot both propose and ratify the same amendment (FGCON-QUORUM-0).
-->

## Proposed Invariant Identifier

<!--
Use snake-case format: CATEGORY-KEYWORD-N (e.g. CACHE-EVICT-0, FED-AUTH-0)
Must be unique — check CONSTITUTION.md before proposing.
-->

```
PROPOSED_INVARIANT_ID: 
```

## Invariant Class

<!-- Select one: Hard (blocks CEL promotion) or Soft (triggers alert) -->

- [ ] **Hard** — Constitutional violation blocks mutation promotion
- [ ] **Soft** — Constitutional violation triggers governance alert (non-blocking)

## Rationale

<!--
Explain WHY this invariant is constitutionally necessary.
Minimum 50 words required. CI rejects proposals below this threshold.
Describe: the failure mode this prevents, the governance principle it enforces,
and why existing invariants do not already cover this.
-->

*[Your rationale here — minimum 50 words]*

## Affected Modules

<!--
List all source files, runtime modules, or API surfaces touched by this invariant.
-->

- `runtime/...`
- `server.py` (if applicable)
- `adaad_core/...` (if applicable)

## Proposed Acceptance Test

<!--
Name and describe the test that validates this invariant.
Format: T<phase>-<CATEGORY>-<NN>: <description>
-->

**Test ID:** `T???-???-01`

**Description:**
*[What does this test verify? What inputs trigger the violation? What is the expected outcome?]*

## Conflict Analysis

<!--
State explicitly whether this proposal conflicts with any existing invariants.
Reference specific invariant IDs from CONSTITUTION.md.
If no conflicts: write "No conflicts identified with existing invariants."
-->

*[Conflict analysis here]*

## FGCON Quorum Confirmation

<!--
COMMUNITY-FGCON-0 prohibits a proposer from also being the ratifying principal.
By submitting this proposal, you confirm the following:
-->

- [ ] I confirm I am not the ratifying principal for this proposal
- [ ] I understand HUMAN-0 ratification (GPG-signed) is required and cannot be automated
- [ ] I have read `CONSTITUTION_PROPOSALS.md` and understand the full amendment lifecycle

## Supporting Evidence (Optional)

<!--
Link to relevant discussions, related phases, external research, or prior art
that supports the constitutional necessity of this invariant.
-->

*[Optional supporting links or context]*

---

*This proposal is subject to CI structural validation, FGCON quorum evaluation,
and HUMAN-0 ratification. See [`CONSTITUTION_PROPOSALS.md`](../../CONSTITUTION_PROPOSALS.md)
for the complete amendment lifecycle.*
