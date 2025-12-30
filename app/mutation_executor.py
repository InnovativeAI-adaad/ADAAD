# SPDX-License-Identifier: Apache-2.0
"""
Mutation executor: verifies requests, applies ops, runs post-checks.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple

from app.agents.discovery import agent_path_from_id
from app.agents.mutation_request import MutationRequest
from runtime.timeutils import now_iso
from runtime import metrics
from security import cryovant
from security.ledger import journal
from runtime.tools.mutation_guard import apply_dna_mutation

ELEMENT_ID = "Fire"


class MutationExecutor:
    def __init__(self, agents_root: Path) -> None:
        self.agents_root = agents_root

    def _verify(self, request: MutationRequest) -> Tuple[bool, str]:
        sig = request.signature or ""
        if cryovant.verify_signature(sig):
            return True, "verified"
        if cryovant.dev_signature_allowed(sig):
            return True, "dev_signature"
        return False, "invalid_signature"

    def _run_tests(self) -> Tuple[bool, str]:
        """
        Run pytest to validate a mutation. Keep it simple: fail fast on errors.
        """
        try:
            result = subprocess.run(["python", "-m", "pytest"], capture_output=True, text=True, check=False)
            if result.returncode != 0:
                return False, result.stderr or result.stdout
            return True, result.stdout
        except Exception as exc:  # pragma: no cover
            return False, str(exc)

    def execute(self, request: MutationRequest) -> Dict[str, Any]:
        ok, reason = self._verify(request)
        if not ok:
            metrics.log(
                event_type="mutation_rejected",
                payload={"agent": request.agent_id, "reason": reason},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return {"status": "rejected", "reason": reason}

        mutation_id = str(uuid.uuid4())

        if not request.ops:
            metrics.log(
                event_type="mutation_noop",
                payload={"agent": request.agent_id, "mutation_id": mutation_id, "reason": "no_ops"},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_noop",
                payload={"mutation_id": mutation_id, "ts": now_iso()},
            )
            return {"status": "skipped", "reason": "no_ops", "mutation_id": mutation_id}

        agent_dir = agent_path_from_id(request.agent_id, self.agents_root)
        journal.write_entry(
            agent_id=request.agent_id,
            action="mutation_planned",
            payload={"mutation_id": mutation_id, "ops": len(request.ops), "ts": now_iso()},
        )
        metrics.log(
            event_type="mutation_planned",
            payload={"agent": request.agent_id, "mutation_id": mutation_id, "ops": len(request.ops), "path": str(agent_dir)},
            level="INFO",
            element_id=ELEMENT_ID,
        )

        agent_fs_id = request.agent_id.replace(":", "/")
        agent_dir = agent_path_from_id(request.agent_id, self.agents_root)
        dna_path = agent_dir / "dna.json"
        backup_bytes = dna_path.read_bytes() if dna_path.exists() else b"{}"

        apply_result = apply_dna_mutation(agent_fs_id, request.ops)

        tests_ok, test_output = self._run_tests()
        payload = {
            "agent": request.agent_id,
            "ops": len(request.ops),
            "tests_ok": tests_ok,
            "mutation_id": mutation_id,
            "lineage": apply_result,
        }
        if tests_ok:
            metrics.log(event_type="mutation_executed", payload=payload, level="INFO", element_id=ELEMENT_ID)
            metrics.log(
                event_type="mutation_score",
                payload={"agent": request.agent_id, "strategy_id": request.intent or "default", "score": 1.0},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_promoted",
                payload={"mutation_id": mutation_id, "lineage": apply_result, "ts": now_iso()},
            )
            return {"status": "executed", "tests_ok": True, "mutation_id": mutation_id}

        # rollback dna
        try:
            dna_path.write_bytes(backup_bytes)
        except Exception:
            pass

        metrics.log(event_type="mutation_failed", payload={**payload, "error": test_output}, level="ERROR", element_id=ELEMENT_ID)
        metrics.log(
            event_type="mutation_score",
            payload={"agent": request.agent_id, "strategy_id": request.intent or "default", "score": 0.0},
            level="INFO",
            element_id=ELEMENT_ID,
        )
        journal.write_entry(
            agent_id=request.agent_id,
            action="mutation_failed",
            payload={"mutation_id": mutation_id, "error": test_output, "ts": now_iso()},
        )
        return {"status": "failed", "tests_ok": False, "error": test_output, "mutation_id": mutation_id}


__all__ = ["MutationExecutor"]
