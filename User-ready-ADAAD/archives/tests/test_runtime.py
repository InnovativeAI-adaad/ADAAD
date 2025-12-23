# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import json

from adad_core.io.atomic import append_jsonl, write_atomic_json
from adad_core.io.health import health_snapshot
from adad_core.runtime import pipeline
from adad_core.runtime.sandbox import run_script


def test_sandbox_ok(tmp_path: Path):
    demo = tmp_path / "demo_agent.py"
    demo.write_text("def run():\n    return 1\nif __name__=='__main__':\n    run()\n", encoding="utf-8")
    res = run_script(str(demo))
    assert "runtime" in res and isinstance(res["ok"], bool)


def test_append_and_atomic(tmp_path: Path):
    data_file = tmp_path / "metrics.jsonl"
    append_jsonl(data_file, {"a": 1})
    append_jsonl(data_file, {"b": 2})
    write_atomic_json(tmp_path / "final.json", {"ok": True})
    lines = data_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert Path(tmp_path / "final.json").exists()


def test_health_snapshot_shape():
    snap = health_snapshot()
    assert "battery" in snap and "over_cpu_limit" in snap


def test_cycle_logs_and_quarantine(tmp_path: Path):
    logs_dir = Path("data/logs")
    quarantine_dir = Path("data/quarantine")
    logs_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    for log in logs_dir.glob("*.jsonl"):
        log.unlink()
    for quarantined in quarantine_dir.glob("*.py"):
        quarantined.unlink()

    bad_agent = Path("adad_core/agents/bad_agent.py")
    bad_agent.parent.mkdir(parents=True, exist_ok=True)
    bad_agent.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    try:
        pipeline.cycle_once()
        fitness_log = logs_dir / "fitness.jsonl"
        metrics_log = logs_dir / "metrics.jsonl"
        assert fitness_log.exists()
        assert metrics_log.exists()
        fitness_entries = fitness_log.read_text(encoding="utf-8").strip().splitlines()
        assert any("bad_agent.py" in entry for entry in fitness_entries)
        metrics_entries = [json.loads(line) for line in metrics_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(entry.get("kind") == "cycle_summary" for entry in metrics_entries)
        assert (quarantine_dir / bad_agent.name).exists()
    finally:
        bad_agent.unlink(missing_ok=True)
        for log in logs_dir.glob("*.jsonl"):
            log.unlink()
        for quarantined in quarantine_dir.glob("*.py"):
            quarantined.unlink()
