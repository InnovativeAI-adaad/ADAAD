# SPDX-License-Identifier: Apache-2.0

"""
Minimal test agent for validating mutation pipeline.
"""

from app.agents.base_agent import BaseAgent
from runtime import metrics


class TestSubjectAgent(BaseAgent):
    """Simple agent designed to be mutated safely."""

    def info(self) -> dict:
        return {
            "id": "test-subject",
            "element": "Fire",
            "purpose": "Mutation testing",
        }

    def run(self, input=None) -> dict:
        metrics.log(
            event_type="test_subject_run",
            payload={"input": input or {}},
            level="INFO",
        )
        return {"status": "ok", "echo": input}

    def mutate(self, src: str) -> str:
        return src + "\n# mutated"

    def score(self, output: dict) -> float:
        return 1.0 if output.get("status") == "ok" else 0.0


__all__ = ["TestSubjectAgent"]
