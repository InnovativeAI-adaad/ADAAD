# Contributing to ADAAD

![Governance: Fail-Closed](https://img.shields.io/badge/Governance-Fail--Closed-critical)
![Replay: Deterministic](https://img.shields.io/badge/Replay-Deterministic-0ea5e9)

> Governance-first contribution guide — read before opening any governance-impacting PR.

**Last reviewed:** 2026-04-05

By submitting a contribution, you agree that your work is licensed under the Apache License 2.0 (see `LICENSE`). The Apache 2.0 license includes an express patent grant — see Section 3 of the LICENSE file. No trademark rights are granted or implied; see `TRADEMARKS.md` and `BRAND_LICENSE.md`.

---

## Development setup

```bash
# 1. Create and activate virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install editable package + dev extras
pip install -e .[dev]

# 3. Initialize workspace
python nexus_setup.py
python nexus_setup.py --validate-only

# 4. Verify boot
python -m app.main --replay audit --verbose
```

---

## Branch naming

| Type | Pattern |
|---|---|
| Feature | `feat/<short-description>` |
| Phase implementation | `feat/phase<N>-<module-slug>` |
| Fix | `fix/<short-description>` |
| Docs | `docs/<short-description>` |
| Governance | `governance/<short-description>` |

---

## Commit message convention

Commits for governed PR work must include structured trailers for audit traceability.

**Required trailers:**

- `PR-ID: <id>`
- `CI tier: <docs|low|standard|critical>`
- `Replay proof: <value>`

`Replay proof` rules:
- `critical` tier → must include strict replay output artifact hash: `Replay proof: sha256:<hash>`
- All other tiers → must be exactly: `Replay proof: not-required`

Examples:

```text
feat(governance): enforce token_ok in gate certifier

PR-ID: PR-HARDEN-01
CI tier: critical
Replay proof: sha256:4f6b9f0c2d0f6e9f7fb9d4e35e8d7a2b8a5af1d4a7df6c2edc36f90bfed2ee11
```

```text
docs(governance): document federation key registry controls

PR-ID: PR-DOCS-01
CI tier: docs
Replay proof: not-required
```

---

## Governed build-agent contract

Read [`AGENTS.md`](AGENTS.md) before opening governance-impacting PRs. It defines lane expectations, fail-closed behavior, and evidence requirements.

---

## Governance-impact labeling

If your change touches governance-critical surfaces, include `governance-impact` in your PR labels.

Governance-critical paths include:

- `runtime/constitution*`
- `runtime/evolution/*`
- `runtime/governance/federation/*`
- `security/ledger/*`
- `security/cryovant.py`
- `app/mutation_executor.py`
- `app/main.py`

---

## Replay requirements

| Scenario | Requirement |
|---|---|
| All PRs | Run `--replay audit` during local validation |
| Governance-impact PRs | Must pass strict replay locally before submission |

```bash
python -m app.main --replay audit --verbose
python -m app.main --verify-replay --replay strict --verbose
```

---

## Test requirements

- Add tests for all functional changes.
- Run targeted pytest suites for impacted modules.
- Do not merge with failing tests.
- Do not remove, skip, or mark xfail on any failing test to make a gate pass.

```bash
python -m pytest -q tests/test_preflight_import_smoke.py
```

---

## Code expectations

- Follow existing code style.
- Keep SPDX headers in all source files: `# SPDX-License-Identifier: Apache-2.0`
- Keep dependencies documented and pinned.
- Avoid introducing nondeterministic behavior in governance paths.

**Never introduce in governance-critical paths:**
- `random` without a fixed seed
- `datetime.now()` — **naive (no timezone)** — nondeterministic across environments. Use `datetime.now(timezone.utc)` which is explicitly permitted; it produces a deterministic UTC timestamp independent of the host locale. The constitutional ban targets the zero-argument form only.
- Time-based scoring without a deterministic provider
- Environment-dependent policy evaluation
- `uuid4()` without a deterministic provider
- Federation HMAC key material in source files or log output

---

## Active phase

Current checkpoint: **Phase 142 shipped (v9.75.0) · 231 Hard-class invariants · 48 innovations complete**.

Next phase: **Phase 143** — see [ROADMAP.md](ROADMAP.md) for current planning.

For new governed work, use the current PR ID convention from `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md` (for example, `PR-PHASE94-01`) rather than legacy `PR-PHASE6-*` identifiers.

Automation sequencing is controlled by `docs/governance/ADAAD_PR_PROCESSION_2026-03-v2.md`; treat that v2 procession file as the canonical source for PR order and closure state.

---

## Canonical agent runtime namespace

`adaad.agents` is the canonical runtime namespace.

- Import from `adaad.agents.*` in all new code.
- `app.agents.*` is a temporary compatibility shim only.
- CI import-lint gates reject newly introduced `app.agents.*` imports outside the shim.

---


## Human-facing image-weight rule

New human-facing imagery in `README.md`, docs pages, and user-facing UI panels must follow the low-weight imagery policy in `docs/DOCS_VISUAL_STYLE_GUIDE.md`.

- Use `img-low-weight` (or `data-img-weight="low"`) by default.
- Use `img-critical` (or `data-img-weight="critical"`) only for critical diagrams where full contrast is required for interpretation.
- Keep required alt text on all image embeds.

Optional validation command:

```bash
python scripts/validate_docs_integrity.py --format json --enforce-image-weight-markers
```

---

## Security and telemetry hygiene

- Do **not** log secrets, credentials, tokens, or sensitive command lines.
- Use allowlisted, minimal fields in metrics payloads.
- Keep JSONL entries as single-line UTF-8 records.

---

## Starter example

```bash
python examples/single-agent-loop/run.py
```

Walkthrough: [examples/single-agent-loop/README.md](examples/single-agent-loop/README.md)
