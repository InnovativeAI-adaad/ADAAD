# ADAAD Constitutional Framework v0.2.0

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

## The Ten Rules

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
| `resource_bounds` | ✅ | BLOCKING | Android/mobile safety |

---

## Severity Levels

- **BLOCKING**: Mutation is rejected. Logged as ERROR.
- **WARNING**: Mutation proceeds but logged as WARN.
- **ADVISORY**: Informational only. Logged as INFO.

Severity can be overridden per tier (e.g., `import_smoke_test` is WARNING for tier-1 but BLOCKING for tier-0).

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

## Metrics & Observability

Every constitutional evaluation generates:
```json
{
  "event": "constitutional_evaluation",
  "payload": {
    "constitution_version": "0.2.0",
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

---

## Future Extensions

- Further hardening and richer validator signals
- Multi-objective fitness integration
- Constitutional amendment proposals
- Community-contributed rules
- Cross-tier promotion pipelines

---

**Version**: 0.2.0  
**Last Updated**: 2026-02-06  
**Next Review**: After 1000 mutations logged

---

## Boot-Critical Constitutional Artifacts

ADAAD boot is fail-closed for constitutional policy inputs. The following artifacts are required at boot:

- `runtime/governance/constitution.yaml`
- `governance/rule_applicability.yaml`

If either artifact is missing or invalid, constitutional initialization fails and runtime start is blocked (`constitution_boot_failed`).

`governance/rule_applicability.yaml` is therefore treated as constitution-adjacent policy, not optional metadata.
