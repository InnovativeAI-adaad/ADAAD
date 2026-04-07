# SPDX-License-Identifier: Apache-2.0
"""
Tests for ADAADchat GitHub App webhook handler.
App ID: 3013088
"""
import hashlib
import hmac
import json
import os
import pytest

from runtime.integrations.github_app import verify_webhook_signature, dispatch_event

SECRET = "test-webhook-secret-adaad"


def _sig(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestSignatureVerification:
    def test_valid_signature(self, monkeypatch):
        import runtime.integrations.github_app as gapp
        monkeypatch.setattr(gapp, "GITHUB_WEBHOOK_SECRET", SECRET)
        body = b'{"action": "opened"}'
        assert verify_webhook_signature(body, _sig(body)) is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
        import runtime.integrations.github_app as gapp
        monkeypatch.setattr(gapp, "GITHUB_WEBHOOK_SECRET", SECRET)
        assert verify_webhook_signature(b"data", "sha256=badhash") is False

    def test_missing_header(self, monkeypatch):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
        import runtime.integrations.github_app as gapp
        monkeypatch.setattr(gapp, "GITHUB_WEBHOOK_SECRET", SECRET)
        assert verify_webhook_signature(b"data", "") is False

    def test_no_secret_dev_mode_allowed(self, monkeypatch):
        monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("ADAAD_ENV", "dev")
        assert verify_webhook_signature(b"data", "") is True

    def test_no_secret_non_dev_blocked(self, monkeypatch):
        import runtime.integrations.github_app as gapp
        monkeypatch.setattr(gapp, "GITHUB_WEBHOOK_SECRET", "")
        monkeypatch.setenv("ADAAD_ENV", "prod")
        assert verify_webhook_signature(b"data", "") is False


class TestEventDispatch:
    def test_ping(self):
        result = dispatch_event("ping", {"zen": "Keep it logically awesome."})
        assert result["status"] == "ok"
        assert result["event"] == "ping"
        assert "zen" in result

    def test_push_main(self):
        payload = {
            "ref": "refs/heads/main",
            "repository": {"full_name": "InnovativeAI-adaad/ADAAD"},
            "commits": [{}, {}],
            "pusher": {"name": "dreezy-6"},
        }
        result = dispatch_event("push", payload)
        assert result["status"] == "ok"
        assert result["commits"] == 2
        assert result["ref"] == "refs/heads/main"

    def test_push_non_main(self):
        payload = {
            "ref": "refs/heads/feature/x",
            "repository": {"full_name": "InnovativeAI-adaad/ADAAD"},
            "commits": [{}],
            "pusher": {"name": "dreezy-6"},
        }
        result = dispatch_event("push", payload)
        assert result["status"] == "ok"

    def test_pull_request_opened(self):
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42, "title": "feat: add thing",
                "head": {"sha": "abc123"}, "merged": False,
            },
            "repository": {"full_name": "InnovativeAI-adaad/ADAAD"},
        }
        result = dispatch_event("pull_request", payload)
        assert result["status"] == "ok"
        assert result["pr"] == 42
        assert result["action"] == "opened"

    def test_pull_request_merged(self):
        payload = {
            "action": "closed",
            "pull_request": {
                "number": 7, "title": "fix: thing", "merged": True,
                "merged_by": {"login": "dreezy-6"},
                "merge_commit_sha": "def456",
                "head": {"sha": "abc"},
            },
            "repository": {"full_name": "InnovativeAI-adaad/ADAAD"},
        }
        result = dispatch_event("pull_request", payload)
        assert result["status"] == "ok"

    def test_slash_command(self):
        payload = {
            "action": "created",
            "comment": {"body": "/adaad status", "user": {"login": "dreezy-6"}},
            "issue": {"number": 10},
            "repository": {"full_name": "InnovativeAI-adaad/ADAAD"},
        }
        result = dispatch_event("issue_comment", payload)
        assert result["status"] == "ok"
        assert result["command"] == "status"
        assert result["actor"] == "dreezy-6"

    def test_ci_failure(self):
        payload = {
            "action": "completed",
            "check_run": {
                "name": "CI / test",
                "conclusion": "failure",
                "head_sha": "abc123",
            },
        }
        result = dispatch_event("check_run", payload)
        assert result["conclusion"] == "failure"
        assert result["status"] == "ok"

    def test_unknown_event_ignored(self):
        result = dispatch_event("marketplace_purchase", {})
        assert result["status"] == "ignored"

    def test_installation(self):
        payload = {
            "action": "created",
            "installation": {"account": {"login": "InnovativeAI-adaad"}},
        }
        result = dispatch_event("installation", payload)
        assert result["account"] == "InnovativeAI-adaad"
        assert result["status"] == "ok"

    def test_pr_review(self):
        payload = {
            "action": "submitted",
            "review": {
                "state": "approved",
                "user": {"login": "dreezy-6"},
                "submitted_at": "2026-03-14T00:00:00Z",
            },
            "pull_request": {"number": 5},
        }
        result = dispatch_event("pull_request_review", payload)
        assert result["state"] == "approved"
