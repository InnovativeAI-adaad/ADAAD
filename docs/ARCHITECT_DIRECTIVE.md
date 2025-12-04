# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Architect Agent Codex Directive

## Mandate
The Architect Agent enforces He65 structural compliance and design governance across the codebase.

## Responsibilities
- Detect missing ADAAD tags in the first five lines of source files.
- Flag deprecated or absolute imports that violate canonical structure.
- Sweep for stubbed modules and placeholders requiring implementation.
- Emit proposals to `reports/architect/architect_proposals_<timestamp>.json` with actionable remediations.

## Review Pipeline
1. Post-mutation, run `governance_sweep()` to aggregate policy violations.
2. Record proposals alongside mutation metrics to inform acceptance decisions.
3. Feed accepted proposals back into Dream Mode or developer action items for correction.

## Compliance Signals
- **Compliant:** No missing tags or invalid imports detected.
- **Warnings:** Non-canonical directories or imports surfaced for cleanup.
- **Critical:** Structural gaps that block Cryovant certification or orchestrator boot.
