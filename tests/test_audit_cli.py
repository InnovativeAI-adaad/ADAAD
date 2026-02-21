# SPDX-License-Identifier: Apache-2.0

import json
import tempfile
from pathlib import Path

from runtime import metrics
from tools.adaad_audit import run_audit


def _write_metrics(path: Path, entries: list[dict]) -> None:
    lines = [json.dumps(entry) for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_audit_cli_filters_and_summary() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "metrics.jsonl"
        entries = [
            {
                "timestamp": "2026-02-06T00:00:00Z",
                "event": "constitutional_evaluation",
                "level": "INFO",
                "element": "Earth",
                "payload": {
                    "agent_id": "test_subject",
                    "tier": "SANDBOX",
                    "passed": True,
                    "blocking_failures": [],
                    "warnings": [],
                },
            },
            {
                "timestamp": "2026-02-06T01:00:00Z",
                "event": "mutation_rejected_constitutional",
                "level": "ERROR",
                "element": "Earth",
                "payload": {
                    "agent_id": "test_subject",
                    "tier": "SANDBOX",
                    "blocking_failures": ["signature_required"],
                },
            },
        ]
        _write_metrics(metrics_path, entries)
        original = metrics.METRICS_PATH
        metrics.METRICS_PATH = metrics_path
        try:
            output = run_audit("test_subject", "SANDBOX", None, None, "json")
        finally:
            metrics.METRICS_PATH = original
        report = json.loads(output)
        assert len(report["evaluations"]) == 1
        assert report["violations"]["constitutional"]["signature_required"] == 1


def test_audit_cli_summary_respects_filters() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "metrics.jsonl"
        entries = [
            {
                "timestamp": "2026-02-06T00:00:00Z",
                "event": "constitutional_evaluation",
                "level": "INFO",
                "element": "Earth",
                "payload": {
                    "agent_id": "alpha",
                    "tier": "SANDBOX",
                    "passed": True,
                    "blocking_failures": [],
                    "warnings": [],
                },
            },
            {
                "timestamp": "2026-02-06T00:30:00Z",
                "event": "mutation_rejected_preflight",
                "level": "ERROR",
                "element": "Earth",
                "payload": {
                    "agent_id": "alpha",
                    "tier": "SANDBOX",
                    "reason": "missing_signature",
                },
            },
            {
                "timestamp": "2026-02-06T00:45:00Z",
                "event": "mutation_rejected_constitutional",
                "level": "ERROR",
                "element": "Earth",
                "payload": {
                    "agent_id": "alpha",
                    "tier": "SANDBOX",
                    "blocking_failures": ["signature_required", "policy_violation"],
                },
            },
            {
                "timestamp": "2026-02-06T01:00:00Z",
                "event": "constitutional_evaluation",
                "level": "INFO",
                "element": "Earth",
                "payload": {
                    "agent_id": "bravo",
                    "tier": "PRODUCTION",
                    "passed": False,
                    "blocking_failures": ["policy_violation"],
                    "warnings": [],
                },
            },
            {
                "timestamp": "2026-02-06T01:30:00Z",
                "event": "mutation_rejected_preflight",
                "level": "ERROR",
                "element": "Earth",
                "payload": {
                    "agent_id": "bravo",
                    "tier": "PRODUCTION",
                    "reason": "bad_checksum",
                },
            },
        ]
        _write_metrics(metrics_path, entries)
        original = metrics.METRICS_PATH
        metrics.METRICS_PATH = metrics_path
        try:
            output = run_audit(
                "alpha",
                "SANDBOX",
                "2026-02-06T00:00:00Z",
                "2026-02-06T00:59:59Z",
                "json",
            )
        finally:
            metrics.METRICS_PATH = original
        report = json.loads(output)
        assert len(report["evaluations"]) == 1
        assert report["violations"]["preflight"]["missing_signature"] == 1
        assert report["violations"]["constitutional"]["signature_required"] == 1
        assert report["violations"]["constitutional"]["policy_violation"] == 1


def test_audit_cli_autonomy_scoreboard_action_json() -> None:
    from tools.adaad_audit import run_autonomy_scoreboard

    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "metrics.jsonl"
        entries = [
            {
                "timestamp": "2026-02-06T00:00:00Z",
                "event": "autonomy_action",
                "level": "INFO",
                "element": "Earth",
                "payload": {"agent": "ExecutorAgent", "duration_ms": 40, "ok": True},
            },
            {
                "timestamp": "2026-02-06T00:01:00Z",
                "event": "mutation_executed",
                "level": "INFO",
                "element": "Earth",
                "payload": {"ok": True},
            },
            {
                "timestamp": "2026-02-06T00:02:00Z",
                "event": "sandbox_validation_failed",
                "level": "WARN",
                "element": "Earth",
                "payload": {"reason": "missing_signature"},
            },
        ]
        _write_metrics(metrics_path, entries)
        original = metrics.METRICS_PATH
        metrics.METRICS_PATH = metrics_path
        try:
            output = run_autonomy_scoreboard(limit=10, output="json")
        finally:
            metrics.METRICS_PATH = original

        report = json.loads(output)
        assert set(report.keys()) >= {
            "performance_by_agent",
            "mutation_outcomes",
            "sandbox_failure_reasons",
        }
        assert report["performance_by_agent"]["ExecutorAgent"]["calls"] == 1.0
        assert report["mutation_outcomes"]["mutation_executed"] == 1
        assert report["sandbox_failure_reasons"]["missing_signature"] == 1


def test_audit_cli_pr_applicability_action_json() -> None:
    from tools.adaad_audit import run_pr_applicability

    with tempfile.TemporaryDirectory() as tmpdir:
        metrics_path = Path(tmpdir) / "metrics.jsonl"
        entries = [
            {
                "timestamp": "2026-02-06T00:00:00Z",
                "event": "constitutional_evaluation",
                "level": "INFO",
                "element": "Earth",
                "payload": {
                    "agent_id": "alpha",
                    "tier": "STABLE",
                    "passed": True,
                    "applicability_matrix": [
                        {
                            "rule": "ast_validity",
                            "applicable": True,
                            "scope_match": True,
                            "trigger_match": True,
                            "change_type_match": True,
                            "fail_behavior": {"on_fail": "block"},
                        }
                    ],
                },
            }
        ]
        _write_metrics(metrics_path, entries)
        original = metrics.METRICS_PATH
        metrics.METRICS_PATH = metrics_path
        try:
            output = run_pr_applicability("alpha", "STABLE", "json")
        finally:
            metrics.METRICS_PATH = original
        report = json.loads(output)
        assert report["payload"]["applicability_matrix"][0]["rule"] == "ast_validity"
