# Contributing to ADAAD

ADAAD is open source (Apache 2.0) and welcomes contributions. Before you begin, understand two things:

1. **Your contribution traverses the same pipeline as every other change.** Pull requests do not bypass the Constitutional Evolution Loop. That's the point.
2. **The Constitution is the authority.** If your contribution conflicts with a Hard-class invariant, it will be blocked — by the system, not by a human reviewer exercising opinion.

---

## Types of contribution

| Type | Process |
|:-----|:--------|
| Bug fixes | Standard PR → CEL review → merge |
| Feature additions | Open an issue first; discuss alignment with SPIE roadmap |
| Constitutional amendment proposals | See [`CONSTITUTION_PROPOSALS.md`](CONSTITUTION_PROPOSALS.md) |
| Documentation | PR against the relevant `.md` file |
| Red-team challenges | See [`docs/BREAK_IT_CHALLENGE.md`](docs/BREAK_IT_CHALLENGE.md) |
| Security reports | See [`SECURITY.md`](SECURITY.md) — do not file public issues |

---

## Pull request requirements

All PRs must:

- Pass the full test suite (`python -m pytest tests/ -v` — 100% required, no exceptions)
- Include or update relevant documentation
- Not introduce `:latest` Docker tags (`DAS-DOCKER-0`)
- Not bypass or mock the GovernanceGate (`GOV-SOLE-0`)
- Validate any `server.py` changes with `python3 -c "import ast; ast.parse(open('server.py').read())"`

PRs that fail constitutional invariant checks will be closed with an explanation of which invariant was violated.

---

## Constitutional amendment proposals

ADAAD's Constitution can be amended — but not autonomously. The community pipeline (Phase 125, `COMMUNITY-HUMAN0-0`) governs how proposals flow from community → CEL → HUMAN-0 ratification.

See [`CONSTITUTION_PROPOSALS.md`](CONSTITUTION_PROPOSALS.md) for the full process.

The short version: propose → discuss → formal RFC → CEL review → HUMAN-0 ratification. The system cannot amend itself. That's constitutional invariant `COMMUNITY-HUMAN0-0`.

---

## Code style

- Python 3.12
- No type: ignore without a comment explaining why
- All governance-critical modules require a module-level docstring citing their constitutional invariants
- Naming convention for invariants: `INNOVATION_CODE-DESCRIPTION-0`

---

## Running the test suite

```bash
source .venv/bin/activate
python -m pytest tests/ -v --tb=short
```

100% pass rate required before any PR is considered. The pipeline won't promote a release with test failures — neither will a human reviewer.

---

## The Break-It Challenge

Found a way to bypass the GovernanceGate? Discovered a constitutional invariant that can be violated without triggering a block? We want to know.

See [`docs/BREAK_IT_CHALLENGE.md`](docs/BREAK_IT_CHALLENGE.md) for the formal red-team protocol. Responsible disclosure is governed by INNOV-36 · BIRC.

---

## Code of conduct

See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---

## Recognition

Contributors who ship accepted PRs are added to [`CONTRIBUTORS.md`](CONTRIBUTORS.md) with their contribution cited.

Constitutional amendment proposal authors are recorded in the Constitution Version Registry (INNOV-43 · CVR) with a permanent ledger entry.

---

## Questions

Open an issue. Or ask DORK — it has access to the full governance history and can explain any past decision in plain English.
