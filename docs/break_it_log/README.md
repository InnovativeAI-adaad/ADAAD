# ADAAD Break-It Challenge — Public Submission Log

**Maintained by:** Governor (HUMAN-0) · Dustin L. Reid  
**Challenge launched:** 2026-04-06 · Phase 127 · v9.60.0  
**Log policy:** All in-scope submissions published within 10 business days of classification, regardless of outcome.

→ [Challenge rules and submission instructions](../BREAK_IT_CHALLENGE.md)

---

## Summary

| Metric | Count |
|:---|:---:|
| Total submissions received | 0 |
| `BYPASS_CONFIRMED` | 0 |
| `GUARANTEE_HOLDS` | 0 |
| `PARTIAL_BYPASS` | 0 |
| `OUT_OF_SCOPE` | 0 |
| Hard-class invariants active | 167 |
| Invariants never challenged | 167 |

*Last updated: 2026-04-06*

---

## Active Invariants Never Successfully Bypassed

All 167 Hard-class invariants are unchallenged. The following high-value targets have received zero bypass attempts:

| Invariant | Claim | Status |
|:---|:---|:---:|
| `GOV-SOLE-0` | No bypass path to production | 🔒 Unchallenged |
| `AFRT-0` | Red Team cannot approve | 🔒 Unchallenged |
| `CEL-EVIDENCE-0` | Every epoch hash-chained | 🔒 Unchallenged |
| `CEL-REPLAY-0` | Byte-identical epoch replay | 🔒 Unchallenged |
| `LSME-0` | Shadow harness zero-write | 🔒 Unchallenged |
| `HUMAN-0` | GPG key required for Tier 0 | 🔒 Unchallenged |
| `CJS-QUORUM-0` | 2-of-3 jury for high-stakes | 🔒 Unchallenged |
| `COMMUNITY-HUMAN0-0` | HUMAN-0 cannot be automated | 🔒 Unchallenged |

→ [Full 167-invariant matrix](../governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md)

---

## Submission Index

*No submissions yet. [Submit the first attempt.](../../.github/ISSUE_TEMPLATE/break_it_submission.md)*

---

## Log Format

Each entry follows this structure:

```
### BREAK-<N> — <InvariantID> — <YYYY-MM-DD>

**Submitted by:** @username  
**Invariant:** <ID>  
**Claim tested:** <what the invariant asserts>  
**Method:** <summary of approach>  
**Result:** BYPASS_CONFIRMED | GUARANTEE_HOLDS | PARTIAL_BYPASS  
**Reproduced:** Yes / No  
**Response:** <explanation of outcome>  
**Finding ID:** <FINDING-XX-XXX if applicable>  
**Credit:** [CONTRIBUTORS.md](../../CONTRIBUTORS.md)
```

---

*Published under the repository proprietary license unless otherwise agreed in writing. All submissions are the intellectual property of their authors. ADAAD publishes classification and outcome; raw exploit details for `BYPASS_CONFIRMED` findings are coordinated with submitter before public disclosure.*
