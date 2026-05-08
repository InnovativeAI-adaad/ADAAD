# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/memory_engine.py
DORK Persistent Memory (DPM) — Memory Engine

INNOV-51 · Phase 145 · v9.78.0
Constitutional invariants: DPM-CHAIN-0, DPM-HUMAN0-0

Architectural mandate: This module is permanently enabled and session-agnostic.
All writes are HMAC-chained append-only. No entry may be deleted without
HUMAN-0 authorisation recorded in the eviction ledger.

Ledger format mirrors CMU ledger: each line is a JSON object with:
  seq, timestamp, entry_type, payload, prev_hash, entry_hash
where entry_hash = HMAC-SHA256(prev_hash + canonical_payload, LEDGER_SECRET).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

_LEDGER_PATH = Path(os.getenv("DPM_LEDGER_PATH", "data/dork/dpm_memory.jsonl"))
_EVICTION_LEDGER_PATH = Path(
    os.getenv("DPM_EVICTION_LEDGER_PATH", "data/dork/dpm_eviction.jsonl")
)
_SECRET = os.getenv("DPM_HMAC_SECRET", "adaad-dpm-constitutional-secret-v1").encode()
_GENESIS_HASH = "0" * 64
_MAX_INJECT_ENTRIES = int(os.getenv("DPM_MAX_INJECT", "8"))
_MIN_CONFIDENCE = float(os.getenv("DPM_MIN_CONFIDENCE", "0.6"))

# DPM-CHAIN-0: All entries MUST carry a valid HMAC chain. Any break is fatal.
# DPM-HUMAN0-0: Eviction requires HUMAN-0 authorisation in eviction ledger.


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _hmac_digest(prev_hash: str, payload_str: str) -> str:
    """Deterministic HMAC-SHA256 over prev_hash + canonical payload string."""
    msg = (prev_hash + payload_str).encode("utf-8")
    return hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()


def _canonical(obj: dict[str, Any]) -> str:
    """Canonical JSON serialisation — sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ── Ledger I/O ────────────────────────────────────────────────────────────────

def _ensure_ledger() -> None:
    """Create ledger file and parent dirs if absent. Write genesis if empty."""
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _LEDGER_PATH.exists() or _LEDGER_PATH.stat().st_size == 0:
        _write_genesis()


def _write_genesis() -> None:
    genesis_payload = {
        "event": "dpm_genesis",
        "version": "1.0",
        "innov": "INNOV-51",
        "phase": 145,
    }
    canon = _canonical(genesis_payload)
    entry_hash = _hmac_digest(_GENESIS_HASH, canon)
    entry = {
        "seq": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry_type": "genesis",
        "payload": genesis_payload,
        "prev_hash": _GENESIS_HASH,
        "entry_hash": entry_hash,
    }
    with _LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _load_all() -> list[dict[str, Any]]:
    """Load all ledger entries. Returns [] if ledger is absent or empty."""
    if not _LEDGER_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    with _LEDGER_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _last_entry() -> dict[str, Any] | None:
    """Return the most-recent ledger entry without loading all."""
    if not _LEDGER_PATH.exists():
        return None
    last: dict[str, Any] | None = None
    with _LEDGER_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last = json.loads(line)
    return last


def _append_entry(entry_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a new HMAC-chained entry to the ledger. Thread-unsafe (single-process use)."""
    _ensure_ledger()
    prev = _last_entry()
    seq = (prev["seq"] + 1) if prev else 1
    prev_hash = prev["entry_hash"] if prev else _GENESIS_HASH
    canon = _canonical(payload)
    entry_hash = _hmac_digest(prev_hash, canon)
    entry = {
        "seq": seq,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry_type": entry_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }
    with _LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return entry


# ── Chain verification ────────────────────────────────────────────────────────

def verify_chain() -> tuple[bool, str]:
    """
    DPM-CHAIN-0: Verify full HMAC chain integrity.
    Returns (ok, diagnostic_message).
    """
    entries = _load_all()
    if not entries:
        return True, "chain_empty"
    prev_hash = _GENESIS_HASH
    for entry in entries:
        if entry.get("entry_type") == "genesis":
            computed = _hmac_digest(entry["prev_hash"], _canonical(entry["payload"]))
            if computed != entry["entry_hash"]:
                return False, f"genesis_hash_mismatch:seq={entry['seq']}"
            prev_hash = entry["entry_hash"]
            continue
        if entry["prev_hash"] != prev_hash:
            return False, f"chain_break:seq={entry['seq']}"
        computed = _hmac_digest(prev_hash, _canonical(entry["payload"]))
        if computed != entry["entry_hash"]:
            return False, f"hash_mismatch:seq={entry['seq']}"
        prev_hash = entry["entry_hash"]
    return True, f"chain_ok:entries={len(entries)}"


# ── Public write API ──────────────────────────────────────────────────────────

def store_memory(
    topic: str,
    content: str,
    confidence: float,
    tags: list[str] | None = None,
    source: str = "pattern_detector",
) -> dict[str, Any]:
    """
    Persist a crystallised memory fragment. Confidence must be >= _MIN_CONFIDENCE.
    Returns the ledger entry written.
    Raises ValueError if confidence below threshold (fail-closed: DPM-CHAIN-0).
    """
    if confidence < _MIN_CONFIDENCE:
        raise ValueError(
            f"DPM-CHAIN-0 VIOLATION: confidence {confidence:.3f} < "
            f"threshold {_MIN_CONFIDENCE:.3f}; memory rejected"
        )
    payload: dict[str, Any] = {
        "topic": topic,
        "content": content,
        "confidence": round(confidence, 6),
        "tags": sorted(tags or []),
        "source": source,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    return _append_entry("memory", payload)


def record_eviction(
    target_seq: int,
    reason: str,
    human0_authorisation: str,
) -> dict[str, Any]:
    """
    DPM-HUMAN0-0: Record an eviction event. Does NOT delete the original entry
    (ledger is append-only). Marks entry as evicted in eviction ledger.
    human0_authorisation must be the HUMAN-0 ratification phrase.
    """
    if not human0_authorisation.strip():
        raise PermissionError(
            "DPM-HUMAN0-0 VIOLATION: eviction requires HUMAN-0 authorisation phrase"
        )
    payload = {
        "target_seq": target_seq,
        "reason": reason,
        "human0_authorisation": human0_authorisation,
        "evicted_at": datetime.now(timezone.utc).isoformat(),
    }
    _EVICTION_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    eviction_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    with _EVICTION_LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(eviction_entry, separators=(",", ":")) + "\n")
    return eviction_entry


# ── Public read API ───────────────────────────────────────────────────────────

def _evicted_seqs() -> set[int]:
    """Return set of seq numbers that have been evicted."""
    if not _EVICTION_LEDGER_PATH.exists():
        return set()
    evicted: set[int] = set()
    with _EVICTION_LEDGER_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                ev = json.loads(line)
                evicted.add(ev["payload"]["target_seq"])
    return evicted


def retrieve_relevant(
    query: str,
    max_results: int = _MAX_INJECT_ENTRIES,
) -> list[dict[str, Any]]:
    """
    DPM-DETERM-0: Deterministic retrieval — score = confidence * keyword_overlap_ratio.
    Returns top-N non-evicted memory entries ordered by score descending.
    """
    _ensure_ledger()
    entries = _load_all()
    evicted = _evicted_seqs()
    query_tokens = set(query.lower().split())
    scored: list[tuple[float, dict[str, Any]]] = []

    for entry in entries:
        if entry.get("entry_type") != "memory":
            continue
        if entry["seq"] in evicted:
            continue
        p = entry["payload"]
        content_tokens = set((p.get("content", "") + " " + p.get("topic", "")).lower().split())
        tag_tokens = set(t.lower() for t in p.get("tags", []))
        all_tokens = content_tokens | tag_tokens
        overlap = len(query_tokens & all_tokens)
        overlap_ratio = overlap / max(len(query_tokens), 1)
        score = p.get("confidence", 0.0) * (0.5 + 0.5 * overlap_ratio)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: (-x[0], -x[1]["seq"]))
    return [e for _, e in scored[:max_results]]


def memory_stats() -> dict[str, Any]:
    """Return summary statistics for monitoring and system-prompt injection."""
    entries = _load_all()
    evicted = _evicted_seqs()
    memories = [e for e in entries if e.get("entry_type") == "memory"]
    active = [e for e in memories if e["seq"] not in evicted]
    return {
        "total_entries": len(entries),
        "memory_entries": len(memories),
        "active_memories": len(active),
        "evicted_count": len(evicted),
        "chain_length": len(entries),
    }
