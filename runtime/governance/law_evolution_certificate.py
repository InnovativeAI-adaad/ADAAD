# SPDX-License-Identifier: Apache-2.0
"""Law Evolution Certificate (LEC) primitives for Founders Law v2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runtime.governance.founders_law_v2 import LawManifest
from runtime.governance.foundation.hashing import sha256_digest


@dataclass(frozen=True)
class LawEvolutionCertificate:
    certificate_id: str
    old_manifest_digest: str
    new_manifest_digest: str
    old_epoch_id: str
    new_epoch_id: str
    reason: str
    replay_safe: bool
    signer_key_id: str
    signer_algo: str
    signature: str


def _canonical_payload(cert: LawEvolutionCertificate) -> dict[str, Any]:
    payload = asdict(cert)
    payload.pop("signature", None)
    return payload


def certificate_digest(cert: LawEvolutionCertificate) -> str:
    return sha256_digest(_canonical_payload(cert))


def law_surface_digest(manifest: LawManifest) -> str:
    """Digest only constitutional law surface (excluding node/epoch/signature envelope)."""
    payload = {
        "law_version": manifest.law_version,
        "trust_mode": manifest.trust_mode,
        "modules": [
            {
                "id": module.id,
                "version": module.version,
                "kind": module.kind,
                "scope": module.scope,
                "applies_to": module.applies_to,
                "trust_modes": module.trust_modes,
                "lifecycle_states": module.lifecycle_states,
                "requires": [{"id": ref.id, "version_range": ref.version_range} for ref in module.requires],
                "conflicts": [{"id": ref.id, "version_range": ref.version_range} for ref in module.conflicts],
                "supersedes": [{"id": ref.id, "version_range": ref.version_range} for ref in module.supersedes],
                "rules": [
                    {
                        "rule_id": rule.rule_id,
                        "name": rule.name,
                        "description": rule.description,
                        "severity": rule.severity,
                        "applies_to": rule.applies_to,
                    }
                    for rule in module.rules
                ],
            }
            for module in manifest.modules
        ],
    }
    return sha256_digest(payload)


def issue_certificate(
    old_manifest: LawManifest,
    new_manifest: LawManifest,
    *,
    reason: str,
    signer_key_id: str,
    signer_algo: str = "ed25519",
    replay_safe: bool = False,
    signature: str = "",
) -> LawEvolutionCertificate:
    old_digest = law_surface_digest(old_manifest)
    new_digest = law_surface_digest(new_manifest)
    preimage = (
        f"{old_digest}|{new_digest}|{old_manifest.epoch_id}|{new_manifest.epoch_id}|"
        f"{reason}|{replay_safe}|{signer_key_id}|{signer_algo}"
    ).encode("utf-8")
    certificate_id = sha256_digest(preimage)
    return LawEvolutionCertificate(
        certificate_id=certificate_id,
        old_manifest_digest=old_digest,
        new_manifest_digest=new_digest,
        old_epoch_id=old_manifest.epoch_id,
        new_epoch_id=new_manifest.epoch_id,
        reason=reason,
        replay_safe=replay_safe,
        signer_key_id=signer_key_id,
        signer_algo=signer_algo,
        signature=signature,
    )


def validate_certificate(
    cert: LawEvolutionCertificate,
    *,
    old_manifest: LawManifest,
    new_manifest: LawManifest,
    require_replay_safe: bool = False,
) -> list[str]:
    errors: list[str] = []

    if cert.old_manifest_digest != law_surface_digest(old_manifest):
        errors.append("old manifest digest does not match certificate")
    if cert.new_manifest_digest != law_surface_digest(new_manifest):
        errors.append("new manifest digest does not match certificate")

    if cert.old_epoch_id != old_manifest.epoch_id:
        errors.append("old epoch id mismatch")
    if cert.new_epoch_id != new_manifest.epoch_id:
        errors.append("new epoch id mismatch")

    if cert.old_manifest_digest == cert.new_manifest_digest:
        errors.append("certificate must reference a manifest change")

    expected_id = issue_certificate(
        old_manifest,
        new_manifest,
        reason=cert.reason,
        signer_key_id=cert.signer_key_id,
        signer_algo=cert.signer_algo,
        replay_safe=cert.replay_safe,
        signature=cert.signature,
    ).certificate_id
    if cert.certificate_id != expected_id:
        errors.append("certificate id is not deterministic for payload")

    if require_replay_safe and not cert.replay_safe:
        errors.append("certificate is not replay-safe")

    if not cert.signer_key_id.strip():
        errors.append("missing signer key id")
    if not cert.signature.strip():
        errors.append("missing certificate signature")

    return errors


def validate_law_transition(
    *,
    old_manifest: LawManifest | None,
    new_manifest: LawManifest | None,
    certificate: LawEvolutionCertificate | None,
    require_replay_safe: bool = False,
) -> list[str]:
    """Validate whether a law transition is legitimate and certificate-backed."""
    if old_manifest is None and new_manifest is None:
        return []

    if old_manifest is None or new_manifest is None:
        return ["both old and new manifests are required for law transition validation"]

    changed = law_surface_digest(old_manifest) != law_surface_digest(new_manifest) or old_manifest.trust_mode != new_manifest.trust_mode
    if changed and certificate is None:
        return ["law transition requires a law evolution certificate"]

    if certificate is None:
        return []

    return validate_certificate(
        certificate,
        old_manifest=old_manifest,
        new_manifest=new_manifest,
        require_replay_safe=require_replay_safe,
    )


def epoch_law_transition_metadata(
    manifest: LawManifest | None,
    certificate: LawEvolutionCertificate | None = None,
) -> dict[str, str]:
    """Metadata anchors for epoch records."""
    if manifest is None:
        return {}
    payload = {
        "law_surface_digest": law_surface_digest(manifest),
        "law_trust_mode": manifest.trust_mode,
    }
    if certificate is not None:
        payload["law_evolution_certificate_id"] = certificate.certificate_id
    return payload


__all__ = [
    "LawEvolutionCertificate",
    "certificate_digest",
    "epoch_law_transition_metadata",
    "issue_certificate",
    "law_surface_digest",
    "validate_certificate",
    "validate_law_transition",
]
