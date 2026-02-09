# SPDX-License-Identifier: Apache-2.0

import json
import os
import tempfile
import time
from pathlib import Path

from app.agents.mutation_request import MutationRequest
from runtime import metrics
from runtime.constitution import Tier, evaluate_mutation


def _write_metric_entries(path: Path, event: str, count: int) -> None:
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {
        "timestamp": now_iso,
        "event": event,
        "level": "INFO",
        "element": "Earth",
        "payload": {},
    }
    lines = [json.dumps(record) for _ in range(count)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_mutation_rate_blocks_when_threshold_exceeded() -> None:
    original_metrics_path = metrics.METRICS_PATH
    original_max_rate = os.environ.get("ADAAD_MAX_MUTATIONS_PER_HOUR")
    original_window = os.environ.get("ADAAD_MUTATION_RATE_WINDOW_SEC")
    original_dev_mode = os.environ.get("CRYOVANT_DEV_MODE")
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics.METRICS_PATH = Path(tmpdir) / "metrics.jsonl"
        metrics.METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write_metric_entries(metrics.METRICS_PATH, "mutation_executed", count=3)
        os.environ["ADAAD_MAX_MUTATIONS_PER_HOUR"] = "2"
        os.environ["ADAAD_MUTATION_RATE_WINDOW_SEC"] = "3600"
        os.environ["CRYOVANT_DEV_MODE"] = "1"
        request = MutationRequest(
            agent_id="test_subject",
            generation_ts="now",
            intent="test",
            ops=[],
            signature="cryovant-dev-test",
            nonce="nonce",
        )
        verdict = evaluate_mutation(request, Tier.PRODUCTION)
    metrics.METRICS_PATH = original_metrics_path
    if original_max_rate is None:
        os.environ.pop("ADAAD_MAX_MUTATIONS_PER_HOUR", None)
    else:
        os.environ["ADAAD_MAX_MUTATIONS_PER_HOUR"] = original_max_rate
    if original_window is None:
        os.environ.pop("ADAAD_MUTATION_RATE_WINDOW_SEC", None)
    else:
        os.environ["ADAAD_MUTATION_RATE_WINDOW_SEC"] = original_window
    if original_dev_mode is None:
        os.environ.pop("CRYOVANT_DEV_MODE", None)
    else:
        os.environ["CRYOVANT_DEV_MODE"] = original_dev_mode

    assert verdict["passed"] is False
    assert "max_mutation_rate" in verdict["blocking_failures"]
    rate_verdict = next(item for item in verdict["verdicts"] if item["rule"] == "max_mutation_rate")
    assert rate_verdict["passed"] is False
