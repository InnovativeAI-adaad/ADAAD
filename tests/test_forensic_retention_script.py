# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path("scripts/enforce_forensic_retention.py")


def _write_bundle(path: Path, *, bundle_id: str, digest: str, retention_days: int) -> None:
    path.write_text(
        json.dumps(
            {
                "bundle_id": bundle_id,
                "export_metadata": {
                    "digest": digest,
                    "retention_days": retention_days,
                },
            }
        ),
        encoding="utf-8",
    )


def test_forensic_retention_dry_run_reports_expired(tmp_path: Path) -> None:
    exports = tmp_path / "forensics"
    exports.mkdir(parents=True, exist_ok=True)

    expired = exports / "evidence-expired.json"
    fresh = exports / "evidence-fresh.json"
    _write_bundle(expired, bundle_id="evidence-expired", digest="sha256:" + "a" * 64, retention_days=1)
    _write_bundle(fresh, bundle_id="evidence-fresh", digest="sha256:" + "b" * 64, retention_days=365)

    now_epoch = 1_700_000_000
    os.utime(expired, (now_epoch - (3 * 86400), now_epoch - (3 * 86400)))
    os.utime(fresh, (now_epoch - (1 * 86400), now_epoch - (1 * 86400)))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--export-dir", str(exports), "--now-epoch", str(now_epoch), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["enforced"] is False
    assert payload["deleted"] == 0
    actions = {Path(item["path"]).name: item for item in payload["actions"]}
    assert actions["evidence-expired.json"]["action"] == "delete"
    assert actions["evidence-fresh.json"]["action"] == "keep"


def test_forensic_retention_enforce_deletes_and_logs(tmp_path: Path) -> None:
    exports = tmp_path / "forensics"
    exports.mkdir(parents=True, exist_ok=True)

    expired = exports / "evidence-expired.json"
    _write_bundle(expired, bundle_id="evidence-expired", digest="sha256:" + "c" * 64, retention_days=1)

    now_epoch = 1_700_000_000
    os.utime(expired, (now_epoch - (4 * 86400), now_epoch - (4 * 86400)))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--export-dir", str(exports), "--now-epoch", str(now_epoch), "--enforce"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["enforced"] is True
    assert payload["deleted"] == 1
    assert not expired.exists()

    disposition_path = exports / "retention_disposition.jsonl"
    assert disposition_path.exists()
    lines = [line for line in disposition_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["schema_version"] == "forensic_retention_disposition.v1"
    assert entry["action"] == "delete"
