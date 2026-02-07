# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
from pathlib import Path

from app.main import Orchestrator
from runtime import metrics


def test_dry_run_does_not_modify_dna() -> None:
    original_metrics = metrics.METRICS_PATH
    original_force_tier = os.environ.get("ADAAD_FORCE_TIER")
    with tempfile.TemporaryDirectory() as tmpdir:
        metrics.METRICS_PATH = Path(tmpdir) / "metrics.jsonl"
        os.environ["ADAAD_FORCE_TIER"] = "SANDBOX"
        dna_path = Path(__file__).resolve().parents[1] / "app" / "agents" / "test_subject" / "dna.json"
        before = dna_path.read_text(encoding="utf-8")
        orchestrator = Orchestrator(dry_run=True)
        orchestrator._run_mutation_cycle()
        after = dna_path.read_text(encoding="utf-8")
        metrics_entries = metrics.METRICS_PATH.read_text(encoding="utf-8").splitlines()
    metrics.METRICS_PATH = original_metrics
    if original_force_tier is None:
        os.environ.pop("ADAAD_FORCE_TIER", None)
    else:
        os.environ["ADAAD_FORCE_TIER"] = original_force_tier
    assert before == after
    assert any('"event": "mutation_dry_run"' in line for line in metrics_entries)
