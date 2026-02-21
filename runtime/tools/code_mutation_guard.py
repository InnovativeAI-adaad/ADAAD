# SPDX-License-Identifier: Apache-2.0
"""
Guarded code mutation helpers.

Applies text/code patches to allowlisted files with atomic writes and
rollback safety. Returns lineage metadata including content checksums.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from runtime import ROOT_DIR, metrics
from runtime.governance.foundation import canonical_json, sha256_prefixed_digest
from runtime.timeutils import now_iso
from runtime.tools.rollback_certificate import issue_rollback_certificate

ELEMENT_ID = "Fire"

FILE_KEYS = ("file", "filepath", "target")
CONTENT_KEYS = ("content", "source", "code", "value")

ALLOWED_ROOTS = (
    ROOT_DIR / "app",
    ROOT_DIR / "runtime",
    ROOT_DIR / "ui",
)


@dataclass
class PatchResult:
    ok: bool
    text: str
    reason: str = "ok"


def _checksum_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_target(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def _allowed_target(path: Path) -> bool:
    for root in ALLOWED_ROOTS:
        try:
            if path == root or root in path.parents:
                return True
        except Exception:
            continue
    return False


def _extract_file_value(entry: Dict[str, Any]) -> Optional[str]:
    for key in FILE_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _normalize_ops(ops: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        file_value = _extract_file_value(op)
        if file_value:
            normalized.append(op)
        files_value = op.get("files")
        if isinstance(files_value, list):
            for entry in files_value:
                if isinstance(entry, dict):
                    normalized.append(entry)
                elif isinstance(entry, str):
                    normalized.append({"file": entry})
    return normalized




def _resolve_rollback_context(ops: List[Dict[str, Any]]) -> tuple[str, str, str, str]:
    for op in ops:
        mutation_id = str(op.get("mutation_id") or op.get("tx_id") or "").strip()
        epoch_id = str(op.get("epoch_id") or "").strip()
        actor_class = str(op.get("actor_class") or "CodeMutationGuard").strip() or "CodeMutationGuard"
        forward_digest = str(op.get("forward_certificate_digest") or op.get("certificate_digest") or "").strip()
        if mutation_id or epoch_id or forward_digest:
            return mutation_id or "code-mutation", epoch_id, actor_class, forward_digest
    return "code-mutation", "", "CodeMutationGuard", ""


def _snapshot_digest(paths: Iterable[Path]) -> str:
    snapshot = []
    for path in sorted(set(paths)):
        snapshot.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "digest": sha256_prefixed_digest(path.read_bytes()) if path.exists() else "",
            }
        )
    return sha256_prefixed_digest(canonical_json(snapshot))


def _emit_rollback_certificate(
    *,
    ops: List[Dict[str, Any]],
    targets: List[Path],
    prior_state_digest: str,
    restored_state_digest: str,
    trigger_reason: str,
    checks: Dict[str, Any],
) -> None:
    mutation_id, epoch_id, actor_class, forward_digest = _resolve_rollback_context(ops)
    issue_rollback_certificate(
        mutation_id=mutation_id,
        epoch_id=epoch_id,
        prior_state_digest=prior_state_digest,
        restored_state_digest=restored_state_digest,
        trigger_reason=trigger_reason,
        actor_class=actor_class,
        completeness_checks={
            **checks,
            "targets_count": len(targets),
        },
        agent_id="system",
        forward_certificate_digest=forward_digest,
    )


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_unified_diff(patch: str) -> List[Tuple[int, List[str]]]:
    hunks: List[Tuple[int, List[str]]] = []
    current: List[str] = []
    start_line = 0
    for line in patch.splitlines(keepends=True):
        if line.startswith("---") or line.startswith("+++"):
            continue
        match = _HUNK_HEADER.match(line)
        if match:
            if current:
                hunks.append((start_line, current))
                current = []
            start_line = int(match.group(1))
            continue
        if current is not None:
            current.append(line)
    if current:
        hunks.append((start_line, current))
    return hunks


def _apply_unified_diff(original: str, patch: str) -> PatchResult:
    if not patch.strip():
        return PatchResult(ok=False, text=original, reason="empty_patch")
    hunks = _parse_unified_diff(patch)
    if not hunks:
        return PatchResult(ok=False, text=original, reason="no_hunks")
    original_lines = original.splitlines(keepends=True)
    result: List[str] = []
    index = 0
    for start_line, lines in hunks:
        target_index = max(start_line - 1, 0)
        if target_index < index:
            return PatchResult(ok=False, text=original, reason="overlapping_hunks")
        result.extend(original_lines[index:target_index])
        index = target_index
        for line in lines:
            if not line:
                continue
            marker = line[0]
            content = line[1:]
            if marker == " ":
                if index >= len(original_lines) or original_lines[index] != content:
                    return PatchResult(ok=False, text=original, reason="context_mismatch")
                result.append(original_lines[index])
                index += 1
            elif marker == "-":
                if index >= len(original_lines) or original_lines[index] != content:
                    return PatchResult(ok=False, text=original, reason="remove_mismatch")
                index += 1
            elif marker == "+":
                result.append(content)
            elif marker == "\\":
                continue
            else:
                return PatchResult(ok=False, text=original, reason="invalid_hunk")
    result.extend(original_lines[index:])
    return PatchResult(ok=True, text="".join(result))


def extract_targets(ops: Iterable[Dict[str, Any]]) -> List[Path]:
    targets: List[Path] = []
    for op in _normalize_ops(ops):
        value = _extract_file_value(op)
        if not value:
            continue
        target = _resolve_target(value)
        if target not in targets:
            targets.append(target)
    return targets


def apply_code_mutation(ops: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = _normalize_ops(ops)
    grouped: Dict[Path, List[Dict[str, Any]]] = {}
    for op in normalized:
        value = _extract_file_value(op)
        if not value:
            continue
        target = _resolve_target(value)
        grouped.setdefault(target, []).append(op)

    result: Dict[str, Any] = {
        "applied": 0,
        "skipped": 0,
        "errors": [],
        "targets": [],
        "updated_at": now_iso(),
    }

    if not grouped:
        return {**result, "status": "skipped", "reason": "no_targets"}

    rollback_targets = list(grouped.keys())
    prior_state_digest = _snapshot_digest(rollback_targets)
    updates: Dict[Path, str] = {}
    backups: Dict[Path, Optional[bytes]] = {}
    lineage: List[Dict[str, Any]] = []

    for target, ops_for_target in grouped.items():
        if not _allowed_target(target):
            result["errors"].append({"path": str(target), "reason": "path_not_allowlisted"})
            result["skipped"] += len(ops_for_target)
            continue

        original_text = target.read_text(encoding="utf-8") if target.exists() else ""
        new_text = original_text
        backups[target] = target.read_bytes() if target.exists() else None
        applied = False
        for op in ops_for_target:
            patch = op.get("patch")
            content = None
            for key in CONTENT_KEYS:
                value = op.get(key)
                if isinstance(value, str):
                    content = value
                    break
            if isinstance(patch, str):
                patch_result = _apply_unified_diff(new_text, patch)
                if not patch_result.ok:
                    result["errors"].append({"path": str(target), "reason": patch_result.reason})
                    break
                new_text = patch_result.text
                result["applied"] += 1
                applied = True
            elif content is not None:
                new_text = content
                result["applied"] += 1
                applied = True
            else:
                result["skipped"] += 1
        else:
            updates[target] = new_text
            lineage.append(
                {
                    "path": str(target),
                    "before": _checksum_text(original_text),
                    "after": _checksum_text(new_text),
                    "updated": applied,
                }
            )
            continue
        result["skipped"] += max(len(ops_for_target) - int(applied), 0)

    if result["errors"]:
        restored_state_digest = _snapshot_digest(rollback_targets)
        _emit_rollback_certificate(
            ops=normalized,
            targets=rollback_targets,
            prior_state_digest=prior_state_digest,
            restored_state_digest=restored_state_digest,
            trigger_reason="patch_validation_failure",
            checks={"errors_detected": len(result["errors"]), "writes_applied": False},
        )
        metrics.log(
            event_type="code_mutation_rollback",
            payload={"errors": result["errors"], "targets": [str(path) for path in grouped]},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        return {**result, "status": "failed"}

    try:
        for target, content in updates.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(target.parent)) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            temp_path.replace(target)
    except Exception as exc:  # pragma: no cover - defensive rollback
        for target, original in backups.items():
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                target.write_bytes(original)
        restored_state_digest = _snapshot_digest(rollback_targets)
        _emit_rollback_certificate(
            ops=normalized,
            targets=rollback_targets,
            prior_state_digest=prior_state_digest,
            restored_state_digest=restored_state_digest,
            trigger_reason="atomic_write_failure",
            checks={"errors_detected": 1, "writes_reverted": True},
        )
        metrics.log(
            event_type="code_mutation_rollback",
            payload={"errors": [str(exc)], "targets": [str(path) for path in grouped]},
            level="ERROR",
            element_id=ELEMENT_ID,
        )
        return {**result, "status": "failed", "errors": [str(exc)]}

    checksum = _checksum_text("".join(item["after"] for item in lineage))
    metrics.log(
        event_type="code_mutation_applied",
        payload={"targets": lineage, "checksum": checksum},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return {
        **result,
        "status": "applied",
        "checksum": checksum,
        "targets": lineage,
    }


__all__ = ["apply_code_mutation", "extract_targets"]
