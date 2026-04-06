# SPDX-License-Identifier: Apache-2.0
"""Phase 77 Track A — Constitutional closure tests.

Covers the four governance gaps closed in feat/phase-77-track-a-close:

  1. EventSigner / EventVerifier — converted to proper ABC (EVENT-SIGN-ABSTRACT-0)
  2. GovernancePlugin.evaluate() — converted to proper ABC (GPLUGIN-ABSTRACT-0)
  3. FitnessEvaluator.evaluate() — abstractmethod contract clarified
  4. Dual webhook handler — shim delegates 100% to app.github_app
     (WEBHOOK-SHIM-DELEG-0 / WEBHOOK-SHIM-COMPAT-0)

Each test asserts the specific invariant it closes.  All tests are hermetic
and deterministic; no external I/O, no ledger writes.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
import pytest
from typing import Any, Mapping
from unittest.mock import patch

# ── 1. EventSigner / EventVerifier ABC enforcement ────────────────────────────

class TestEventSignerAbstract:
    """EVENT-SIGN-ABSTRACT-0: EventSigner is abstract; direct instantiation is a TypeError."""

    def test_event_signer_cannot_be_instantiated(self):
        from runtime.evolution.event_signing import EventSigner
        with pytest.raises(TypeError, match="abstract"):
            EventSigner()  # type: ignore[abstract]

    def test_event_verifier_cannot_be_instantiated(self):
        from runtime.evolution.event_signing import EventVerifier
        with pytest.raises(TypeError, match="abstract"):
            EventVerifier()  # type: ignore[abstract]

    def test_deterministic_mock_signer_is_concrete_and_functional(self):
        """DeterministicMockSigner satisfies both EventSigner and EventVerifier."""
        from runtime.evolution.event_signing import DeterministicMockSigner, EventSigner, EventVerifier
        m = DeterministicMockSigner()
        assert isinstance(m, EventSigner)
        assert isinstance(m, EventVerifier)
        bundle = m.sign("governance-test-message")
        assert bundle.algorithm == "hmac-sha256"
        assert bundle.signature.startswith("sig:")

    def test_event_sign_determ_0_identical_inputs_identical_bundle(self):
        """EVENT-SIGN-DETERM-0: sign() is deterministic."""
        from runtime.evolution.event_signing import DeterministicMockSigner
        m = DeterministicMockSigner()
        b1 = m.sign("determinism-check")
        b2 = m.sign("determinism-check")
        assert b1 == b2

    def test_event_sign_compare_0_verify_uses_constant_time(self):
        """EVENT-SIGN-COMPARE-0: verify returns False for tampered signature."""
        from runtime.evolution.event_signing import DeterministicMockSigner, SignatureBundle
        m = DeterministicMockSigner()
        bundle = m.sign("message")
        tampered = SignatureBundle(
            signature="sig:deadbeef",
            signing_key_id=bundle.signing_key_id,
            algorithm=bundle.algorithm,
        )
        assert m.verify(message="message", signature=tampered) is False

    def test_hmac_keyring_verifier_concrete(self):
        """HMACKeyringVerifier is a concrete EventVerifier."""
        from runtime.evolution.event_signing import (
            DeterministicMockSigner,
            EventVerifier,
            HMACKeyringVerifier,
        )
        keyring = {"key-1": "s3cr3t"}
        verifier = HMACKeyringVerifier(keyring)
        assert isinstance(verifier, EventVerifier)

        signer = DeterministicMockSigner(key_id="key-1", secret="s3cr3t")
        bundle = signer.sign("cross-verify-test")
        assert verifier.verify(message="cross-verify-test", signature=bundle)

    def test_concrete_subclass_can_implement_signer(self):
        """A custom subclass satisfying the abstract contract instantiates cleanly."""
        from runtime.evolution.event_signing import EventSigner, SignatureBundle

        class Ed25519StubSigner(EventSigner):
            def sign(self, message: str) -> SignatureBundle:
                digest = hashlib.sha256(message.encode()).hexdigest()
                return SignatureBundle(
                    signature=f"ed25519:{digest}",
                    signing_key_id="stub-ed25519",
                    algorithm="ed25519",
                )

        signer = Ed25519StubSigner()
        bundle = signer.sign("hello")
        assert bundle.algorithm == "ed25519"


# ── 2. GovernancePlugin ABC enforcement ───────────────────────────────────────

class TestGovernancePluginAbstract:
    """GPLUGIN-ABSTRACT-0: GovernancePlugin is abstract; direct instantiation is a TypeError."""

    def test_governance_plugin_cannot_be_instantiated(self):
        from runtime.innovations import GovernancePlugin
        with pytest.raises(TypeError, match="abstract"):
            GovernancePlugin()  # type: ignore[abstract]

    def test_no_new_dependencies_plugin_is_concrete(self):
        from runtime.innovations import GovernancePlugin, NoNewDependenciesPlugin
        p = NoNewDependenciesPlugin()
        assert isinstance(p, GovernancePlugin)

    def test_gplugin_determ_0_identical_inputs_identical_result(self):
        """GPLUGIN-DETERM-0: evaluate() is deterministic."""
        from runtime.innovations import NoNewDependenciesPlugin
        p = NoNewDependenciesPlugin()
        mutation = {"new_dependencies": []}
        r1 = p.evaluate(mutation)
        r2 = p.evaluate(mutation)
        assert r1 == r2

    def test_gplugin_noside_0_does_not_mutate_input(self):
        """GPLUGIN-NOSIDE-0: evaluate() must not mutate the mutation dict."""
        from runtime.innovations import NoNewDependenciesPlugin
        p = NoNewDependenciesPlugin()
        mutation: dict[str, Any] = {"new_dependencies": ["requests"]}
        original = dict(mutation)
        p.evaluate(mutation)
        assert mutation == original

    def test_concrete_subclass_can_implement_plugin(self):
        from runtime.innovations import GovernancePlugin, PluginRuleResult

        class StubPlugin(GovernancePlugin):
            plugin_id = "gplugin.stub.v1"

            def evaluate(self, mutation: Mapping[str, Any]) -> PluginRuleResult:
                return PluginRuleResult(plugin_id=self.plugin_id, passed=True, message="stub-ok")

        result = StubPlugin().evaluate({})
        assert result.passed is True
        assert result.plugin_id == "gplugin.stub.v1"


# ── 3. FitnessEvaluator abstract contract ─────────────────────────────────────

class TestFitnessEvaluatorAbstract:
    """FitnessEvaluator is ABC; subclasses must implement evaluate()."""

    def test_fitness_evaluator_cannot_be_instantiated(self):
        from runtime.fitness_pipeline import FitnessEvaluator
        with pytest.raises(TypeError):
            FitnessEvaluator()  # type: ignore[abstract]

    def test_concrete_evaluator_satisfies_contract(self):
        from runtime.fitness_pipeline import FitnessEvaluator, FitnessMetric

        class AlwaysOneEvaluator(FitnessEvaluator):
            def evaluate(self, mutation_data):
                return FitnessMetric(name="always_one", weight=1.0, score=1.0, metadata={})

        e = AlwaysOneEvaluator()
        result = e.evaluate({})
        assert result.score == 1.0

    def test_existing_evaluators_remain_concrete(self):
        from runtime.fitness_pipeline import (
            EfficiencyEvaluator,
            FitnessEvaluator,
            PolicyComplianceEvaluator,
            RiskEvaluator,
            TestOutcomeEvaluator,
        )
        for cls in (TestOutcomeEvaluator, RiskEvaluator, EfficiencyEvaluator, PolicyComplianceEvaluator):
            inst = cls()
            assert isinstance(inst, FitnessEvaluator)


# ── 4. Webhook shim — dual handler consolidation ─────────────────────────────

class TestWebhookShimDelegation:
    """WEBHOOK-SHIM-DELEG-0: shim delegates 100% to app.github_app.
    WEBHOOK-SHIM-COMPAT-0: public API surface preserved.
    """

    def test_shim_exports_required_public_api(self):
        from runtime.integrations import github_webhook_handler as shim
        for name in (
            "verify_webhook_signature",
            "handle_webhook",
            "handle_push",
            "handle_pull_request",
            "handle_check_run",
            "handle_workflow_run",
            "handle_installation",
            "HANDLED_EVENTS",
            "EVENT_HANDLERS",
        ):
            assert hasattr(shim, name), f"missing public API: {name}"

    def test_verify_webhook_signature_is_same_object_as_governed_app(self):
        """WEBHOOK-SHIM-DELEG-0: signature verification is the governed implementation."""
        from runtime.integrations.github_app import verify_webhook_signature as authoritative
        from runtime.integrations.github_webhook_handler import verify_webhook_signature as shim_fn
        assert shim_fn is authoritative

    def test_handle_push_delegates_to_governed_dispatch(self):
        from runtime.integrations.github_webhook_handler import handle_push
        result = handle_push({"ref": "refs/heads/feature", "repository": {"full_name": "org/repo"}})
        assert result["status"] == "ok"
        assert result["event"] == "push"

    def test_handle_pull_request_delegates(self):
        from runtime.integrations.github_webhook_handler import handle_pull_request
        result = handle_pull_request({
            "action": "opened",
            "pull_request": {"number": 42, "title": "test pr", "user": {"login": "dev"},
                             "head": {"sha": "abc123"}, "base": {"ref": "main"}},
            "repository": {"full_name": "org/repo"},
        })
        assert result["status"] == "ok"
        assert result["event"] == "pull_request"

    def test_handle_check_run_delegates(self):
        from runtime.integrations.github_webhook_handler import handle_check_run
        result = handle_check_run({
            "action": "completed",
            "check_run": {"name": "ci/test", "conclusion": "success", "head_sha": "abc"},
        })
        assert result["status"] == "ok"

    def test_handle_installation_delegates(self):
        from runtime.integrations.github_webhook_handler import handle_installation
        result = handle_installation({
            "action": "created",
            "installation": {"account": {"login": "org"}, "id": 99},
        })
        assert result["status"] == "ok"

    def test_handle_webhook_valid_signature_routes_event(self, monkeypatch):
        """handle_webhook: valid sig → 200 + dispatch.

        GITHUB_WEBHOOK_SECRET is read at module import time in app.github_app,
        so we patch the module-level constant directly rather than the env var.
        """
        import runtime.integrations.github_app as governed_app
        secret = "test-webhook-secret"
        monkeypatch.setattr(governed_app, "GITHUB_WEBHOOK_SECRET", secret)
        monkeypatch.setenv("ADAAD_ENV", "dev")  # dev: GovernanceGate advisory passthrough

        payload = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "org/repo"},
                               "commits": [], "pusher": {"name": "dev"}}).encode()
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        from runtime.integrations.github_webhook_handler import handle_webhook
        status, body = handle_webhook(payload, "push", sig, delivery_id="del-001")
        assert status == 200
        assert body["status"] == "ok"

    def test_handle_webhook_invalid_signature_returns_401(self, monkeypatch):
        """handle_webhook: bad sig → 401 fail-closed."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "correct-secret")
        monkeypatch.setenv("ADAAD_ENV", "prod")

        payload = b'{"ref": "refs/heads/main"}'
        from runtime.integrations.github_webhook_handler import handle_webhook
        status, body = handle_webhook(payload, "push", "sha256=badhash", delivery_id="del-002")
        assert status == 401
        assert "invalid_signature" in body.get("error", "")

    def test_handle_webhook_unknown_event_ignored(self, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
        monkeypatch.setenv("ADAAD_ENV", "dev")

        from runtime.integrations.github_webhook_handler import handle_webhook
        payload = b"{}"
        status, body = handle_webhook(payload, "marketplace_purchase", "sha256=x")
        assert status == 200
        assert body["status"] == "ignored"

    def test_handled_events_set_preserved(self):
        from runtime.integrations.github_webhook_handler import HANDLED_EVENTS
        for event in ("push", "pull_request", "check_run", "installation"):
            assert event in HANDLED_EVENTS

    def test_event_handlers_dict_populated(self):
        from runtime.integrations.github_webhook_handler import EVENT_HANDLERS
        assert "push" in EVENT_HANDLERS
        assert callable(EVENT_HANDLERS["push"])
