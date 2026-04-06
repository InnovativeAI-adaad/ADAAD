# Phase 125 — Invariant Registration Record

**Phase:** 125
**Version:** v9.58.0
**Date:** 2026-04-05
**Cumulative Hard-class Invariants:** 167

---

## New Invariants Registered This Phase

### COMMUNITY-FGCON-0 (Hard-class)

**Full definition:**
Community amendments to the ADAAD constitutional registry are subject to FGCON-QUORUM-0
(registered Phase 119). No single contributor may both propose and ratify the same
constitutional amendment. The FGCON quorum gate requires a minimum of two distinct
governance principals before any proposal is eligible for HUMAN-0 ratification.

**Enforcement surface:**
- `.github/workflows/constitution_amendment_validation.yml` (CI gate)
- `scripts/validate_amendment_proposal.py` (structural validation)
- `CONSTITUTION_PROPOSALS.md` (lifecycle documentation)

**Test coverage:**
- T125-COMM-10 (FGCON checkbox enforcement)
- T125-WFLOW-22 (workflow FGCON quorum job)
- T125-INV-28 (no self-ratification path in any workflow)

---

### COMMUNITY-HUMAN0-0 (Hard-class)

**Full definition:**
HUMAN-0 ratification of constitutional amendments cannot be delegated, automated, or bypassed
through any community governance workflow, bot account, cosignatory arrangement, or CI/CD
pipeline configuration. The only valid ratification signal is a GPG signature from HUMAN-0's
registered key on the amendment merge commit.

**Enforcement surface:**
- `.github/workflows/constitution_amendment_validation.yml` (no auto-merge path)
- `CONSTITUTION_PROPOSALS.md` (ratification inviolability documented)
- `docs/GOVERNANCE_PARTICIPATION.md` (contributor guidance)
- `scripts/validate_amendment_proposal.py` (rejects auto-ratification claims)

**Test coverage:**
- T125-COMM-11 (auto-ratification claim rejection)
- T125-TMPL-17 (no auto-merge instructions in template)
- T125-INV-29 (no autonomous merge path in workflow)
- T125-INV-30 (governance artifact integrity check)

---

## Cumulative Invariant Count

| Up to Phase | Count |
|-------------|-------|
| Phase 124   | 165   |
| Phase 125   | **167** |
