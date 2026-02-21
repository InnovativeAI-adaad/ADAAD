# Agent Contract v1 (Draft)

Required module constants:
- `AGENT_ID: str`
- `VERSION: semver`
- `CAPABILITIES: list[str]`
- `GOAL_SCHEMA: dict`
- `OUTPUT_SCHEMA: dict`
- `SPAWN_POLICY: dict`

Required callables:
- `get_agent_manifest() -> dict`
- `run_goal(goal) -> dict`

Required compatibility API signatures:
- `def info() -> dict:`
- `def run(input=None) -> dict:`
- `def mutate(src: str) -> str:`
- `def score(output: dict) -> float:`

Validation entry points:
- `adaad.core.agent_contract.validate_agent_module`
- `adaad.core.agent_contract.validate_agent_contracts`
- `runtime.preflight.validate_agent_contract_preflight`


Legacy bridge validation:
- `validate_agent_contracts(..., include_legacy_bridge=True)` checks selected legacy class-based agents for API signature compliance while migration is in progress.
