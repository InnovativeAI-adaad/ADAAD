# SPDX-License-Identifier: Apache-2.0
"""
Module: registry_store
Purpose: Provide deterministic JSON/SQLite persistence for capability registries.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: runtime.governance.foundation.canonical_json
  - Consumed by: runtime.capability_graph and migration helpers
  - Governance impact: medium — registry persistence backend controlled by policy state_backend
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from runtime.governance.foundation import canonical_json


class CryovantRegistryStore:
    """Registry persistence adapter with deterministic JSON and SQLite backends."""

    def __init__(self, json_path: Path, *, sqlite_path: Path | None = None, backend: str = "json") -> None:
        if backend not in {"json", "sqlite"}:
            raise ValueError("invalid_state_backend")
        self.json_path = json_path
        self.sqlite_path = sqlite_path or json_path.with_suffix(".sqlite")
        self.backend = backend
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "sqlite":
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registry_entries (
                    name TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def load_registry(self) -> dict[str, dict[str, Any]]:
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as conn:
                rows = conn.execute(
                    "SELECT name, payload_json FROM registry_entries ORDER BY name ASC"
                ).fetchall()
            return {name: json.loads(payload_json) for name, payload_json in rows}

        if not self.json_path.exists():
            return {}
        try:
            payload = json.loads(self.json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        ordered = sorted(payload.items(), key=lambda item: str(item[0]))
        return {str(name): value for name, value in ordered if isinstance(value, dict)}

    def save_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        ordered = {name: registry[name] for name in sorted(registry)}
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute("DELETE FROM registry_entries")
                conn.executemany(
                    "INSERT INTO registry_entries(name, payload_json) VALUES (?, ?)",
                    [(name, canonical_json(payload)) for name, payload in ordered.items()],
                )
            return

        payload = json.dumps(ordered, indent=2, sort_keys=True, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.json_path.parent,
            prefix=f".{self.json_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            temp_path = Path(handle.name)
        temp_path.replace(self.json_path)

    def upsert(self, name: str, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        registry = self.load_registry()
        registry[name] = dict(payload)
        self.save_registry(registry)
        return registry

    def get(self, name: str) -> dict[str, Any] | None:
        return self.load_registry().get(name)
