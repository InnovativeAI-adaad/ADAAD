# SPDX-License-Identifier: Apache-2.0
"""
Mutation executor: verifies requests, applies ops, runs post-checks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Sequence

from app.agents.discovery import agent_path_from_id
from app.agents.mutation_request import MutationRequest
from runtime import ROOT_DIR, metrics
from runtime.analysis.impact_predictor import ImpactPredictor
from runtime.evolution import EvolutionRuntime
from runtime.evolution.entropy_discipline import deterministic_context, deterministic_id
from runtime.evolution.promotion_events import create_promotion_event
from runtime.evolution.promotion_policy import PromotionPolicyEngine
from runtime.evolution.promotion_state_machine import PromotionState, require_transition
from runtime.evolution.entropy_detector import detect_entropy_metadata, observed_entropy_from_telemetry
from runtime.evolution.entropy_policy import EntropyPolicy, enforce_entropy_policy
from runtime.fitness_pipeline import FitnessPipeline, RiskEvaluator, TestOutcomeEvaluator
from runtime.fitness_v2 import score_mutation_survival
from runtime.governance.foundation import RuntimeDeterminismProvider, default_provider, require_replay_safe_provider
from runtime.invariants import verify_all
from runtime.manifest.generator import generate_manifest, write_manifest
from runtime.mutation_lifecycle import LifecycleTransitionError, MutationLifecycleContext, transition as lifecycle_transition
from runtime.test_sandbox import TestSandbox, TestSandboxResult, TestSandboxStatus
from runtime.sandbox.executor import HardenedSandboxExecutor
from runtime.timeutils import now_iso
from runtime.tools.code_mutation_guard import apply_code_mutation, extract_targets as extract_code_targets
from runtime.tools.mutation_guard import apply_dna_mutation
from runtime.tools.mutation_tx import MutationTargetError, MutationTransaction
from security.ledger import journal

ELEMENT_ID = "Fire"

def _is_valid_replay_seed(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 16:
        return False
    if not all(ch in "0123456789abcdefABCDEF" for ch in value):
        return False
    return value.lower() != "0" * 16


class MutationExecutor:
    def __init__(
        self,
        agents_root: Path,
        evolution_runtime: EvolutionRuntime | None = None,
        *,
        provider: RuntimeDeterminismProvider | None = None,
    ) -> None:
        self.agents_root = agents_root
        self.evolution_runtime = evolution_runtime or EvolutionRuntime()
        self.governor = self.evolution_runtime.governor
        self.provider = provider or default_provider()
        self.test_sandbox = TestSandbox(root_dir=ROOT_DIR, timeout_s=60)
        self.hardened_sandbox = HardenedSandboxExecutor(self.test_sandbox, provider=self.provider)
        self.impact_predictor = ImpactPredictor(agents_root)
        self.fitness_pipeline = FitnessPipeline([TestOutcomeEvaluator(), RiskEvaluator()])
        self.promotion_policy = PromotionPolicyEngine({
            "schema_version": "1.0",
            "policy_id": "default",
            "minimum_score": 0.5,
            "blocked_conditions": [],
            "risk_ceiling": 0.8,
        })
        self.entropy_policy = EntropyPolicy(
            policy_id="default-entropy-v1",
            per_mutation_ceiling_bits=128,
            per_epoch_ceiling_bits=4096,
        )

    def _run_tests(
        self,
        args: Sequence[str] | None = None,
        retries: int = 1,
        *,
        mutation_id: str = "",
        epoch_id: str = "",
        replay_seed: str = "0000000000000001",
    ) -> TestSandboxResult:
        """Run project tests through hardened sandbox wrapper and return sandbox metadata."""
        return self.hardened_sandbox.run_tests_with_retry(
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            replay_seed=replay_seed,
            args=args,
            retries=retries,
        )

    def _normalize_test_result(self, result: TestSandboxResult | tuple[bool, str]) -> TestSandboxResult:
        """Normalize legacy tuple mocks into TestSandboxResult."""
        if isinstance(result, tuple):
            ok, output = result
            return TestSandboxResult(
                ok=ok,
                output=output,
                returncode=0 if ok else 1,
                duration_s=0.0,
                timeout_s=self.test_sandbox.timeout_s,
                sandbox_dir="",
                status=TestSandboxStatus.OK if ok else TestSandboxStatus.FAILED,
            )
        return result

    def _build_mutation_id(self, request: MutationRequest, epoch_id: str) -> str:
        require_replay_safe_provider(
            self.provider,
            replay_mode=self.evolution_runtime.replay_mode.value,
            recovery_tier=self.governor.recovery_tier.value,
        )
        if deterministic_context(
            replay_mode=self.evolution_runtime.replay_mode.value,
            recovery_tier=self.governor.recovery_tier.value,
        ):
            return deterministic_id(
                epoch_id=epoch_id,
                bundle_id=request.bundle_id or request.intent or "mutation",
                agent_id=request.agent_id,
                label="mutation",
            )
        return self.provider.next_id(
            label=f"mutation:{epoch_id}:{request.agent_id}:{request.intent or 'mutation'}",
            length=32,
        )


    @staticmethod
    def _risk_tier(risk_score: float) -> str:
        score = float(risk_score)
        if score >= 0.85:
            return "CRITICAL"
        if score >= 0.65:
            return "HIGH"
        if score >= 0.35:
            return "MEDIUM"
        return "LOW"

    def _last_promotion_event_hash(self, mutation_id: str, epoch_id: str) -> str | None:
        try:
            events = self.governor.ledger.read_epoch(epoch_id)
        except Exception:
            return None
        latest: str | None = None
        for entry in events:
            if entry.get("type") != "PromotionEvent":
                continue
            payload = entry.get("payload") or {}
            if str(payload.get("mutation_id") or "") != mutation_id:
                continue
            event_hash = payload.get("event_hash")
            if isinstance(event_hash, str):
                latest = event_hash
        return latest

    def _emit_promotion_event(
        self,
        *,
        mutation_id: str,
        epoch_id: str,
        from_state: PromotionState,
        to_state: PromotionState,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        require_transition(from_state, to_state)
        event = create_promotion_event(
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            from_state=from_state,
            to_state=to_state,
            actor_type="SYSTEM",
            actor_id="mutation_executor",
            policy_version=self.promotion_policy.policy_version,
            payload=payload,
            prev_event_hash=self._last_promotion_event_hash(mutation_id, epoch_id),
            provider=self.provider,
            replay_mode=self.evolution_runtime.replay_mode.value,
            recovery_tier=self.governor.recovery_tier.value,
        )
        self.governor.ledger.append_event("PromotionEvent", event)
        return event

    def execute(self, request: MutationRequest) -> Dict[str, Any]:
        epoch_id = self.evolution_runtime.epoch_manager.get_active().epoch_id
        mutation_id = self._build_mutation_id(request, epoch_id)
        trust_mode = os.getenv("ADAAD_TRUST_MODE", "dev").strip().lower()
        lifecycle_dry_run = os.getenv("ADAAD_LIFECYCLE_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}
        lifecycle = MutationLifecycleContext(
            mutation_id=mutation_id,
            agent_id=request.agent_id,
            epoch_id=epoch_id,
            signature=request.signature or "",
            trust_mode=trust_mode,
            founders_law_check=verify_all,
            metadata={"intent": request.intent or "", "bundle_id": request.bundle_id or ""},
        )
        lifecycle_state = lifecycle.current_state

        try:
            lifecycle_state = lifecycle_transition(lifecycle_state, "staged", lifecycle)
        except LifecycleTransitionError as exc:
            return {"status": "rejected", "reason": str(exc), "mutation_id": mutation_id, "epoch_id": epoch_id}

        impact = self.impact_predictor.predict(request)
        metrics.log(
            event_type="mutation_impact_prediction",
            payload={
                "agent": request.agent_id,
                "mutation_id": mutation_id,
                "risk_score": impact.risk_score,
                "affected_agents": sorted(impact.affected_agents),
                "affected_files": sorted(impact.affected_files),
                "recommendations": impact.recommendations,
            },
            level="WARNING" if impact.risk_score > 0.8 else "INFO",
            element_id=ELEMENT_ID,
        )

        request.epoch_id = epoch_id
        if self.evolution_runtime.fail_closed:
            return {"status": "blocked", "reason": "fail_closed", "epoch_id": epoch_id, "replay_status": "failed"}

        decision = self.governor.validate_bundle(request, epoch_id=epoch_id)
        if not decision.accepted:
            metrics.log(
                event_type="mutation_rejected_governance",
                payload={"agent": request.agent_id, "reason": decision.reason, "epoch_id": epoch_id, "replay_status": decision.replay_status},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return {
                "status": "rejected",
                "reason": decision.reason,
                "epoch_id": epoch_id,
                "replay_status": decision.replay_status,
                "evolution": {"epoch_id": epoch_id, "certificate": decision.certificate or {}, "replay": {"passed": decision.replay_status == "ok"}},
            }

        replay_seed = (decision.certificate or {}).get("replay_seed")
        if replay_seed is not None and not _is_valid_replay_seed(replay_seed):
            metrics.log(
                event_type="sandbox_validation_failed",
                payload={"agent": request.agent_id, "reason": "invalid_replay_seed", "epoch_id": epoch_id},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            return {
                "status": "rejected",
                "reason": "invalid_replay_seed",
                "epoch_id": epoch_id,
                "replay_status": "failed",
                "evolution": {"epoch_id": epoch_id, "certificate": decision.certificate or {}, "replay": {"passed": False}},
            }

        if not request.ops and not request.targets:
            metrics.log(
                event_type="mutation_noop",
                payload={"agent": request.agent_id, "mutation_id": mutation_id, "reason": "no_ops", "epoch_id": epoch_id},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_noop",
                payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "ts": now_iso()},
            )
            self.evolution_runtime.after_mutation_cycle({"status": "skipped"})
            return {"status": "skipped", "reason": "no_ops", "mutation_id": mutation_id, "epoch_id": epoch_id}

        lifecycle.cert_refs = decision.certificate or {}
        lifecycle.fitness_score = max(0.0, 1.0 - float(impact.risk_score))
        lifecycle.metadata["risk_score"] = impact.risk_score
        try:
            lifecycle_state = lifecycle_transition(lifecycle_state, "certified", lifecycle)
            lifecycle_state = lifecycle_transition(lifecycle_state, "executing", lifecycle)
        except LifecycleTransitionError as exc:
            return {"status": "rejected", "reason": str(exc), "mutation_id": mutation_id, "epoch_id": epoch_id}

        if lifecycle_dry_run:
            try:
                lifecycle_state = lifecycle_transition(lifecycle_state, "completed", lifecycle)
            except LifecycleTransitionError as exc:
                return {"status": "rejected", "reason": str(exc), "mutation_id": mutation_id, "epoch_id": epoch_id}
            metrics.log(
                event_type="mutation_lifecycle_dry_run",
                payload={"agent": request.agent_id, "mutation_id": mutation_id, "epoch_id": epoch_id, "final_state": lifecycle_state},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_lifecycle_dry_run",
                payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "final_state": lifecycle_state, "ts": now_iso()},
            )
            return {"status": "dry_run", "mutation_id": mutation_id, "epoch_id": epoch_id, "final_state": lifecycle_state, "simulated": True}

        agent_dir = agent_path_from_id(request.agent_id, self.agents_root)
        if request.targets:
            target_types = [target.target_type for target in request.targets]
            journal.write_entry(
                agent_id=request.agent_id,
                action="mutation_planned",
                payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "targets": len(request.targets), "target_types": target_types, "ts": now_iso()},
            )
            metrics.log(
                event_type="mutation_planned",
                payload={"agent": request.agent_id, "mutation_id": mutation_id, "targets": len(request.targets), "target_types": target_types, "path": str(agent_dir)},
                level="INFO",
                element_id=ELEMENT_ID,
            )

            mutation_records = []
            try:
                with MutationTransaction(request.agent_id, agents_root=self.agents_root) as tx:
                    for target in request.targets:
                        mutation_records.append(tx.apply(target))
                    tx.verify()
                    test_result = self._normalize_test_result(self._run_tests(mutation_id=mutation_id, epoch_id=epoch_id, replay_seed=str(replay_seed or "0000000000000001")))
                    tests_ok = test_result.ok
                    test_output = test_result.output
                    if tests_ok:
                        tx.commit()
                    else:
                        tx.rollback()
            except MutationTargetError as exc:
                metrics.log(event_type="mutation_rejected_preflight", payload={"agent": request.agent_id, "reason": str(exc)}, level="ERROR", element_id=ELEMENT_ID)
                journal.write_entry(agent_id=request.agent_id, action="mutation_failed", payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "error": str(exc), "ts": now_iso()})
                self.evolution_runtime.after_mutation_cycle({"status": "skipped"})
                return {"status": "failed", "tests_ok": False, "error": str(exc), "mutation_id": mutation_id, "epoch_id": epoch_id}

            payload = {
                "agent": request.agent_id,
                "epoch_id": epoch_id,
                "certificate": decision.certificate or {},
                "targets": len(request.targets),
                "target_types": target_types,
                "tests_ok": tests_ok,
                "mutation_id": mutation_id,
                "test_result": {
                    "returncode": test_result.returncode,
                    "duration_s": round(test_result.duration_s, 4),
                    "timeout_s": test_result.timeout_s,
                    "status": test_result.status.value,
                    "retries": test_result.retries,
                    "stdout": test_result.stdout,
                    "stderr": test_result.stderr,
                    "memory_mb": test_result.memory_mb,
                },
                "lineage": [{"path": str(record.path), "checksum": record.checksum, "applied": record.applied, "skipped": record.skipped} for record in mutation_records],
            }
        else:
            journal.write_entry(agent_id=request.agent_id, action="mutation_planned", payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "ops": len(request.ops), "ts": now_iso()})
            metrics.log(event_type="mutation_planned", payload={"agent": request.agent_id, "mutation_id": mutation_id, "ops": len(request.ops), "path": str(agent_dir)}, level="INFO", element_id=ELEMENT_ID)

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
                    metrics.log(event_type="mutation_failed", payload={"agent": request.agent_id, "mutation_id": mutation_id, "error": "code_mutation_failed"}, level="ERROR", element_id=ELEMENT_ID)
                    journal.write_entry(agent_id=request.agent_id, action="mutation_failed", payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "error": "code_mutation_failed", "ts": now_iso()})
                    self.evolution_runtime.after_mutation_cycle({"status": "skipped"})
                    return {"status": "failed", "tests_ok": False, "error": "code_mutation_failed", "mutation_id": mutation_id, "epoch_id": epoch_id}

            test_result = self._normalize_test_result(self._run_tests(mutation_id=mutation_id, epoch_id=epoch_id, replay_seed=str(replay_seed or "0000000000000001")))
            evidence_hash = str(self.hardened_sandbox.last_evidence_hash or "")
            if evidence_hash:
                sandbox_evidence_payload = dict(self.hardened_sandbox.last_evidence_payload or {})
                sandbox_evidence_payload.update({"epoch_id": epoch_id, "mutation_id": mutation_id, "evidence_hash": evidence_hash})
                self.governor.ledger.append_event(
                    "SandboxEvidenceEvent",
                    sandbox_evidence_payload,
                )
            tests_ok = test_result.ok
            test_output = test_result.output
            payload = {
                "agent": request.agent_id,
                "epoch_id": epoch_id,
                "certificate": decision.certificate or {},
                "ops": len(request.ops),
                "tests_ok": tests_ok,
                "mutation_id": mutation_id,
                "test_result": {
                    "returncode": test_result.returncode,
                    "duration_s": round(test_result.duration_s, 4),
                    "timeout_s": test_result.timeout_s,
                    "status": test_result.status.value,
                    "retries": test_result.retries,
                    "stdout": test_result.stdout,
                    "stderr": test_result.stderr,
                    "memory_mb": test_result.memory_mb,
                },
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

        survival_payload = {**payload, "verified": True, "ops": request.ops, "impact_risk_score": impact.risk_score}
        survival_score = score_mutation_survival(request.agent_id, request.intent or "default", survival_payload)
        composed_fitness = self.fitness_pipeline.evaluate({"tests_ok": tests_ok, "impact_risk_score": impact.risk_score})

        entropy_metadata = detect_entropy_metadata(
            request,
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            sandbox_nondeterministic=bool(self.hardened_sandbox.policy.network_egress_allowlist),
        )
        telemetry_observed_bits, telemetry_sources = observed_entropy_from_telemetry(
            {
                "unseeded_rng_calls": int((self.hardened_sandbox.last_evidence_payload or {}).get("unseeded_rng_calls", 0) or 0),
                "wall_clock_reads": int((self.hardened_sandbox.last_evidence_payload or {}).get("wall_clock_reads", 0) or 0),
                "external_io_attempts": int((self.hardened_sandbox.last_evidence_payload or {}).get("external_io_attempts", 0) or 0),
            }
        )
        # Rationale: aggregate declared request entropy with observed runtime telemetry.
        # Invariants: epoch entropy is monotonically non-decreasing and policy remains fail-closed.
        prior_epoch_bits = int(getattr(self.evolution_runtime, "epoch_cumulative_entropy_bits", 0) or 0)
        mutation_total_bits = int(entropy_metadata.estimated_bits) + int(telemetry_observed_bits)
        epoch_entropy_bits = prior_epoch_bits + mutation_total_bits
        entropy_check = enforce_entropy_policy(
            policy=self.entropy_policy,
            mutation_bits=mutation_total_bits,
            declared_bits=entropy_metadata.estimated_bits,
            observed_bits=telemetry_observed_bits,
            epoch_bits=epoch_entropy_bits,
        )
        if not entropy_check["passed"]:
            metrics.log(
                event_type="mutation_rejected_entropy",
                payload={"agent": request.agent_id, "epoch_id": epoch_id, **entropy_check},
                level="ERROR",
                element_id=ELEMENT_ID,
            )
            if decision.certificate:
                self.governor.activate_certificate(epoch_id, decision.certificate.get("bundle_id", ""), False, "entropy_ceiling_exceeded")
            self.evolution_runtime.after_mutation_cycle({"status": "rejected", "mutation_id": mutation_id, "epoch_id": epoch_id, "reason": "entropy_ceiling_exceeded"})
            return {
                "status": "rejected",
                "tests_ok": bool(tests_ok),
                "reason": "entropy_ceiling_exceeded",
                "mutation_id": mutation_id,
                "epoch_id": epoch_id,
            }

        epoch_state = self.evolution_runtime.epoch_manager.add_entropy_bits(mutation_total_bits)
        self.evolution_runtime.epoch_cumulative_entropy_bits = int(epoch_state.cumulative_entropy_bits)

        promotion_mutation_data = {
            "score": float(survival_score),
            "entropy_bits": int(mutation_total_bits),
            "risk_tier": self._risk_tier(float(impact.risk_score)),
            "entropy_declared_bits": int(entropy_metadata.estimated_bits),
            "entropy_observed_bits": int(telemetry_observed_bits),
            "entropy_observed_sources": list(telemetry_sources),
            "risk_score": float(impact.risk_score),
            "tests_ok": bool(tests_ok),
        }
        # Rationale: canary simulation evidence must gate promotion without mutating runtime state.
        target_state = self.promotion_policy.evaluate_transition(PromotionState.CERTIFIED, promotion_mutation_data)
        canary_evidence = dict(promotion_mutation_data.get("simulation_verdict") or {})
        scored_event = self._emit_promotion_event(
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            from_state=PromotionState.CERTIFIED,
            to_state=target_state,
            payload=promotion_mutation_data,
        )

        if target_state == PromotionState.REJECTED:
            metrics.log(
                event_type="promotion_policy_rejected",
                payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "event_hash": scored_event.get("event_hash")},
                level="INFO",
                element_id=ELEMENT_ID,
            )
            if decision.certificate:
                self.governor.activate_certificate(epoch_id, decision.certificate.get("bundle_id", ""), False, "promotion_policy_rejected")
            self.evolution_runtime.after_mutation_cycle({"status": "rejected", "mutation_id": mutation_id, "epoch_id": epoch_id, "reason": "promotion_policy_rejected"})
            return {
                "status": "rejected",
                "tests_ok": bool(tests_ok),
                "reason": "promotion_policy_rejected",
                "mutation_id": mutation_id,
                "epoch_id": epoch_id,
            }

        if tests_ok:
            try:
                lifecycle_state = lifecycle_transition(lifecycle_state, "completed", lifecycle)
            except LifecycleTransitionError as exc:
                return {"status": "rejected", "reason": str(exc), "mutation_id": mutation_id, "epoch_id": epoch_id}
            lifecycle.current_state = lifecycle_state
            try:
                manifest = generate_manifest(lifecycle, "completed", risk_score=float(impact.risk_score))
                manifest_path = agent_dir / "manifests" / f"{mutation_id}.manifest.json"
                manifest_hash = write_manifest(manifest_path, manifest)
                journal.write_entry(
                    agent_id=request.agent_id,
                    action="mutation_manifest_written",
                    payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "manifest_path": str(manifest_path), "manifest_hash": manifest_hash, "ts": now_iso()},
                )
            except Exception as exc:
                return {"status": "rejected", "reason": f"manifest_failed:{exc}", "mutation_id": mutation_id, "epoch_id": epoch_id}

            metrics.log(event_type="mutation_executed", payload=payload, level="INFO", element_id=ELEMENT_ID)
            metrics.log(event_type="mutation_score", payload={"agent": request.agent_id, "strategy_id": request.intent or "default", "score": survival_score, "epoch_id": epoch_id}, level="INFO", element_id=ELEMENT_ID)
            metrics.log(event_type="mutation_fitness_pipeline", payload={"agent": request.agent_id, "epoch_id": epoch_id, **composed_fitness}, level="INFO", element_id=ELEMENT_ID)
            journal.write_entry(agent_id=request.agent_id, action="mutation_promoted", payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "lineage": payload["lineage"], "decision": "promoted", "evidence": {"lineage": payload["lineage"], "canary": canary_evidence}, "bundle_id": (decision.certificate or {}).get("bundle_id"), "manifest_hash": manifest_hash, "ts": now_iso()})
            if decision.certificate:
                self.governor.activate_certificate(epoch_id, decision.certificate.get("bundle_id", ""), True, "tests_passed")
            evolution_result = self.evolution_runtime.after_mutation_cycle({"status": "executed", "mutation_id": mutation_id, "epoch_id": epoch_id, "evolution": {"certificate": decision.certificate or {}}})
            return {
                "status": "executed",
                "tests_ok": True,
                "mutation_id": mutation_id,
                "epoch_id": epoch_id,
                "manifest_path": str(manifest_path),
                "manifest_hash": manifest_hash,
                "evolution": {
                    "epoch_id": epoch_id,
                    "bundle_id": (decision.certificate or {}).get("bundle_id"),
                    "epoch_digest": (decision.certificate or {}).get("epoch_digest") or (evolution_result.get("replay", {}) or {}).get("epoch_digest"),
                    "replay_passed": (evolution_result.get("replay", {}) or {}).get("replay_passed"),
                    "certificate": decision.certificate or {},
                    "replay": evolution_result.get("replay", {}),
                },
            }

        metrics.log(event_type="mutation_failed", payload={**payload, "error": test_output}, level="ERROR", element_id=ELEMENT_ID)
        metrics.log(event_type="mutation_score", payload={"agent": request.agent_id, "strategy_id": request.intent or "default", "score": survival_score, "epoch_id": epoch_id}, level="INFO", element_id=ELEMENT_ID)
        metrics.log(event_type="mutation_fitness_pipeline", payload={"agent": request.agent_id, "epoch_id": epoch_id, **composed_fitness}, level="INFO", element_id=ELEMENT_ID)
        journal.write_entry(agent_id=request.agent_id, action="mutation_failed", payload={"mutation_id": mutation_id, "epoch_id": epoch_id, "error": test_output, "canary": canary_evidence, "ts": now_iso()})
        if target_state != PromotionState.REJECTED:
            self._emit_promotion_event(
                mutation_id=mutation_id,
                epoch_id=epoch_id,
                from_state=target_state,
                to_state=PromotionState.REJECTED,
                payload={"reason": "tests_failed", "scored_event_hash": scored_event.get("event_hash")},
            )
        if decision.certificate:
            self.governor.activate_certificate(epoch_id, decision.certificate.get("bundle_id", ""), False, "tests_failed")
        self.evolution_runtime.after_mutation_cycle({"status": "failed", "mutation_id": mutation_id})
        return {"status": "failed", "tests_ok": False, "error": test_output, "mutation_id": mutation_id, "epoch_id": epoch_id}


__all__ = ["MutationExecutor"]
