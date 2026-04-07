---
name: "🔴 Break-It Challenge Submission"
about: "Submit an attempt to bypass a ADAAD Hard-class constitutional invariant"
title: "[BREAK-IT] <InvariantID> — <brief description>"
labels: ["break-it-challenge", "governance-audit"]
assignees: ["dreezy66"]
---

<!--
Thank you for participating in the ADAAD Break-It Challenge.
Read the full rules before submitting: docs/BREAK_IT_CHALLENGE.md
All in-scope submissions are published in docs/break_it_log/ regardless of outcome.
-->

## Invariant Targeted

<!-- The exact invariant ID, e.g. GOV-SOLE-0, AFRT-0, CEL-REPLAY-0 -->

**Invariant ID:**
**Invariant claim:** <!-- Copy from docs/governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md -->
**Module / file:** <!-- e.g. runtime/evolution/afrt_engine.py -->

---

## Method

<!-- Describe your approach. How did you attempt to bypass the invariant? -->

---

## Reproduction Steps

<!-- Must work from a clean git clone with no credentials beyond the public repo -->

```bash
git clone https://github.com/InnovativeAI-adaad/adaad.git
cd adaad
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
export ADAAD_SEED=42 PYTHONHASHSEED=0

# Your reproduction steps here:

```

---

## Evidence

<!-- Paste ledger output, hash, error message, or proof of absence.
     For BYPASS_CONFIRMED: show the invariant violation without epoch abort.
     For GUARANTEE_HOLDS: show that the invariant correctly blocked the attempt. -->

```
<paste evidence here>
```

---

## Result Classification (your assessment)

- [ ] `BYPASS_CONFIRMED` — I successfully violated the invariant without triggering an epoch abort
- [ ] `GUARANTEE_HOLDS` — My attempt was correctly blocked; the invariant held
- [ ] `PARTIAL_BYPASS` — I found an edge case or weakened form of the guarantee
- [ ] `UNSURE` — I need help classifying the outcome

---

## Environment

| Field | Value |
|:---|:---|
| Python version | |
| OS | |
| ADAAD version | |
| Git commit SHA | |

---

## Notes

<!-- Anything else you want to share: related invariants, suggested mitigations, or context -->

---

**By submitting, you agree to:**
- Public publication of this submission and its classification in `docs/break_it_log/`
- Attribution in `CONTRIBUTORS.md`
- Coordination with HUMAN-0 before public disclosure of any `BYPASS_CONFIRMED` finding

*Challenge rules: [docs/BREAK_IT_CHALLENGE.md](../../docs/BREAK_IT_CHALLENGE.md)*
