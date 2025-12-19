from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class AgentMetadata:
    name: str
    version: str
    lineage_hash: str


class BaseAgent:
    def info(self) -> Dict[str, object]:
        raise NotImplementedError

    def run(self, input=None) -> Dict[str, object]:
        raise NotImplementedError
