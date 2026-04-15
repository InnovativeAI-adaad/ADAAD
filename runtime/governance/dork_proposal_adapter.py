# SPDX-License-Identifier: Apache-2.0
"""DORK proposal execution adapter through governance-approved interfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from runtime import ROOT_DIR
from runtime.governance.foundation.determinism import default_provider
from runtime.governance.gate import GovernanceGate
from runtime.mcp.proposal_queue import append_proposal
from runtime.mcp.proposal_validator import ProposalValidationError, validate_proposal
from runtime.preflight import migrate_runtime_profile_lock

_RUNTIME_PROFILE_LOCK_PATH = ROOT_DIR / "governance_runtime_profile.lock.json"
_DEFAULT_GROK_CREDENTIAL_PATH = ROOT_DIR / "security" / "ledger" / "credentials" / "grok_pat.vault"


@dataclass(frozen=True)
class DorkProposalResult:
    proposal_id: str
    gate_decision_id: str
    governance_decision: str
    queued_event_type: str
    queue_hash: str


@dataclass(frozen=True)
class DorkProposalPreflightError(Exception):
    code: str
    status_code: int = 423

    def __str__(self) -> str:  # pragma: no cover - defensive
        return self.code


def _load_grok_profile_state() -> dict[str, Any]:
    try:
        profile_payload = json.loads(_RUNTIME_PROFILE_LOCK_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DorkProposalPreflightError("grok_profile_missing") from exc
    except json.JSONDecodeError as exc:
        raise DorkProposalPreflightError("grok_profile_invalid") from exc

    migrated = migrate_runtime_profile_lock(profile_payload)
    agents = migrated["profile"].get("agents")
    if not isinstance(agents, dict):
        raise DorkProposalPreflightError("grok_profile_missing")
    profile = agents.get("grok-integrator")
    if not isinstance(profile, dict):
        raise DorkProposalPreflightError("grok_profile_missing")
    return profile


def _resolve_grok_credentials_path(grok_profile: dict[str, Any]) -> Path:
    metadata = grok_profile.get("metadata")
    metadata_path = ""
    if isinstance(metadata, dict):
        metadata_path = str(metadata.get("credentials_path", "")).strip()
    env_path = os.getenv("GIP01_VAULT_FILE", "").strip()
    chosen = metadata_path or env_path
    return (ROOT_DIR / chosen) if chosen else _DEFAULT_GROK_CREDENTIAL_PATH


def _ensure_grok_profile_prerequisites() -> None:
    profile = _load_grok_profile_state()
    if not bool(profile.get("enabled")):
        raise DorkProposalPreflightError("grok_disabled")

    credential_path = _resolve_grok_credentials_path(profile)
    if not credential_path.exists():
        raise DorkProposalPreflightError("grok_credentials_missing")
    token = credential_path.read_text(encoding="utf-8").strip()
    if not token:
        raise DorkProposalPreflightError("grok_credentials_missing")


def execute_dork_proposal(
    *,
    proposal_payload: dict[str, Any],
    trust_mode: str,
    actor: str,
    gate: GovernanceGate | None = None,
) -> DorkProposalResult:
    """Execute proposal preflight + queue using concrete governance surfaces."""
    _ensure_grok_profile_prerequisites()
    governance_gate = gate or GovernanceGate()
    proposal_id = default_provider().next_id(label="dork-proposal", length=12)

    gate_decision = governance_gate.approve_mutation(
        mutation_id=proposal_id,
        trust_mode=str(trust_mode or "standard"),
        mutation_payload={"proposal": dict(proposal_payload)},
        mutation_context={"surface": "dork_api", "actor": str(actor or "dork")},
        human_override=False,
    )
    if not gate_decision.approved:
        raise PermissionError(
            "governance_gate_blocked:"
            + ",".join(gate_decision.reason_codes or ["unknown_reason"])
        )

    request, _validation = validate_proposal(dict(proposal_payload))
    queued = append_proposal(proposal_id=proposal_id, request=request)
    return DorkProposalResult(
        proposal_id=proposal_id,
        gate_decision_id=gate_decision.decision_id,
        governance_decision=gate_decision.decision,
        queued_event_type=str(queued.get("event_type", "")),
        queue_hash=str(queued.get("hash", "")),
    )


__all__ = [
    "DorkProposalResult",
    "ProposalValidationError",
    "execute_dork_proposal",
]
