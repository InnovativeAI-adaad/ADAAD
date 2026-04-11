# SPDX-License-Identifier: Apache-2.0
"""Minimal GitHub App webhook helpers used by tests and local wiring."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


def _is_dev_mode() -> bool:
    return (os.getenv("ADAAD_ENV") or "").strip().lower() in {"dev", "local", "test"}


def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    """Validate GitHub webhook signature using SHA-256 HMAC."""
    secret = GITHUB_WEBHOOK_SECRET or os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return _is_dev_mode()

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def dispatch_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Route GitHub webhook payload to deterministic summary shape."""
    event = (event_type or "").strip().lower()
    payload = payload if isinstance(payload, dict) else {}

    if event == "ping":
        return {"status": "ok", "event": "ping", "zen": payload.get("zen", "")}

    if event == "push":
        commits = payload.get("commits")
        return {
            "status": "ok",
            "event": "push",
            "ref": payload.get("ref", ""),
            "repository": ((payload.get("repository") or {}).get("full_name", "")),
            "commits": len(commits) if isinstance(commits, list) else 0,
            "actor": ((payload.get("pusher") or {}).get("name", "")),
        }

    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        return {
            "status": "ok",
            "event": "pull_request",
            "action": payload.get("action", ""),
            "pr": pr.get("number"),
            "title": pr.get("title", ""),
            "merged": bool(pr.get("merged", False)),
            "merge_commit_sha": pr.get("merge_commit_sha", ""),
        }

    if event == "issue_comment":
        comment = payload.get("comment") or {}
        raw = str(comment.get("body", "")).strip()
        command = ""
        if raw.startswith("/adaad "):
            tokens = raw.split()
            if len(tokens) >= 2:
                command = tokens[1]
        return {
            "status": "ok",
            "event": "issue_comment",
            "command": command,
            "actor": ((comment.get("user") or {}).get("login", "")),
            "issue": ((payload.get("issue") or {}).get("number")),
        }

    if event == "check_run":
        check_run = payload.get("check_run") or {}
        return {
            "status": "ok",
            "event": "check_run",
            "name": check_run.get("name", ""),
            "conclusion": check_run.get("conclusion", ""),
            "head_sha": check_run.get("head_sha", ""),
        }

    if event == "installation":
        account = ((payload.get("installation") or {}).get("account") or {})
        return {"status": "ok", "event": "installation", "account": account.get("login", "")}

    if event == "pull_request_review":
        review = payload.get("review") or {}
        return {
            "status": "ok",
            "event": "pull_request_review",
            "state": review.get("state", ""),
            "actor": ((review.get("user") or {}).get("login", "")),
            "pr": ((payload.get("pull_request") or {}).get("number")),
        }

    return {"status": "ignored", "event": event}


__all__ = ["GITHUB_WEBHOOK_SECRET", "dispatch_event", "verify_webhook_signature"]
