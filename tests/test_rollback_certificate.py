from __future__ import annotations

from copy import deepcopy
from unittest import mock

from runtime.tools.rollback_certificate import issue_rollback_certificate, verify_rollback_certificate


@mock.patch("runtime.tools.rollback_certificate.journal.append_tx")
@mock.patch("runtime.tools.rollback_certificate.journal.write_entry")
def test_issue_and_verify_rollback_certificate(_write_entry, _append_tx) -> None:
    envelope = issue_rollback_certificate(
        mutation_id="m-1",
        epoch_id="epoch-1",
        prior_state_digest="sha256:prior",
        restored_state_digest="sha256:restored",
        trigger_reason="manual",
        actor_class="UnitTest",
        completeness_checks={"restored": True},
        agent_id="agent-alpha",
        forward_certificate_digest="sha256:forward",
    )
    ok, errors = verify_rollback_certificate(envelope.certificate)
    assert ok is True
    assert errors == []


@mock.patch("runtime.tools.rollback_certificate.journal.append_tx")
@mock.patch("runtime.tools.rollback_certificate.journal.write_entry")
def test_verify_rollback_certificate_detects_tampering(_write_entry, _append_tx) -> None:
    envelope = issue_rollback_certificate(
        mutation_id="m-2",
        epoch_id="epoch-1",
        prior_state_digest="sha256:a",
        restored_state_digest="sha256:b",
        trigger_reason="failure",
        actor_class="UnitTest",
        completeness_checks={"restored": True},
        agent_id="agent-alpha",
        forward_certificate_digest="sha256:forward",
    )
    tampered = deepcopy(envelope.certificate)
    tampered["restored_state_digest"] = "sha256:evil"
    ok, errors = verify_rollback_certificate(tampered)
    assert ok is False
    assert "digest_mismatch" in errors
