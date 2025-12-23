# SPDX-License-Identifier: Apache-2.0
"""
Sample agent implementation used for boot health checks.
"""

from app.agents.base_agent import BaseAgent
from runtime import metrics


class SampleAgent(BaseAgent):
    def info(self) -> dict:
        return {"id": "sample-agent", "element": "Wood"}

    def run(self, input=None) -> dict:
        metrics.log(event_type="sample_agent_run", payload={"input": input or {}}, level="INFO")
        return {"status": "ok", "input": input}

    def mutate(self, src: str) -> str:
        return src + "/*mutated*/"

    def score(self, output: dict) -> float:
        return 1.0


__all__ = ["SampleAgent"]
