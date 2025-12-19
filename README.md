# ADAAD He65

![InnovativeAI LLC](ui/assets/innovativeai_llc.svg)

Autonomous AI-driven App Dev (ADAAD) – He65 user-ready build.

Core identities:

- Nexari – orchestrator/runtime core
- Arbion – architect / structural growth
- Pyronex – mutation / evolution engine
- Cryovant – registry, lineage, and trust
- Aponi – dashboard and control surface

## Governance spine (HE65)

- **Cryovant** is the single ledger writer, enforcing canonical paths (`security/ledger/events.jsonl`), keys (`security/keys/`), schema versions, and deterministic lineage hashes derived from `meta.json`, `dna.json`, and `certificate.json`.
- **Promotion** is audited: every ticket attempt emits a `promotion.accepted` or `promotion.rejected` event with ticket metadata, reasons, and test summary hashes.
- **Boot** is gated: active agents are validated; zero-agent scenarios enter safe boot (mutation disabled) and are ledgered as `gate_cycle.rejected`.
- **Doctor** is the ship gate (`scripts/he65_doctor.py`): deterministic, local-only, validating structure, imports, logging hygiene, schema versions, ledger writability, and tests. Exit code `0` = ship, `1` = block.

## Ship-ready defaults

- Ledger schema version: `1.0`; lineage metadata schema version: `1.0` (see `security/schema_versions.py`).
- Agent templates ship with versioned lineage metadata in `app/agents/agent_template/`.
- Safe boot is deterministic and mutation stays disabled until agents validate.

---

InnovativeAI LLC  
ADAAD Autonomous Systems  
© 2025 InnovativeAI LLC. All rights reserved.
