# SPDX-License-Identifier: Apache-2.0
"""Deterministic forensic bundle retention enforcement helper.

This utility is intentionally simple and fail-closed:
- Requires an explicit `--now-epoch` input to avoid implicit wall-clock dependence.
- Refuses to enforce retention if bundle metadata is malformed.
- Produces deterministic action ordering for repeatable operator runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

RETENTION_LOG_BASENAME = "retention_disposition.jsonl"


class RetentionError(RuntimeError):
    """Raised when retention evaluation cannot proceed safely."""


def _canonical_json_line(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_bundle(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RetentionError(f"invalid_bundle_json:{path}:{exc.msg}") from exc
    if not isinstance(value, dict):
        raise RetentionError(f"invalid_bundle_type:{path}:expected_object")
    return value


def _bundle_retention_days(bundle: Dict[str, Any], default_retention_days: int) -> int:
    metadata = bundle.get("export_metadata")
    if not isinstance(metadata, dict):
        return default_retention_days
    raw = metadata.get("retention_days", default_retention_days)
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise RetentionError("invalid_retention_days") from exc
    if parsed < 1:
        raise RetentionError("invalid_retention_days")
    return parsed


def collect_retention_actions(*, export_dir: Path, default_retention_days: int, now_epoch: int) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for path in sorted(export_dir.glob("*.json")):
        if path.name == RETENTION_LOG_BASENAME:
            continue
        bundle = _read_bundle(path)
        retention_days = _bundle_retention_days(bundle, default_retention_days)
        age_days = max(0, int((now_epoch - int(path.stat().st_mtime)) // 86400))
        expired = age_days > retention_days
        metadata = bundle.get("export_metadata") if isinstance(bundle.get("export_metadata"), dict) else {}
        actions.append(
            {
                "path": str(path),
                "bundle_id": str(bundle.get("bundle_id") or ""),
                "digest": str(metadata.get("digest") or ""),
                "age_days": age_days,
                "retention_days": retention_days,
                "expired": expired,
                "action": "delete" if expired else "keep",
            }
        )
    return actions


def enforce_retention(*, actions: List[Dict[str, Any]], now_epoch: int, enforce: bool, export_dir: Path) -> Dict[str, Any]:
    disposition_log = export_dir / RETENTION_LOG_BASENAME
    deleted = 0
    kept = 0
    for action in actions:
        if action.get("action") == "delete" and enforce:
            Path(str(action["path"])).unlink(missing_ok=False)
            deleted += 1
        else:
            kept += 1

    if enforce:
        disposition_log.parent.mkdir(parents=True, exist_ok=True)
        with disposition_log.open("a", encoding="utf-8") as handle:
            for action in actions:
                handle.write(
                    _canonical_json_line(
                        {
                            "schema_version": "forensic_retention_disposition.v1",
                            "now_epoch": now_epoch,
                            "enforced": True,
                            "action": action["action"],
                            "path": action["path"],
                            "bundle_id": action["bundle_id"],
                            "digest": action["digest"],
                            "age_days": action["age_days"],
                            "retention_days": action["retention_days"],
                        }
                    )
                    + "\n"
                )

    return {
        "ok": True,
        "enforced": enforce,
        "export_dir": str(export_dir),
        "total": len(actions),
        "deleted": deleted,
        "kept": kept,
        "actions": actions,
        "disposition_log": str(disposition_log),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enforce deterministic forensic retention policy")
    parser.add_argument("--export-dir", default="reports/forensics", help="forensic export directory")
    parser.add_argument("--retention-days", type=int, default=365, help="default retention window")
    parser.add_argument("--now-epoch", type=int, required=True, help="explicit unix epoch for deterministic evaluation")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="evaluate only (default)")
    mode.add_argument("--enforce", action="store_true", help="delete expired bundles and append disposition events")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    export_dir = Path(args.export_dir)
    enforce = bool(args.enforce)
    try:
        actions = collect_retention_actions(
            export_dir=export_dir,
            default_retention_days=max(1, int(args.retention_days)),
            now_epoch=int(args.now_epoch),
        )
        summary = enforce_retention(actions=actions, now_epoch=int(args.now_epoch), enforce=enforce, export_dir=export_dir)
    except RetentionError as exc:
        print(_canonical_json_line({"ok": False, "error": str(exc)}))
        return 2

    print(_canonical_json_line(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
