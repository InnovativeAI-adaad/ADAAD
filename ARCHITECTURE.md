# SPDX-License-Identifier: Apache-2.0
# ADAAD System Architecture

## CLI Data Flow (Phase 123)

The `adaad` CLI provides a unified entry point for interacting with the governance runtime.

```mermaid
graph TD
    User([User]) --> CLI[scripts/adaad shim]
    CLI --> Main[adaad.__main__.py]
    Main --> Demo[cmd_demo: dry-run CEL]
    Main --> Inspect[cmd_inspect_ledger: ledger summary]
    Main --> Propose[cmd_propose: CEL Step 4 injection]
    
    Demo --> CEL[Constitutional Evolution Loop]
    Propose --> CEL
    Inspect --> Ledger[(evolution_ledger.jsonl)]
```

## Governance Invariants

- **CLI-SANDBOX-0**: All CLI-initiated mutations default to sandbox-only execution.
- **CLI-GATE-0**: Proposals via CLI must traverse the same 16-step CEL pipeline as autonomous proposals.

## Module Map

| Layer | Module | Responsibility |
|:---|:---|:---|
| Interface | `adaad.__main__.py` | Command routing, argument parsing, sandbox guarding. |
| Interface | `scripts/adaad` | POSIX shim for local execution. |
| Runtime | `app/main.py` | Full autonomous loop orchestrator. |
| Core | `adaad/core/` | Governance-critical primitives. |
| Evolution | `runtime/evolution/` | 16-step CEL implementation. |
| Ledger | `security/ledger/` | Tamper-evident hash-chained records. |

## Governance Intelligence Layer (DORK)

The Governance Intelligence Layer, powered by the **DORK (Developer Operator Runtime Kernel) Engine**, is the institutional consciousness of ADAAD. It ensures that the system's autonomous evolution remains constitutionally bounded and epistemologically aligned with human intent.

**Core Components:**
- **GovernanceGate:** The final arbiter for all mutation approvals.
- **Constitutional Lineage Engine (CLE):** Traces the evolution of the system's legal framework.
- **Multi-Dimensional Fitness Surface (MDFS):** Unified real-time health and fitness topography.
- **Emergent Behavior Sentinel (EBS):** Detects un-governed novelty in module interactions.

**Strategic Document:** [DORK_STRATEGIC_PLAN.md](docs/governance/DORK_STRATEGIC_PLAN.md)
