# ADAAD Constitutional Framework v0.9.0

## Philosophy

ADAAD is not "autonomous AI." It is a **constitutionally governed runtime** that self-improves within explicit, auditable constraints.

Every mutation passes through constitutional evaluation. Every rule is versioned. Every decision is logged.

---

## The Three Tiers

### Tier 0: Production (Human-Only)
- **Paths**: `runtime/`, `security/`, `app/main.py`, orchestrator core
- **Mutations**: Never auto-executed
- **Review**: Required before merge
- **Rationale**: Core infrastructure must be human-verified

### Tier 1: Stable (Post-Approval Autonomous)
- **Paths**: `tests/`, `docs/`, most agents
- **Mutations**: Auto-execute, human reviews logs within 24h
- **Rollback**: Automatic if tests fail
- **Rationale**: Low-risk improvements with audit trail

### Tier 2: Sandbox (Fully Autonomous)
- **Paths**: `app/agents/test_subject/`
- **Mutations**: Fully autonomous
- **Constraints**: Cannot affect other tiers
- **Rationale**: Experimental evolution without blast radius

---

## Constitutional Rule Set (Versioned)

Canonical rule-count wording source:

- Human-readable: `docs/CONSTITUTION.md`
- Machine-readable: `governance/constitutional_rule_count.json` (derived from `runtime/governance/constitution.yaml`)

Rule count is versioned. Downstream docs should avoid hard-coded totals and instead reference the canonical sources above for the current count.

| Rule | Enabled | Severity | Purpose |
|------|---------|----------|---------|
| `single_file_scope` | ✅ | BLOCKING | Reduces complexity, memory usage |
| `ast_validity` | ✅ | BLOCKING | Prevents syntax errors |
| `import_smoke_test` | ✅ | WARNING | Catches dependency issues |
| `no_banned_tokens` | ✅ | BLOCKING | Security guardrails (no eval/exec) |
| `signature_required` | ✅ | BLOCKING | Cryptographic lineage |
| `max_complexity_delta` | ✅ | WARNING | Prevents code rot |
| `test_coverage_maintained` | ✅ | WARNING | Quality preservation |
| `max_mutation_rate` | ✅ | WARNING (SANDBOX: ADVISORY, PRODUCTION: BLOCKING) | Prevents runaway loops |
| `lineage_continuity` | ✅ | BLOCKING | Traceability |
| `resource_bounds` | ✅ | BLOCKING | Android/mobile safety; strict tiers require resource telemetry evidence |
| `entropy_budget_limit` | ✅ | WARNING (PRODUCTION: BLOCKING) | Prevents entropy budget overruns per mutation |
| `deployment_authority_tier` | ✅ | ADVISORY | Surfaces deployment authority context for governance audit trails |
| `revenue_credit_floor` | ✅ | ADVISORY | Records revenue-credit floor posture for economic governance telemetry |
| `reviewer_calibration` | ✅ | ADVISORY | Captures reviewer calibration context for audit evidence |
| `federation_dual_gate` | ✅ | BLOCKING | Federated mutation requires GovernanceGate approval in both source and destination repos |
| `federation_hmac_required` | ✅ | BLOCKING | Federation-enabled nodes must present valid HMAC key material at boot; absent key halts with fail-closed |


### Resource Telemetry Prerequisites (`resource_bounds`)

- `resource_measurements` should include deterministic usage keys such as `peak_rss_mb`, `cpu_seconds`/`cpu_time_seconds`, and `wall_seconds`/`wall_time_seconds`/`duration_s`.
- `platform_telemetry` may provide fallback evidence via `memory_mb` when direct measurements are incomplete.
- Governance policy can configure `resource_bounds_policy.strict_telemetry_tiers` (default: `PRODUCTION`) to enforce fail-closed behavior when both sources are missing.
- Non-strict tiers remain configurable fail-open, but emit a `resource_measurements_missing` warning event that explicitly records the fail-open rationale.

---

## Phase 5 Federation Extensions (v0.3.0 — incorporated)

v0.3.0 introduced two BLOCKING federation rules (federation_dual_gate, federation_hmac_required). These remain active in v0.7.0. Rule count is versioned and canonicalized by `runtime/governance/constitution.yaml` (`rules` array) and this Constitution; avoid hard-coding totals in downstream docs.

### `federation_dual_gate`
Every federated mutation must receive `GovernanceGate.approve_mutation()` approval in **both** the source repository and the destination repository before any cross-repo propagation may execute. A gate failure in either repo rejects the federated proposal unconditionally (fail-closed). Enforced in `runtime/governance/federation/mutation_broker.py`.

### `federation_hmac_required`
Any ADAAD node with `ADAAD_FEDERATION_ENABLED=true` must present valid HMAC key material (`ADAAD_FEDERATION_HMAC_KEY`) at boot. Key absent or below minimum length → `FederationKeyError` raised at startup; process does not proceed. Enforced in `runtime/governance/federation/key_registry.py`.

Both rules are replay-verified. Their enforcement is tested in `tests/test_federation_mutation_broker.py` and `tests/governance/federation/test_federation_hmac_key_validation.py` respectively.

---

## Severity Levels

- **BLOCKING**: Mutation is rejected. Logged as ERROR.
- **WARNING**: Mutation proceeds but logged as WARN.
- **ADVISORY**: Informational only. Logged as INFO.

Severity can be overridden per tier (e.g., `import_smoke_test` is WARNING for tier-1 but BLOCKING for tier-0).

---


## Severity Escalation Framework

Default severities are defined in policy and tier overrides. Runtime can **escalate only** (never de-escalate) a rule severity through deterministic directives:

- Environment variable `ADAAD_SEVERITY_ESCALATIONS` with JSON object (example: `{"reviewer_calibration":"blocking"}`)
- Deterministic envelope state key `severity_escalations`

Escalation ordering is `advisory -> warning -> blocking`. Any downgrade request is ignored fail-safe.

---

## Changing the Constitution

Constitutional rules can themselves evolve through governance:

1. Propose rule change as tier-0 mutation
2. Human review + approval required
3. Version bumped (`0.2.0` → next)
4. All subsequent mutations use new constitution
5. Change logged in Cryovant ledger

**The constitution is evolvable but not mutable without human oversight.**

---

## Resource Telemetry Data Flow

`resource_bounds` is enforced using deterministic envelope state populated at mutation-evaluation time:

1. Sandbox/runtime observations and Android `AndroidMonitor.snapshot()` signals are normalized with `runtime/governance/resource_accounting.py` helpers.
2. `platform_telemetry` feeds `_validate_resources` for memory pressure and CPU context, with battery/storage retained as mobile safety metadata.
3. Precedence is conservative: memory/CPU use max-merge across sources, battery/storage use min-merge, and policy limits remain fail-closed.

## Metrics & Observability

Every constitutional evaluation generates:
```json
{
  "event": "constitutional_evaluation",
  "payload": {
    "constitution_version": "0.7.0",
    "tier": "SANDBOX",
    "passed": true,
    "verdicts": [...],
    "blocking_failures": [],
    "warnings": []
  }
}
```

Query rejection patterns:
```python
from runtime.metrics_analysis import summarize_preflight_rejections
summary = summarize_preflight_rejections(limit=1000)
```



## Governance Review KPI SLOs

Governance review quality is tracked as deterministic telemetry (`governance_review_quality`) mirrored to metrics and Cryovant journal projections.

**SLO targets (rolling window):**
- **Review latency distribution**: p95 <= 86,400s (24h), p99 <= 172,800s (48h).
- **Reviewed within SLA**: >= 95% within `sla_seconds` (default 24h).
- **Reviewer participation concentration**: largest reviewer share <= 0.60 and HHI <= 0.40.
- **Review depth proxies**: average comment count >= 1.0 and override rate <= 20%.

Operations dashboards should consume `/metrics/review-quality` for aggregate computation + threshold monitoring.

---

## Future Extensions

- Further hardening and richer validator signals
- Multi-objective fitness integration
- Constitutional amendment proposals
- Community-contributed rules
- Cross-tier promotion pipelines

---

## Amendment Log

| Version | Phase | Rule Added | Severity |
|---------|-------|-----------|----------|
| v0.1.0 | 1 | Initial rule set (single_file_scope, ast_validity, no_banned_tokens, signature_required, lineage_continuity, resource_bounds) | BLOCKING |
| v0.2.0 | 3 | max_complexity_delta, test_coverage_maintained, max_mutation_rate, deployment_authority_tier, revenue_credit_floor, reviewer_calibration, governance_health_floor | WARNING / ADVISORY |
| v0.3.0 | 5 | federation_dual_gate, federation_hmac_required | BLOCKING |
| v0.4.0 | 7 | import_smoke_test | WARNING |
| v0.5.0 | 9 | soulbound_privacy_invariant | BLOCKING |
| v0.6.0 | 11-A | bandit_arm_integrity_invariant | BLOCKING |
| v0.7.0 | 13 | market_signal_integrity_invariant | BLOCKING |
| v0.7.0 | 23 | entropy_budget_limit | WARNING |
| v0.9.0 | 63 | phase63_ast_safe_scaffold, phase63_ast_import_scaffold, phase63_ast_complexity_scaffold, phase63_semantic_integrity_scaffold, phase63_exception_scope_scaffold | ADVISORY (GovernanceGateV2) |

Current rule count: **23 rules** — 9 BLOCKING, 5 WARNING, 9 ADVISORY (includes 5 GovernanceGateV2 scaffold rules introduced Phase 63).
Federation constraints (governed separately): 2 federation-BLOCKING.
**Canonical source:** `runtime/governance/constitution.yaml` (`rules` array). Do not hard-code this total in downstream docs; reference the YAML directly.
Policy hash: `71eb6499bc09d8b4…` (authoritative: `runtime/constitution.py → POLICY_HASH`)

**Version**: 0.9.0
**Last Updated**: 2026-03-24
**Active Phase**: 142 (v9.75.0 — INNOV-48 CSS complete · 231 Hard-class invariants · 48 innovations shipped)
**Next Review**: After 1000 mutations logged

**Canonical implementation specs:**
- Phase 5 (Federation): `docs/governance/ARCHITECT_SPEC_v3.1.0.md`
- Phase 6 (Roadmap Self-Amendment): `docs/governance/ARCHITECT_SPEC_v3.1.0.md`

---

## Boot-Critical Constitutional Artifacts

ADAAD boot is fail-closed for constitutional policy inputs. The following artifacts are required at boot:

- `runtime/governance/constitution.yaml`
- `governance/rule_applicability.yaml`

If either artifact is missing or invalid, constitutional initialization fails and runtime start is blocked (`constitution_boot_failed`).

`governance/rule_applicability.yaml` is therefore treated as constitution-adjacent policy, not optional metadata.


## LLM Proposal Agents

LLM agents (e.g. claude-proposal-agent) are governed identically to ArchitectAgent. authority_level is always governor-review. Tier-0 paths require explicit policy elevation by a human reviewer.
