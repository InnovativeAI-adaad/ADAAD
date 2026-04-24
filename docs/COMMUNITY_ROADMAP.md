# SPDX-License-Identifier: Apache-2.0
# ADAAD — Community Roadmap & Contributor Onramp
**v9.92.0 · Phase 159 · Updated 2026-04-24**

> ADAAD is a constitutionally governed autonomous software evolution engine.
> Every contribution traverses the same mutation pipeline as the system's own self-improvements.
> The Constitution is the authority — not maintainer opinion.

---

## Quick Links

| Resource | Location |
|----------|----------|
| Constitution summary | [`docs/CONSTITUTION_SUMMARY.md`](CONSTITUTION_SUMMARY.md) |
| First-run checklist | [`docs/INSPECT_CHECKLIST.md`](INSPECT_CHECKLIST.md) |
| Deterministic demo | `python demo/deterministic_demo.py` |
| Adversarial harness | `pytest tests/adversarial/` |
| Break-it challenge | [`docs/BREAK_IT_CHALLENGE.md`](BREAK_IT_CHALLENGE.md) |
| Contributing guide | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Constitutional proposals | [`CONSTITUTION_PROPOSALS.md`](../CONSTITUTION_PROPOSALS.md) |
| Security reports | [`SECURITY.md`](../SECURITY.md) (private, not public issues) |

---

## Where ADAAD Is Today

| Metric | Value |
|--------|-------|
| Version | 9.92.0 |
| Phase | 159 |
| Innovations shipped | INNOV-01 → INNOV-65 (65 total) |
| Hard-class invariants | 263 (cumulative, enforced) |
| Constitutional rules | 23 named rules in `constitution.yaml` |
| CEL steps | 16-step Constitutional Evolution Loop |
| Deterministic replay | Active — any epoch is byte-reproducible |
| External verifiability | `docker compose up das-demo` — no credentials needed |

---

## 90-Day Roadmap (2026 Q2)

### Now (Phases 160–162): Stability & Verifiability

| Deliverable | Status | Phase |
|-------------|--------|-------|
| Deterministic demo (single-file, seed-pinned) | ✅ Shipped | 159 |
| Constitution summary (signed, versioned) | ✅ Shipped | 159 |
| Adversarial harness (24 deterministic tests) | ✅ Shipped | 159 |
| First-run inspect checklist | ✅ Shipped | 159 |
| Ledger verifier (`verify_ledger.py`) | Active | — |
| Docker DAS demo (`docker compose up das-demo`) | Active | — |
| PyPI v1.1-GA publication | ⏳ Track B (ADAADell) | TBD |

### Next (Phases 163–166): Adoptability

| Deliverable | Owner | Notes |
|-------------|-------|-------|
| INNOV-66: Governed Mutation Diffing (GMD) | DEVADAAD | Visual diff of constitutional impact per mutation |
| INNOV-67: Constitutional Health Dashboard | DEVADAAD | Browser-based CEL health panel |
| F-Droid listing | HUMAN-0 | Manual MR submission |
| Stable `adaad-core` SDK 1.0 | DEVADAAD + HUMAN-0 ratification | `CORE-SEMVER-0` gate |

### Horizon (Phases 167+): Sustainability

| Deliverable | Notes |
|-------------|-------|
| INNOV-68+: Community-proposed innovations | Via `CONSTITUTION_PROPOSALS.md` pipeline |
| External federation node support | `FGCON-0` / `federation_hmac_required` |
| Institutional partnership onramp | Governed integration path for external ADAAD nodes |
| Grant application support docs | `docs/SUSTAINABILITY.md` (planned) |

---

## How to Contribute

### Fastest path (< 30 minutes)

```bash
git clone https://github.com/InnovativeAI-adaad/adaad.git
cd adaad
python onboard.py                          # sets up env, validates governance
python demo/deterministic_demo.py          # run one governed epoch
pytest tests/adversarial/ -v              # verify constitutional guarantees
```

### Contribution types

| Type | Process | Constitutional gate |
|------|---------|---------------------|
| Bug fix | Standard PR → CEL review | `ast_validity`, `no_banned_tokens`, tests |
| Feature | Open issue first; discuss SPIE alignment | Full CEL + HUMAN-0 review |
| Documentation | PR against `.md` | SPDX header check |
| Constitutional amendment | `CONSTITUTION_PROPOSALS.md` pipeline | Double HUMAN-0 + CEL |
| Red-team challenge | `docs/BREAK_IT_CHALLENGE.md` | Public disclosure on resolution |
| Security report | `SECURITY.md` (private) | Coordinated disclosure |

### PR requirements (all PRs)

- [ ] `python -m pytest tests/ -v` — 100% pass, no exceptions
- [ ] `python scripts/check_spdx_headers.py` — exit 0
- [ ] No `:latest` Docker tags (`DAS-DOCKER-0`)
- [ ] No mock/bypass of GovernanceGate (`GOV-SOLE-0`)
- [ ] Documentation updated if behaviour changes

---

## Key Success Metrics

| Metric | Target | How to measure |
|--------|--------|---------------|
| Demo replay success rate | 100% | `python demo/deterministic_demo.py` exit 0 on any Python 3.11+ |
| Adversarial harness pass rate | 24/24 | `pytest tests/adversarial/` |
| Time to first verified epoch | < 30 min | Cold clone → `onboard.py` → checklist |
| SPDX compliance | 100% | `scripts/check_spdx_headers.py` exit 0 |
| Constitutional invariant coverage | 263/263 | `scripts/check_invariant_count.py` |

---

## Governance Principles for Contributors

1. **The Constitution is the authority.** If a PR violates a Hard-class invariant,
   it is blocked by the system — not by a maintainer's discretion.

2. **Audit trails are non-negotiable.** Every change is ledgered. Do not attempt
   to suppress or truncate ledger output.

3. **HUMAN-0 actions cannot be delegated.** Tier 0 ratification, constitutional
   amendments, and key ceremonies require Dustin L. Reid's GPG signature. Do not
   open PRs that bypass this.

4. **Determinism is a contract.** If your change makes any gate or evaluation
   non-deterministic (same seed → different output), it will be blocked by
   `ACSE-SEED-NONDETERMINISTIC` and the adversarial harness.

5. **Fail-closed is the default.** Any gate that cannot produce a decision
   must block, not approve. Design new invariants with this in mind.

---

## Community Channels

- **Issues**: GitHub Issues — bug reports, feature requests, architecture discussion
- **Security**: See `SECURITY.md` — do not file public issues for vulnerabilities
- **Red-team challenges**: `docs/BREAK_IT_CHALLENGE.md` — all valid findings published
- **Constitutional proposals**: `CONSTITUTION_PROPOSALS.md` — formal RFC process

---

*This roadmap is maintained by DEVADAAD and reflects the SPIE (Self-Proposing Innovation Engine) output.*
*Ratified items are GPG-tagged by HUMAN-0 at each version promotion.*
