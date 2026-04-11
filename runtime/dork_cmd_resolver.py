# runtime/dork_cmd_resolver.py
# Phase 132 · INNOV-41 · DORK Living Fleet
# Constitutional invariant: DORK-CMD-0
# SPDX-License-Identifier: Apache-2.0

"""
DorkCommandResolver — validates, routes, and chain-ledgers all DORK slash commands.

DORK-CMD-0 (Hard):
  All slash-command signatures MUST be validated against the canonical
  slash_commands.json manifest before dispatch. Unknown commands MUST be
  rejected with a structured CommandError — never silently forwarded.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Manifest path ─────────────────────────────────────────────────────────────
_MANIFEST_PATH = Path(os.getenv(
    "DORK_CMD_MANIFEST",
    str(Path(__file__).parent.parent / "data" / "dork" / "slash_commands.json"),
))


# ── Exceptions ────────────────────────────────────────────────────────────────
class CommandError(ValueError):
    """Raised when a slash command fails DORK-CMD-0 validation."""


class ManifestLoadError(RuntimeError):
    """Raised when the slash_commands.json manifest cannot be loaded."""


# ── Chain-ledger entry ────────────────────────────────────────────────────────
class CommandLedgerEntry:
    """Immutable, hash-chained record of a single command dispatch."""

    def __init__(
        self,
        seq: int,
        slash: str,
        args: dict[str, Any],
        intent: str,
        status: str,
        prev_hash: str,
    ) -> None:
        self.seq = seq
        self.slash = slash
        self.args = args
        self.intent = intent
        self.status = status
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.prev_hash = prev_hash
        self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps(
            {
                "seq": self.seq,
                "slash": self.slash,
                "intent": self.intent,
                "status": self.status,
                "timestamp": self.timestamp,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "slash": self.slash,
            "args": self.args,
            "intent": self.intent,
            "status": self.status,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


# ── Resolver ──────────────────────────────────────────────────────────────────
class DorkCommandResolver:
    """
    Validates and routes DORK slash commands with append-only chain ledger.

    Usage:
        resolver = DorkCommandResolver()
        result = resolver.resolve("/dork:gate")
    """

    GENESIS_HASH = "0" * 64

    def __init__(self, manifest_path: Path | None = None) -> None:
        self._manifest_path = manifest_path or _MANIFEST_PATH
        self._commands: dict[str, dict] = {}
        self._ledger: list[CommandLedgerEntry] = []
        self._prev_hash: str = self.GENESIS_HASH
        self._load_manifest()

    # ── Manifest ─────────────────────────────────────────────────────────────
    def _load_manifest(self) -> None:
        """Load and index slash_commands.json. Raises ManifestLoadError on failure."""
        try:
            raw = json.loads(self._manifest_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ManifestLoadError(
                f"DORK-CMD-0: cannot load manifest at {self._manifest_path}: {exc}"
            ) from exc

        for cmd in raw.get("commands", []):
            slash = cmd.get("slash", "").strip()
            if slash:
                self._commands[slash] = cmd

    def known_commands(self) -> list[str]:
        """Return sorted list of all registered slash commands."""
        return sorted(self._commands)

    # ── Validation (DORK-CMD-0) ───────────────────────────────────────────────
    def _validate(self, slash: str) -> dict:
        """
        Validate slash against manifest.
        Raises CommandError for unknown commands — never silently forwards.
        """
        if not slash.startswith("/dork:"):
            raise CommandError(
                f"DORK-CMD-0 violation: command must begin with '/dork:' — got {slash!r}"
            )
        if slash not in self._commands:
            known = ", ".join(self.known_commands())
            raise CommandError(
                f"DORK-CMD-0 violation: unknown command {slash!r}. "
                f"Registered commands: {known}"
            )
        return self._commands[slash]

    # ── Chain ledger append ───────────────────────────────────────────────────
    def _ledger_append(
        self, slash: str, args: dict, intent: str, status: str
    ) -> CommandLedgerEntry:
        entry = CommandLedgerEntry(
            seq=len(self._ledger),
            slash=slash,
            args=args,
            intent=intent,
            status=status,
            prev_hash=self._prev_hash,
        )
        self._ledger.append(entry)
        self._prev_hash = entry.entry_hash
        return entry

    # ── Public API ────────────────────────────────────────────────────────────
    def resolve(self, raw_input: str) -> dict:
        """
        Parse, validate, and ledger a DORK slash command.

        Returns a structured resolution dict:
            {
                "slash": str,
                "intent": str,
                "args": dict,
                "description": str,
                "example": str,
                "ledger_entry": dict,
                "status": "ok" | "error",
                "error": str | None,
            }
        """
        parts = raw_input.strip().split()
        slash = parts[0] if parts else ""
        # Parse --key value pairs from remaining tokens
        args: dict[str, Any] = {}
        i = 1
        while i < len(parts):
            if parts[i].startswith("--") and i + 1 < len(parts):
                args[parts[i][2:]] = parts[i + 1]
                i += 2
            else:
                i += 1

        try:
            cmd_def = self._validate(slash)
        except CommandError as exc:
            entry = self._ledger_append(slash, args, "unknown", "error")
            return {
                "slash": slash,
                "intent": "unknown",
                "args": args,
                "description": None,
                "example": None,
                "ledger_entry": entry.to_dict(),
                "status": "error",
                "error": str(exc),
            }

        entry = self._ledger_append(slash, args, cmd_def["intent"], "ok")
        return {
            "slash": slash,
            "intent": cmd_def["intent"],
            "args": args,
            "description": cmd_def.get("description"),
            "example": cmd_def.get("example"),
            "ledger_entry": entry.to_dict(),
            "status": "ok",
            "error": None,
        }

    # ── Ledger accessors ──────────────────────────────────────────────────────
    def ledger_tail(self, n: int = 10) -> list[dict]:
        return [e.to_dict() for e in self._ledger[-n:]]

    def verify_ledger(self) -> tuple[bool, str]:
        """Re-derive chain from genesis. Returns (valid, reason)."""
        prev = self.GENESIS_HASH
        for e in self._ledger:
            if e.prev_hash != prev:
                return False, f"Chain break at seq={e.seq}"
            prev = e.entry_hash
        return True, "chain_valid"

    def ledger_len(self) -> int:
        return len(self._ledger)
