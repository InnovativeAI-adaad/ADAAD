# SPDX-License-Identifier: Apache-2.0
# ADAAD — First-Run Inspect Checklist
**What to look at after your first epoch**

After running `python onboard.py` or `python demo/deterministic_demo.py`, use this
checklist to verify the system behaved correctly.  Each item maps to a constitutional
guarantee — if any item doesn't match, a constitutional invariant may be violated.

---

## 1 · Ledger (`data/`)

```bash
# List ledger files produced
ls data/*.jsonl

# Spot-check the last ledger record
tail -1 data/demo_ledger.jsonl | python3 -m json.tool
```

**What to verify:**
- [ ] Record contains `mutation_id`, `epoch_id`, `chain_digest`
- [ ] `gov_approved` is `true` for a clean sandbox epoch
- [ ] `chain_digest` is a 64-char hex string
- [ ] No two records share the same `chain_digest`

**Verify chain integrity independently:**

```bash
python verify_ledger.py data/evolution_ledger.jsonl
# Exit 0 = chain intact.  Exit 1 = tampered record at position N.
```

---

## 2 · Governance Gate Decision

```bash
# Run demo with JSON output to inspect decision object
python demo/deterministic_demo.py --json | python3 -m json.tool
```

**What to verify:**
- [ ] `governance.approved` matches the epoch_result
- [ ] `governance.decision_id` is present and non-empty
- [ ] `acse.vectors` ≥ 0 (ACSE ran; 0 is valid for clean mutations)
- [ ] `acse.seed` is a 64-char hex string

---

## 3 · Evolution Ledger (`data/evolution_ledger.jsonl`)

```bash
# Count records
wc -l data/evolution_ledger.jsonl

# Summarize all mutation verdicts
python3 -c "
import json
records = [json.loads(l) for l in open('data/evolution_ledger.jsonl')]
approved = sum(1 for r in records if r.get('approved') or r.get('gov_approved'))
print(f'Total records : {len(records)}')
print(f'Approved      : {approved}')
print(f'Rejected      : {len(records) - approved}')
"
```

---

## 4 · Replay Verification

```bash
# Replay the fixed demo epoch — output must be identical to first run
python demo/deterministic_demo.py \
  --seed a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2

# The Mutation ID must always be:  DEMO-MUT-4C5152BA
# The chain digest of record 1 must always start with:  8252c4c5…
```

**What to verify:**
- [ ] Mutation ID matches `DEMO-MUT-4C5152BA`
- [ ] Epoch seed fingerprint matches `1dd4e7cb45bcb872`
- [ ] Exit code 0 (APPROVED)

---

## 5 · Constitutional Rule Check

```bash
# Verify the canonical rule count matches the running system
python3 -c "
import json, sys
sys.path.insert(0, '.')
with open('governance/constitutional_rule_count.json') as f:
    meta = json.load(f)
count = meta['rule_count']['total_rules']
print(f'Constitutional rules (canonical): {count}')
print(f'Constitution version: {meta[\"rule_count\"][\"as_of\"]}')
"
```

**What to verify:**
- [ ] `total_rules` matches the value in `docs/CONSTITUTION_SUMMARY.md`
- [ ] `as_of` version matches the header in `docs/CONSTITUTION.md`

---

## 6 · SPDX Header Compliance

```bash
python3 scripts/check_spdx_headers.py
# Must exit 0 for a clean repo.
# Any exit 1 = a source file is missing Apache-2.0 header.
```

---

## 7 · Adversarial Harness (fast safety smoke test)

```bash
PYTHONPATH=. python3 -m pytest tests/adversarial/ -v --tb=short
# Must be 24/24 pass.  Any failure = constitutional regression.
```

---

## 8 · Agent State (`adaad_agent_state.json`)

```bash
python3 -c "
import json
s = json.load(open('.adaad_agent_state.json'))
print('Version       :', s.get('current_version'))
print('Hard-class Δ  :', s.get('hard_class_invariant_count'))
print('Last innovation:', s.get('last_innovation'))
"
```

**What to verify:**
- [ ] `current_version` matches `VERSION` file
- [ ] `hard_class_invariant_count` ≥ 263

---

## Quick-Reference: Key File Locations

| Artefact | Path |
|----------|------|
| Evolution ledger | `data/evolution_ledger.jsonl` |
| Demo ledger | `data/demo_ledger.jsonl` |
| Governance decision log | `data/gate_decisions.jsonl` (if exists) |
| Agent state | `.adaad_agent_state.json` |
| Constitution (machine) | `runtime/governance/constitution.yaml` |
| Constitution (human) | `docs/CONSTITUTION.md` |
| Constitution summary | `docs/CONSTITUTION_SUMMARY.md` |
| Invariant count | `governance/constitutional_rule_count.json` |
| Adversarial harness | `tests/adversarial/test_adversarial_harness.py` |
| Deterministic demo | `demo/deterministic_demo.py` |

---

*Time-to-first-verified-epoch target: < 30 minutes from cold clone.*
*If anything above fails, open an issue referencing the invariant that broke.*
