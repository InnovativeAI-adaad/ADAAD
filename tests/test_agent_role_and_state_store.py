# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from adaad.agents.base_agent import BaseAgent, assign_task_by_role
from runtime.agent_state import AgentStateStore


class DemoAgent(BaseAgent):
    def info(self) -> dict:
        return {"role": self.role}

    def run(self, input=None) -> dict:
        return {"input": input}

    def mutate(self, src: str) -> str:
        return src

    def score(self, output: dict) -> float:
        return float(output.get("score", 0.0))


def test_base_agent_persistent_fields_defaults() -> None:
    agent = DemoAgent()
    assert agent.role == "builder"
    assert isinstance(agent.skill_vector, dict)
    assert agent.score_history == []
    assert agent.lineage_id == "demoagent"
    assert agent.survival_rank == 0.0
    assert agent.memory_ref is None


def test_assign_task_by_role_uses_role_compatibility_and_trend() -> None:
    builder = DemoAgent(role="builder", score_history=[0.2, 0.5, 0.9])
    tester = DemoAgent(role="tester", score_history=[0.8, 0.75, 0.7])
    selected = assign_task_by_role([builder, tester], {"build": 0.8, "test": 0.2})
    assert selected is builder


def test_agent_state_store_snapshot_and_recent_history(tmp_path: Path) -> None:
    store = AgentStateStore(tmp_path / "runtime" / "agent_state")

    store.write_snapshot("agent-a", {"role": "builder", "survival_rank": 0.75}, now_ts=10.0)
    store.write_snapshot("agent-a", {"role": "optimizer", "survival_rank": 0.8}, now_ts=11.0)
    latest = store.read_snapshot("agent-a")

    assert latest is not None
    assert latest["snapshot"]["role"] == "optimizer"

    store.write_execution_event("agent-a", "task_complete", {"task": "build"}, score=0.6, now_ts=12.0)
    store.write_execution_event("agent-a", "task_complete", {"task": "optimize"}, score=0.9, now_ts=13.0)
    recent = store.read_recent_execution_history("agent-a", limit=1)

    assert len(recent) == 1
    assert recent[0]["payload"]["task"] == "optimize"
