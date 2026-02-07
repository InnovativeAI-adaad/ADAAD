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
                "payload": {"blocking_failures": ["signature_required"]},
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
