# SPDX-License-Identifier: Apache-2.0
"""Deterministic orchestration kernel for mutation cycles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.agents.discovery import iter_agent_dirs
from app.agents.mutation_engine import MutationEngine
from app.agents.mutation_request import MutationRequest
from app.agents.mutation_strategies import load_skill_weights, select_strategy
from app.mutation_executor import MutationExecutor
from runtime import ROOT_DIR
from runtime.evolution.mutation_fitness_evaluator import MutationFitnessEvaluator
from runtime.governance.policy_validator import PolicyValidator
from security import cryovant


class EvolutionKernel:
    """Single entrypoint for mutation-cycle orchestration."""

    def __init__(
        self,
        *,
        agents_root: Path,
        lineage_dir: Path,
        compatibility_adapter: Any | None = None,
        mutation_executor: MutationExecutor | None = None,
    ) -> None:
        self.agents_root = Path(agents_root)
        self.lineage_dir = Path(lineage_dir)
        self.compatibility_adapter = compatibility_adapter
        self.mutation_executor = mutation_executor or MutationExecutor(self.agents_root)
        self.policy_validator = PolicyValidator()
        self.fitness_evaluator = MutationFitnessEvaluator()
        self.policy_path = ROOT_DIR / "governance" / "governance_policy_v1.json"

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def load_agent(self, agent_path: str | Path) -> Dict[str, Any]:
        """Load deterministic agent bundle from app/agents metadata files."""
        root = Path(agent_path)
        payload = {
            "agent_path": str(root),
            "meta": self._read_json(root / "meta.json"),
            "dna": self._read_json(root / "dna.json"),
            "certificate": self._read_json(root / "certificate.json"),
        }
        payload["agent_id"] = str(payload["meta"].get("name") or root.name)
        return payload

    def propose_mutation(self, agent: Mapping[str, Any]) -> Dict[str, Any]:
        """Select and score a mutation strategy deterministically."""
        agent_path = Path(str(agent.get("agent_path") or ""))
        state_path = ROOT_DIR / "data" / "mutation_engine_state.json"
        metrics_path = ROOT_DIR / "data" / "metrics.jsonl"

        skill_weights = load_skill_weights(state_path)
        intent, ops = select_strategy(agent_path, skill_weights=skill_weights)

        request = MutationRequest(
            agent_id=str(agent.get("agent_id") or agent_path.name),
            generation_ts="",
            intent=intent,
            ops=ops,
            signature="",
            nonce="",
        )
        engine = MutationEngine(metrics_path=metrics_path, state_path=state_path)
        selected_request, scores = engine.select([request])

        return {
            "request": (selected_request or request).to_dict(),
            "scores": scores,
            "selected_intent": (selected_request.intent if selected_request else intent),
        }

    def validate_mutation(self, policy: Mapping[str, Any] | str | None, mutation: Mapping[str, Any]) -> Dict[str, Any]:
        """Validate mutation against governance policy artifact and policy parser."""
        raw_policy: Dict[str, Any]
        if isinstance(policy, Mapping):
            raw_policy = dict(policy)
        elif isinstance(policy, str) and policy.strip():
            raw_policy = json.loads(policy)
        else:
            raw_policy = self._read_json(self.policy_path)

        validator_result = self.policy_validator.validate(json.dumps(raw_policy, sort_keys=True))
        mutation_has_ops = bool(mutation.get("ops") or mutation.get("targets"))
        return {
            "valid": validator_result.valid and mutation_has_ops,
            "policy_valid": validator_result.valid,
            "mutation_has_ops": mutation_has_ops,
            "errors": list(validator_result.errors),
            "policy_path": str(self.policy_path),
        }

    def execute_in_sandbox(self, agent: Mapping[str, Any], mutation: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute mutation through current MutationExecutor sandbox workflow."""
        request_payload = mutation.get("request") if "request" in mutation else mutation
        request = MutationRequest.from_dict(dict(request_payload))
        if not request.agent_id:
            request.agent_id = str(agent.get("agent_id") or "")
        return self.mutation_executor.execute(request)

    def evaluate_fitness(self, agent: Mapping[str, Any], goal_graph: Mapping[str, Any]) -> Dict[str, Any]:
        """Evaluate deterministic fitness using kernel evaluator module."""
        return self.fitness_evaluator.evaluate(
            str(agent.get("agent_id") or ""),
            dict(goal_graph.get("mutation") or {}),
            goal_graph,
        )

    def sign_certificate(self, agent: Mapping[str, Any]) -> Dict[str, Any]:
        """Sign/evolve agent certificate using cryovant lineage signer."""
        agent_id = str(agent.get("agent_id") or "")
        agent_path = Path(str(agent.get("agent_path") or ""))
        return cryovant.evolve_certificate(agent_id, agent_path, self.lineage_dir, {})

    def run_cycle(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Run one mutation cycle, preferring compatibility adapter when explicitly selected."""
        if self.compatibility_adapter is not None and agent_id is None:
            return self.compatibility_adapter.run_cycle(agent_id)

        available_agents = list(iter_agent_dirs(self.agents_root))
        if not available_agents:
            raise RuntimeError("no_agents_available")

        available_agents_by_resolved = {agent_path.resolve(): agent_path for agent_path in available_agents}

        if agent_id is None:
            target_agent_path = available_agents[0]
        else:
            candidate_path = (self.agents_root / agent_id.replace(":", "/")).resolve()
            target_agent_path = available_agents_by_resolved.get(candidate_path)
            if target_agent_path is None:
                raise RuntimeError(f"agent_not_found:{agent_id}")

        agent = self.load_agent(target_agent_path)
        mutation = self.propose_mutation(agent)
        validation = self.validate_mutation(None, mutation.get("request") or mutation)
        if not validation.get("valid"):
            return {
                "status": "rejected",
                "reason": "policy_invalid",
                "agent_id": agent.get("agent_id"),
                **validation,
            }

        execution_result = self.execute_in_sandbox(agent, mutation)
        fitness_result = self.evaluate_fitness(agent, mutation)
        certificate_result = self.sign_certificate(agent)
        return {
            **execution_result,
            "agent_id": agent.get("agent_id"),
            "fitness": fitness_result,
            "certificate": certificate_result,
            "kernel_path": True,
        }


__all__ = ["EvolutionKernel"]
