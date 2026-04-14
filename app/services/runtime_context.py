# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class _JournalModule(Protocol):
    def read_entries(self, limit: int = 200) -> list[dict[str, Any]]: ...


class _MetricsModule(Protocol):
    def tail(self, limit: int = 200) -> list[dict[str, Any]]: ...

    def log(self, event_type: str, payload: dict[str, Any] | None = None, level: str = "INFO") -> None: ...


@dataclass(frozen=True)
class RuntimeContext:
    """Shared API runtime dependencies wired at the server composition root."""

    root: Path
    replay_proofs_dir: Path
    forensic_export_dir: Path
    compliance_export_dir: Path
    journal: _JournalModule
    metrics: _MetricsModule
    lineage_ledger_cls: type
    evidence_bundle_builder_factory: Any
