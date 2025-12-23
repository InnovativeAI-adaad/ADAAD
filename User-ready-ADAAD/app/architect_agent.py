"""
Architect agent responsible for scanning the workspace.
"""

from pathlib import Path
from typing import Dict, List

from app.agents.base_agent import validate_agents
from runtime import metrics

ELEMENT_ID = "Wood"


class ArchitectAgent:
    """
    Performs workspace scans and validates agent inventory.
    """

    def __init__(self, agents_root: Path):
        self.agents_root = agents_root

    def scan(self) -> Dict[str, List[str]]:
        valid, errors = validate_agents(self.agents_root)
        result = {"valid": valid, "errors": errors}
        level = "INFO" if valid else "ERROR"
        metrics.log(event_type="architect_scan", payload=result, level=level)
        return result
