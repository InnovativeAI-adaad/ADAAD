# SPDX-License-Identifier: Apache-2.0
"""
Mutation executor: verifies requests, applies ops, runs post-checks.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple

from app.agents.discovery import agent_path_from_id
from app.agents.mutation_request import MutationRequest
from runtime import ROOT_DIR
from runtime.timeutils import now_iso
from runtime import metrics
from runtime.fitness_v2 import score_mutation_survival
from security import cryovant
from security.ledger import journal
from runtime.tools.mutation_guard import apply_dna_mutation
from runtime.tools.code_mutation_guard import apply_code_mutation, extract_targets as extract_code_targets
from runtime.tools.mutation_tx import MutationTargetError, MutationTransaction

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
        Run pytest with timeout and capture results.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-x", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ROOT_DIR),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "Test execution timeout (>30s)"
        except Exception as exc:  # pragma: no cover
            return False, f"Test execution error: {exc}"

        if result.returncode in {0, 5}:
            return True, result.stdout

        stderr_lines = result.stderr.splitlines()
        failure_summary = "\n".join(stderr_lines[-10:])
        return False, f"Tests failed:\n{failure_summary}"

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

        if not request.ops and not request.targets:
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
        if request.targets:
            target_types = [target.target_type for target in request.targets]
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_planned",
                payload={"mutation_id": mutation_id, "targets": len(request.targets), "target_types": target_types, "ts": now_iso()},
            )
            metrics.log(
                event_type="mutation_planned",
                payload={
                    "agent": request.agent_id,
                    "mutation_id": mutation_id,
                    "targets": len(request.targets),
                    "target_types": target_types,
                    "path": str(agent_dir),
                },
                level="INFO",
                element_id=ELEMENT_ID,
            )

            mutation_records = []
            try:
                with MutationTransaction(request.agent_id, agents_root=self.agents_root) as tx:
                    for target in request.targets:
                        mutation_records.append(tx.apply(target))
                    tx.verify()
                    tests_ok, test_output = self._run_tests()
                    if tests_ok:
                        tx.commit()
                    else:
                        tx.rollback()
            except MutationTargetError as exc:
                metrics.log(
                    event_type="mutation_rejected_preflight",
                    payload={"agent": request.agent_id, "reason": str(exc)},
                    level="ERROR",
                    element_id=ELEMENT_ID,
                )
                journal.write_entry(
                    agent_id=request.agent_id,
                    action="mutation_failed",
                    payload={"mutation_id": mutation_id, "error": str(exc), "ts": now_iso()},
                )
                return {"status": "failed", "tests_ok": False, "error": str(exc), "mutation_id": mutation_id}

            payload = {
                "agent": request.agent_id,
                "targets": len(request.targets),
                "target_types": target_types,
                "tests_ok": tests_ok,
                "mutation_id": mutation_id,
                "lineage": [
                    {"path": str(record.path), "checksum": record.checksum, "applied": record.applied, "skipped": record.skipped}
                    for record in mutation_records
                ],
            }
        else:
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
            dna_path = agent_dir / "dna.json"
            backup_bytes = dna_path.read_bytes() if dna_path.exists() else b"{}"

            dna_ops: list[Dict[str, Any]] = []
            code_ops: list[Dict[str, Any]] = []
            for op in request.ops:
                if not isinstance(op, dict):
                    dna_ops.append(op)
                    continue
                target_value = op.get("file") or op.get("target") or op.get("filepath")
                if isinstance(target_value, str) and target_value.strip():
                    if Path(target_value).name == "dna.json":
                        dna_ops.append(op)
                    else:
                        code_ops.append(op)
                else:
                    dna_ops.append(op)

            code_targets = extract_code_targets(code_ops) if code_ops else []
            code_backups = {path: (path.read_bytes() if path.exists() else None) for path in code_targets}

            apply_result: Dict[str, Any] = {}
            if dna_ops:
                apply_result["dna"] = apply_dna_mutation(agent_fs_id, dna_ops)
            if code_ops:
                apply_result["code"] = apply_code_mutation(code_ops)
                if apply_result["code"].get("status") == "failed":
                    metrics.log(
                        event_type="mutation_failed",
                        payload={"agent": request.agent_id, "mutation_id": mutation_id, "error": "code_mutation_failed"},
                        level="ERROR",
                        element_id=ELEMENT_ID,
                    )
                    journal.write_entry(
                        agent_id=request.agent_id,
                        action="mutation_failed",
                        payload={"mutation_id": mutation_id, "error": "code_mutation_failed", "ts": now_iso()},
                    )
                    return {"status": "failed", "tests_ok": False, "error": "code_mutation_failed", "mutation_id": mutation_id}

            tests_ok, test_output = self._run_tests()
            payload = {
                "agent": request.agent_id,
                "ops": len(request.ops),
                "tests_ok": tests_ok,
                "mutation_id": mutation_id,
                "lineage": apply_result,
            }
            if not tests_ok:
                try:
                    dna_path.write_bytes(backup_bytes)
                except Exception:
                    pass
                for path, original in code_backups.items():
                    try:
                        if original is None:
                            if path.exists():
                                path.unlink()
                        else:
                            path.write_bytes(original)
                    except Exception:
                        continue
        survival_payload = {
            **payload,
            "verified": ok,
            "ops": request.ops,
        }
        survival_score = score_mutation_survival(
            request.agent_id,
            request.intent or "default",
            survival_payload,
        )
        if tests_ok:
            metrics.log(event_type="mutation_executed", payload=payload, level="INFO", element_id=ELEMENT_ID)
            metrics.log(
                event_type="mutation_score",
                payload={"agent": request.agent_id, "strategy_id": request.intent or "default", "score": survival_score},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_promoted",
                payload={"mutation_id": mutation_id, "lineage": payload["lineage"], "ts": now_iso()},
            )
            return {"status": "executed", "tests_ok": True, "mutation_id": mutation_id}

        metrics.log(event_type="mutation_failed", payload={**payload, "error": test_output}, level="ERROR", element_id=ELEMENT_ID)
        metrics.log(
            event_type="mutation_score",
            payload={"agent": request.agent_id, "strategy_id": request.intent or "default", "score": survival_score},
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
