# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Evolutionary Cycle Contract (ECC)

## Overview
The Evolutionary Cycle Contract defines the deterministic loop ADAAD follows in Phase II to unify Cryovant, Dream Mode, Architect Agent, and Beast Loop under a single governed sequence.

## Cycle Stages
1. **Initialize**
   - Earth/runtime validates directory invariants and health-first status.
   - Cryovant registry paths are created and permissions recommended.
2. **Mutate**
   - Dream Mode performs sandboxed mutation (function-level or file-level) with CPU and memory limits.
   - Mutation tasks are scheduled via Beast Loop when active, or invoked directly by the orchestrator.
3. **Certify**
   - Cryovant signs, records, and mirrors artifacts; mirror writes are size-checked to prevent silent failure.
   - Failed verification routes artifacts to `security/quarantine`.
4. **Score**
   - Mutation outcomes are evaluated for survival metrics and structural compliance.
   - Architect Agent governance sweep identifies policy violations or missing tags.
5. **Promote**
   - Successful offspring are registered through Cryovant; failing candidates remain quarantined for follow-up.
6. **Log**
   - Metrics emitted to `reports/metrics.jsonl` and lineage to `reports/cryovant.jsonl`.
   - Runtime logging appends notable events to `runtime/logs/events.jsonl`.

## Fitness Trajectory Inputs
- Survival rate across cycles
- Certification success rate
- Mutation complexity deltas
- Execution latency under sandbox constraints
- Structural compliance and tag coverage
- Ancestry depth recorded in Cryovant ledger

## Operator Notes
- Mutation is gated by health-first boot and Cryovant readiness.
- Quarantine paths must be monitored to prevent drift.
- Architect proposals in `reports/architect/` provide actionable remediation steps.
