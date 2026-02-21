# SPDX-License-Identifier: Apache-2.0
"""Explicit mutation lifecycle transition enforcement."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping

from runtime import ROOT_DIR, metrics
from runtime.governance.foundation import canonical_json, sha256_prefixed_digest
from runtime.timeutils import now_iso
from runtime.tools.rollback_certificate import issue_rollback_certificate
from security import cryovant
from security.ledger import journal

ELEMENT_ID = "Fire"
TRUST_MODES = {"dev", "prod"}
LIFECYCLE_STATE_DIR = ROOT_DIR / "runtime" / "lifecycle_states"


class LifecycleTransitionError(RuntimeError):
    """Raised when a lifecycle transition is not explicitly allowed."""


@dataclass
class MutationLifecycleContext:
    mutation_id: str
    agent_id: str
    epoch_id: str
    signature: str = ""
    trust_mode: str = "dev"
    cert_refs: Mapping[str, Any] = field(default_factory=dict)
    fitness_score: float | None = None
    fitness_threshold: float = 0.5
    founders_law_check: Callable[[], tuple[bool, list[str]]] | None = None
    founders_law_result: tuple[bool, list[str]] | None = None
    stage_timestamps: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    current_state: str = "proposed"
    state_dir: Path = LIFECYCLE_STATE_DIR

    def __post_init__(self) -> None:
        self.stage_timestamps.setdefault("proposed", now_iso())

    def state_path(self) -> Path:
        return Path(self.state_dir) / f"{self.mutation_id}.lifecycle.json"

    def persist(self) -> None:
        path = self.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mutation_id": self.mutation_id,
            "agent_id": self.agent_id,
            "epoch_id": self.epoch_id,
            "signature": self.signature,
            "trust_mode": self.trust_mode,
            "cert_refs": dict(self.cert_refs),
            "fitness_score": self.fitness_score,
            "fitness_threshold": self.fitness_threshold,
            "stage_timestamps": dict(self.stage_timestamps),
            "metadata": dict(self.metadata),
            "current_state": self.current_state,
            "ts": now_iso(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def cleanup_state(self) -> None:
        path = self.state_path()
        if path.exists():
            path.unlink()

    @classmethod
    def restore(cls, mutation_id: str, state_dir: Path = LIFECYCLE_STATE_DIR) -> MutationLifecycleContext | None:
        path = Path(state_dir) / f"{mutation_id}.lifecycle.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            mutation_id=str(raw.get("mutation_id") or mutation_id),
            agent_id=str(raw.get("agent_id") or "unknown"),
            epoch_id=str(raw.get("epoch_id") or "unknown"),
            signature=str(raw.get("signature") or ""),
            trust_mode=str(raw.get("trust_mode") or "dev"),
            cert_refs=dict(raw.get("cert_refs") or {}),
            fitness_score=raw.get("fitness_score"),
            fitness_threshold=float(raw.get("fitness_threshold", 0.5)),
            stage_timestamps=dict(raw.get("stage_timestamps") or {}),
            metadata=dict(raw.get("metadata") or {}),
            current_state=str(raw.get("current_state") or "proposed"),
            state_dir=Path(state_dir),
        )


def _signature_valid(signature: str, trust_mode: str) -> tuple[bool, str]:
    if cryovant.verify_signature(signature):
        return True, "verified"
    if trust_mode == "dev" and cryovant.dev_signature_allowed(signature):
        return True, "dev_signature"
    return False, "invalid_signature"


def _founders_law_ok(context: MutationLifecycleContext) -> tuple[bool, list[str]]:
    if context.founders_law_result is not None:
        return context.founders_law_result
    if context.founders_law_check is None:
        context.founders_law_result = (True, [])
        return context.founders_law_result
    context.founders_law_result = context.founders_law_check()
    return context.founders_law_result


def _transition_payload(*, from_state: str, to_state: str, context: MutationLifecycleContext, guard_report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mutation_id": context.mutation_id,
        "agent_id": context.agent_id,
        "epoch_id": context.epoch_id,
        "from_state": from_state,
        "to_state": to_state,
        "trust_mode": context.trust_mode,
        "guard_report": guard_report,
        "cert_refs": dict(context.cert_refs),
        "fitness_score": context.fitness_score,
        "fitness_threshold": context.fitness_threshold,
        "stage_timestamps": dict(context.stage_timestamps),
        "metadata": dict(context.metadata),
        "ts": now_iso(),
    }


def _record_success(payload: Dict[str, Any]) -> None:
    journal.write_entry(agent_id=str(payload["agent_id"]), action="mutation_lifecycle_transition", payload=payload)
    journal.append_tx(tx_type="mutation_lifecycle_transition", payload=payload)
    metrics.log(event_type="mutation_lifecycle_transition", payload=payload, level="INFO", element_id=ELEMENT_ID)


def _record_rejection(payload: Dict[str, Any]) -> None:
    journal.write_entry(agent_id=str(payload["agent_id"]), action="mutation_lifecycle_rejected", payload=payload)
    journal.append_tx(tx_type="mutation_lifecycle_rejected", payload=payload)
    metrics.log(event_type="mutation_lifecycle_rejected", payload=payload, level="ERROR", element_id=ELEMENT_ID)


TRANSITIONS: Dict[tuple[str, str], Dict[str, Any]] = {
    ("proposed", "staged"): {"require_cert": False, "require_fitness": False, "allowed_trust_modes": TRUST_MODES},
    ("staged", "certified"): {"require_cert": True, "require_fitness": False, "allowed_trust_modes": TRUST_MODES},
    ("certified", "executing"): {"require_cert": True, "require_fitness": True, "allowed_trust_modes": TRUST_MODES},
    ("executing", "completed"): {"require_cert": True, "require_fitness": False, "allowed_trust_modes": TRUST_MODES},
    ("completed", "pruned"): {"require_cert": False, "require_fitness": False, "allowed_trust_modes": TRUST_MODES},
}


def declared_predecessors(state: str) -> Iterable[str]:
    return [from_state for (from_state, to_state), _meta in TRANSITIONS.items() if to_state == state]


def transition(current_state: str, next_state: str, context: MutationLifecycleContext) -> str:
    rule = TRANSITIONS.get((current_state, next_state))
    if rule is None:
        payload = _transition_payload(
            from_state=current_state,
            to_state=next_state,
            context=context,
            guard_report={"ok": False, "reason": "undeclared_transition", "declared_predecessors": sorted(declared_predecessors(next_state))},
        )
        _record_rejection(payload)
        context.persist()
        raise LifecycleTransitionError(f"undeclared_transition:{current_state}->{next_state}")

    trust_mode = (context.trust_mode or os.getenv("ADAAD_TRUST_MODE", "dev")).strip().lower()
    signature_ok, signature_method = _signature_valid(context.signature or "", trust_mode)
    founders_ok, founders_failures = _founders_law_ok(context)
    cert_ok = True if not rule["require_cert"] else bool(context.cert_refs)
    fitness_ok = True
    if rule["require_fitness"]:
        fitness_ok = context.fitness_score is not None and context.fitness_score >= context.fitness_threshold

    guard_report = {
        "ok": signature_ok and founders_ok and cert_ok and fitness_ok and trust_mode in rule["allowed_trust_modes"],
        "cryovant_signature_validity": {"ok": signature_ok, "method": signature_method},
        "founders_law_invariant_gate": {"ok": founders_ok, "failures": founders_failures},
        "fitness_threshold_gate": {
            "ok": fitness_ok,
            "required": bool(rule["require_fitness"]),
            "score": context.fitness_score,
            "threshold": context.fitness_threshold,
        },
        "trust_mode_compatibility_gate": {
            "ok": trust_mode in rule["allowed_trust_modes"],
            "trust_mode": trust_mode,
            "allowed": sorted(rule["allowed_trust_modes"]),
        },
        "cert_reference_gate": {"ok": cert_ok, "required": bool(rule["require_cert"])},
    }
    context.trust_mode = trust_mode

    if not guard_report["ok"]:
        payload = _transition_payload(from_state=current_state, to_state=next_state, context=context, guard_report=guard_report)
        _record_rejection(payload)
        context.persist()
        raise LifecycleTransitionError(f"guard_failed:{current_state}->{next_state}")

    context.stage_timestamps[next_state] = now_iso()
    context.current_state = next_state
    payload = _transition_payload(from_state=current_state, to_state=next_state, context=context, guard_report=guard_report)
    _record_success(payload)
    if next_state in {"completed", "pruned"}:
        context.cleanup_state()
    else:
        context.persist()
    return next_state


def rollback(context: MutationLifecycleContext, to_state: str, reason: str = "manual_rollback") -> str:
    valid_rollbacks = {
        "executing": "certified",
        "certified": "staged",
        "staged": "proposed",
    }
    expected = valid_rollbacks.get(context.current_state)
    if expected is None:
        raise LifecycleTransitionError(f"cannot_rollback_from:{context.current_state}")
    if to_state != expected:
        raise LifecycleTransitionError(f"invalid_rollback_target:{to_state}")

    from_state = context.current_state
    prior_snapshot = {
        "current_state": context.current_state,
        "stage_timestamps": dict(context.stage_timestamps),
        "cert_refs": dict(context.cert_refs),
    }
    prior_state_digest = sha256_prefixed_digest(canonical_json(prior_snapshot))
    context.current_state = to_state
    context.stage_timestamps[to_state] = now_iso()
    payload = _transition_payload(
        from_state=from_state,
        to_state=to_state,
        context=context,
        guard_report={"ok": True, "rollback": True, "reason": reason},
    )
    _record_success(payload)
    context.persist()

    restored_snapshot = {
        "current_state": context.current_state,
        "stage_timestamps": dict(context.stage_timestamps),
        "cert_refs": dict(context.cert_refs),
    }
    restored_state_digest = sha256_prefixed_digest(canonical_json(restored_snapshot))
    forward_certificate_digest = str(
        context.cert_refs.get("forward_certificate_digest")
        or context.cert_refs.get("certificate_digest")
        or context.cert_refs.get("bundle_id")
        or ""
    )
    cert = issue_rollback_certificate(
        mutation_id=context.mutation_id,
        epoch_id=context.epoch_id,
        prior_state_digest=prior_state_digest,
        restored_state_digest=restored_state_digest,
        trigger_reason=reason,
        actor_class="MutationLifecycle",
        completeness_checks={
            "rollback_target_matches_expected": to_state == expected,
            "state_persisted": context.state_path().exists(),
            "state_changed": from_state != to_state,
        },
        agent_id=context.agent_id,
        forward_certificate_digest=forward_certificate_digest,
    )
    context.metadata["last_rollback_certificate_digest"] = cert.digest
    if isinstance(context.cert_refs, dict):
        context.cert_refs["rollback_certificate_digest"] = cert.digest
        if forward_certificate_digest:
            context.cert_refs["forward_certificate_digest"] = forward_certificate_digest
    context.persist()
    return to_state


def retry_transition(
    context: MutationLifecycleContext,
    next_state: str,
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_error: LifecycleTransitionError | None = None
    for attempt in range(max_attempts):
        try:
            return transition(context.current_state, next_state, context)
        except LifecycleTransitionError as exc:
            last_error = exc
            if attempt == max_attempts - 1:
                break
            sleep_fn(float(2**attempt))
    raise last_error or LifecycleTransitionError(f"transition_failed:{context.current_state}->{next_state}")


__all__ = [
    "MutationLifecycleContext",
    "LifecycleTransitionError",
    "LIFECYCLE_STATE_DIR",
    "TRANSITIONS",
    "declared_predecessors",
    "transition",
    "rollback",
    "retry_transition",
]
