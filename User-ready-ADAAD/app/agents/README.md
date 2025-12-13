# app/agents

Element: WOOD (contracts) + WATER (certification boundary)

Agents are first-class artifacts. They must be certifiable, auditable, and lineage-tracked.

## Directory layout

app/agents/
  base_agent.py
  builtin/
    <agent_name>/
      meta.json
      dna.json
      certificate.json
      agent.py
  lineage/
    <offspring_id>/
      meta.json
      dna.json
      certificate.json
      agent.py

## Required metadata

meta.json
  - name
  - role (planner|executor|critic|verifier|explainer)
  - authority (read_only|propose|commit)
  - version
  - created_at

dna.json
  - immutable design intent
  - constraints and tool permissions
  - evaluation targets

certificate.json
  - issuer (Cryovant)
  - lineage hash
  - parent id
  - certification timestamp
  - policy hash reference

## Contracts

Python interface must conform to BaseAgent:
  - act() for executors
  - plan() optional for planners
  - verify() optional for verifiers

Authority boundaries:
  read_only: cannot write or promote
  propose: can produce diffs and proposals only
  commit: can request promotion, but promotion still requires Cryovant and policy allow

## Cryovant gating

At boot, the orchestrator must call Cryovant.gate_cycle() on agent directories.
If certification fails:
  - mutation engines must remain disabled
  - promotion must not occur

## Lineage rules

1) Offspring must be written only into app/agents/lineage/.
2) Offspring must not overwrite builtin agents.
3) Every offspring must include complete meta/dna/certificate.
4) Lineage is append-only. Deletions require explicit governance action and audit trail.
