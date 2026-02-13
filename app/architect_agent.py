# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Architect agent responsible for scanning the workspace.
"""

from pathlib import Path
from typing import Dict, List

from app.agents.base_agent import validate_agents
from app.agents.discovery import iter_agent_dirs, resolve_agent_id
from app.agents.invariants import check_invariants
from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime import metrics
from runtime import ROOT_DIR
from runtime.timeutils import now_iso
from runtime.tools.mutation_fs import file_hash

ELEMENT_ID = "Wood"


class ArchitectAgent:
    """
    Performs workspace scans and validates agent inventory.
    """

    def __init__(self, agents_root: Path):
        self.agents_root = agents_root

    def scan(self) -> Dict[str, List[str]]:
        valid, errors = validate_agents(self.agents_root)
        invariant_errors = check_invariants(self.agents_root)
        if invariant_errors:
            errors.extend(invariant_errors)
        result = {"valid": valid and not invariant_errors, "errors": errors}
        level = "INFO" if result["valid"] else "ERROR"
        metrics.log(event_type="architect_scan", payload=result, level=level)
        return result

    def propose_mutations(self) -> List[MutationRequest]:
        """
        Generate actionable mutation proposals using concrete strategies.
        """
        from app.agents.mutation_strategies import load_skill_weights, select_strategy

        proposals: List[MutationRequest] = []
        skill_weights = load_skill_weights(ROOT_DIR / "data" / "mutation_engine_state.json")
        for agent_dir in iter_agent_dirs(self.agents_root):
            agent_id = resolve_agent_id(agent_dir, self.agents_root)
            strategy_name, ops = select_strategy(agent_dir, skill_weights=skill_weights)
            if not ops:
                continue
            dna_path = agent_dir / "dna.json"
            targets = [
                MutationTarget(
                    agent_id=agent_id,
                    path="dna.json",
                    target_type="dna",
                    ops=ops,
                    hash_preimage=file_hash(dna_path),
                )
            ]
            proposals.append(
                MutationRequest(
                    agent_id=agent_id,
                    generation_ts=now_iso(),
                    intent=strategy_name,
                    ops=ops,
                    targets=targets,
                    signature="cryovant-dev-architect",
                    nonce=f"arch-{agent_id}-{now_iso()}",
                    authority_level="governor-review",
                )
            )
        metrics.log(
            event_type="architect_proposals",
            payload={"count": len(proposals), "strategies": [p.intent for p in proposals]},
            level="INFO",
        )
        return proposals
