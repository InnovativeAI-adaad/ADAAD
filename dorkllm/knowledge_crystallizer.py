# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/knowledge_crystallizer.py
DORK Persistent Memory (DPM) — Knowledge Crystallizer

INNOV-51 · Phase 145 · v9.78.0
Constitutional invariants: DPM-INJECT-0, DPM-GATE-0

Orchestration layer between the pattern detector and memory engine.
Provides the single public entry-point for the intelligence layer:

    crystallize(query, response)  → list of stored entry dicts
    inject_memory_block(query)    → str (formatted block for system prompt)

DPM-GATE-0: This module MUST NOT be disabled at runtime. Any attempt to
disable it via environment variable or flag must be rejected with a
constitutional violation log. The module is permanently active.

DPM-INJECT-0: inject_memory_block() must never propagate exceptions.
All errors are caught, logged to stderr, and return a safe empty string.
"""

from __future__ import annotations

import sys
from typing import Any

from dorkllm import memory_engine as _mem
from dorkllm import pattern_detector as _pd

# ── DPM-GATE-0: Permanent activation guard ────────────────────────────────────

import os as _os

_DISABLE_FLAG = _os.getenv("DPM_DISABLE", "").strip().lower()
if _DISABLE_FLAG in {"1", "true", "yes", "on"}:
    print(
        "[DPM-GATE-0 CONSTITUTIONAL VIOLATION] "
        "DPM_DISABLE flag detected. DPM is constitutionally permanent and "
        "cannot be disabled at runtime. Flag ignored.",
        file=sys.stderr,
    )


# ── Crystallisation pipeline ──────────────────────────────────────────────────

def crystallize(
    query: str,
    response: str = "",
    force_store: bool = False,
) -> list[dict[str, Any]]:
    """
    Run the full detect → filter → store pipeline.

    1. pattern_detector.detect_patterns(query, response)
    2. Filter patterns below crystallisation threshold (unless force_store)
    3. memory_engine.store_memory() for each qualifying pattern
    4. Return list of stored ledger entries

    DPM-INJECT-0: Exceptions are caught and logged; returns [] on failure.
    """
    stored: list[dict[str, Any]] = []
    try:
        patterns = _pd.detect_patterns(query, response)
        for pattern in patterns:
            if not force_store and not _pd.should_crystallise(pattern):
                continue
            try:
                entry = _mem.store_memory(
                    topic=pattern["topic"],
                    content=pattern["content"],
                    confidence=pattern["confidence"],
                    tags=pattern["tags"],
                    source=pattern.get("source", "knowledge_crystallizer"),
                )
                stored.append(entry)
            except ValueError:
                # DPM-CHAIN-0: confidence below threshold — skip silently
                pass
            except Exception as exc:  # noqa: BLE001
                print(f"[DPM crystallize error] {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[DPM crystallize fatal] {exc}", file=sys.stderr)
    return stored


# ── System prompt injection ───────────────────────────────────────────────────

def inject_memory_block(query: str) -> str:
    """
    DPM-INJECT-0: Retrieve relevant memories and format as a system-prompt block.
    NEVER raises. Returns empty string on any failure.

    Format:
        ### DORK PERSISTENT MEMORY
        [seq=N | topic | conf=0.XXX] content…
        …
    """
    try:
        ok, diag = _mem.verify_chain()
        if not ok:
            print(f"[DPM-CHAIN-0 VIOLATION] {diag}", file=sys.stderr)
            return ""

        entries = _mem.retrieve_relevant(query)
        if not entries:
            return ""

        lines = ["### DORK PERSISTENT MEMORY"]
        for entry in entries:
            p = entry["payload"]
            conf = p.get("confidence", 0.0)
            topic = p.get("topic", "?")
            content = p.get("content", "")
            seq = entry.get("seq", "?")
            lines.append(f"[seq={seq} | {topic} | conf={conf:.3f}] {content}")

        stats = _mem.memory_stats()
        lines.append(
            f"[DPM: {stats['active_memories']} active memories | "
            f"chain={stats['chain_length']} entries]"
        )
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        print(f"[DPM inject_memory_block error] {exc}", file=sys.stderr)
        return ""


# ── Convenience passthrough ───────────────────────────────────────────────────

def stats() -> dict[str, Any]:
    """Return memory statistics (passthrough to memory_engine)."""
    try:
        return _mem.memory_stats()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def verify() -> tuple[bool, str]:
    """Verify chain integrity (passthrough to memory_engine)."""
    try:
        return _mem.verify_chain()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
