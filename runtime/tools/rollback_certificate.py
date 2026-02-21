# SPDX-License-Identifier: Apache-2.0
"""Canonical rollback certificate helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.governance.foundation import canonical_json, sha256_prefixed_digest
from runtime.timeutils import now_iso
from security import cryovant
from security.ledger import journal

ROLLBACK_CERTIFICATE_VERSION = "rollback-certificate/v1"
ROLLBACK_CERTIFICATE_KEY_ID = "rollback-cert-v1"


@dataclass(frozen=True)
class RollbackCertificateEnvelope:
    certificate: dict[str, Any]
    digest: str


def _canonical_body(
    *,
    mutation_id: str,
    epoch_id: str,
    prior_state_digest: str,
    restored_state_digest: str,
    trigger_reason: str,
    actor_class: str,
    completeness_checks: Mapping[str, Any],
    forward_certificate_digest: str,
) -> dict[str, Any]:
    return {
        "schema": ROLLBACK_CERTIFICATE_VERSION,
        "mutation_id": mutation_id,
        "epoch_id": epoch_id,
        "prior_state_digest": prior_state_digest,
        "restored_state_digest": restored_state_digest,
        "trigger_reason": trigger_reason,
        "actor_class": actor_class,
        "completeness_checks": dict(completeness_checks),
        "forward_certificate_digest": forward_certificate_digest,
        "issued_at": now_iso(),
    }


def issue_rollback_certificate(
    *,
    mutation_id: str,
    epoch_id: str,
    prior_state_digest: str,
    restored_state_digest: str,
    trigger_reason: str,
    actor_class: str,
    completeness_checks: Mapping[str, Any],
    agent_id: str,
    forward_certificate_digest: str = "",
) -> RollbackCertificateEnvelope:
    body = _canonical_body(
        mutation_id=mutation_id,
        epoch_id=epoch_id,
        prior_state_digest=prior_state_digest,
        restored_state_digest=restored_state_digest,
        trigger_reason=trigger_reason,
        actor_class=actor_class,
        completeness_checks=completeness_checks,
        forward_certificate_digest=forward_certificate_digest,
    )
    digest = sha256_prefixed_digest(canonical_json(body))
    signature = cryovant.sign_hmac_digest(
        key_id=ROLLBACK_CERTIFICATE_KEY_ID,
        signed_digest=digest,
        specific_env_prefix="CRYOVANT_ROLLBACK_SIGNING_KEY_",
        generic_env_var="CRYOVANT_ROLLBACK_SIGNING_KEY",
        fallback_namespace="cryovant-rollback-certificate",
    )
    certificate = {
        **body,
        "rollback_certificate_digest": digest,
        "signature": {
            "algorithm": "hmac-sha256",
            "key_id": ROLLBACK_CERTIFICATE_KEY_ID,
            "signed_digest": digest,
            "value": signature,
        },
    }
    journal.write_entry(agent_id=agent_id, action="mutation_rollback_certificate", payload=certificate)
    journal.append_tx(tx_type="mutation_rollback_certificate", payload=certificate)
    if forward_certificate_digest:
        link_payload: dict[str, object] = {
            "mutation_id": mutation_id,
            "epoch_id": epoch_id,
            "forward_certificate_digest": forward_certificate_digest,
            "rollback_certificate_digest": digest,
            "ts": now_iso(),
        }
        journal.write_entry(agent_id=agent_id, action="mutation_certificate_link", payload=link_payload)
        journal.append_tx(tx_type="mutation_certificate_link", payload=link_payload)
    return RollbackCertificateEnvelope(certificate=certificate, digest=digest)


def verify_rollback_certificate(certificate: Mapping[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    required = [
        "schema",
        "mutation_id",
        "epoch_id",
        "prior_state_digest",
        "restored_state_digest",
        "trigger_reason",
        "actor_class",
        "completeness_checks",
        "forward_certificate_digest",
        "issued_at",
        "rollback_certificate_digest",
        "signature",
    ]
    for field in required:
        if field not in certificate:
            errors.append(f"missing:{field}")
    if errors:
        return False, errors

    canonical_body = _canonical_body(
        mutation_id=str(certificate.get("mutation_id") or ""),
        epoch_id=str(certificate.get("epoch_id") or ""),
        prior_state_digest=str(certificate.get("prior_state_digest") or ""),
        restored_state_digest=str(certificate.get("restored_state_digest") or ""),
        trigger_reason=str(certificate.get("trigger_reason") or ""),
        actor_class=str(certificate.get("actor_class") or ""),
        completeness_checks=dict(certificate.get("completeness_checks") or {}),
        forward_certificate_digest=str(certificate.get("forward_certificate_digest") or ""),
    )
    canonical_body["issued_at"] = str(certificate.get("issued_at") or "")
    expected_digest = sha256_prefixed_digest(canonical_json(canonical_body))
    cert_digest = str(certificate.get("rollback_certificate_digest") or "")
    if cert_digest != expected_digest:
        errors.append("digest_mismatch")

    signature = certificate.get("signature") or {}
    if not isinstance(signature, Mapping):
        errors.append("signature_invalid")
        return False, errors
    signature_ok = cryovant.verify_hmac_digest_signature(
        key_id=str(signature.get("key_id") or ROLLBACK_CERTIFICATE_KEY_ID),
        signed_digest=str(signature.get("signed_digest") or ""),
        signature=str(signature.get("value") or ""),
        specific_env_prefix="CRYOVANT_ROLLBACK_SIGNING_KEY_",
        generic_env_var="CRYOVANT_ROLLBACK_SIGNING_KEY",
        fallback_namespace="cryovant-rollback-certificate",
    )
    if str(signature.get("signed_digest") or "") != cert_digest:
        errors.append("signature_digest_link_mismatch")
    if not signature_ok:
        errors.append("signature_verification_failed")
    return not errors, errors


__all__ = ["RollbackCertificateEnvelope", "issue_rollback_certificate", "verify_rollback_certificate"]
