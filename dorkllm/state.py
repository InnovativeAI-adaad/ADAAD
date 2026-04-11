# SPDX-License-Identifier: Apache-2.0
# DORK State Bus Interface Module
# Phase 137 · INNOV-44 · DORK Intelligence Hardening & Capability Expansion
# Constitutional invariants: DORK-STATE-0, DORK-PROV-0, DORK-LEDGER-HASH-0

import http.client
import json
import os
import hashlib
from datetime import datetime, timezone

PORT = int(os.getenv("ADAAD_PORT", "8000"))

# ── DORK-STATE-0 ──────────────────────────────────────────────────────────────
# Hard invariant: ConversationLedger entries are append-only and hash-chained.
# Any attempt to mutate a prior entry raises ConversationLedgerViolation.
# ─────────────────────────────────────────────────────────────────────────────

# ── DORK-PROV-0 ───────────────────────────────────────────────────────────────
# Hard invariant: ProviderHealthRegistry must record all provider probe outcomes.
# Unhealthy providers must not be silently skipped — callers must receive
# a structured ProviderStatus with healthy=False before fallback is used.
# ─────────────────────────────────────────────────────────────────────────────

# ── DORK-LEDGER-HASH-0 ────────────────────────────────────────────────────────
# Hard invariant: ConversationLedger._hash_entry() MUST include the `seq` field
# in its canonical hash payload, producing schema parity with
# DorkLedgerPersistence. Cross-layer hydration (persist→memory) requires
# identical hash schemas — any divergence is a constitutionally prohibited
# chain integrity violation.
# ─────────────────────────────────────────────────────────────────────────────


class ConversationLedgerViolation(RuntimeError):
    """Raised when ConversationLedger append-only invariant is violated."""


class ConversationLedger:
    """
    Append-only, hash-chained record of all DORK conversation turns.

    Each entry stores: seq, role, content digest, timestamp, prev_hash, entry_hash.
    The chain is verifiable end-to-end — no silent mutation is possible.

    DORK-LEDGER-HASH-0: hash payload includes seq for DorkLedgerPersistence parity.
    """

    GENESIS_HASH = "0" * 64

    def __init__(self):
        self._entries: list[dict] = []
        self._prev_hash: str = self.GENESIS_HASH

    def _hash_entry(
        self, seq: int, role: str, content_digest: str, timestamp: str, prev_hash: str
    ) -> str:
        """
        DORK-LEDGER-HASH-0: canonical hash payload includes seq, role,
        content_digest, timestamp, prev_hash — matching DorkLedgerPersistence.
        """
        payload = json.dumps(
            {
                "seq": seq,
                "role": role,
                "content_digest": content_digest,
                "timestamp": timestamp,
                "prev_hash": prev_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def append(self, role: str, content: str) -> dict:
        """Append a new turn to the ledger. Returns the sealed entry."""
        self._validate_role(role)
        seq = len(self._entries)
        timestamp = datetime.now(timezone.utc).isoformat()
        content_digest = hashlib.sha256(content.encode()).hexdigest()[:24]
        entry_hash = self._hash_entry(seq, role, content_digest, timestamp, self._prev_hash)
        entry = {
            "seq": seq,
            "role": role,
            "content_digest": content_digest,
            "timestamp": timestamp,
            "prev_hash": self._prev_hash,
            "entry_hash": entry_hash,
        }
        self._entries.append(entry)
        self._prev_hash = entry_hash
        return entry

    def restore_entry(
        self,
        *,
        seq: int,
        role: str,
        content_digest: str,
        timestamp: str,
        prev_hash: str,
        entry_hash: str,
    ) -> dict:
        """
        Restore a precomputed ledger entry from an authoritative chain source.

        DORK-LEDGER-HASH-0: recomputes hash using seq-inclusive canonical schema
        to ensure cross-layer chain continuity with DorkLedgerPersistence.

        Invariants enforced:
        - role must be canonical
        - seq must be contiguous append index
        - prev_hash must equal current chain tail hash
        - entry_hash must match canonical recomputation (seq-inclusive)
        """
        self._validate_role(role)
        expected_seq = len(self._entries)
        if seq != expected_seq:
            raise ConversationLedgerViolation(
                f"Invalid seq continuity: expected {expected_seq}, got {seq}"
            )
        if prev_hash != self._prev_hash:
            raise ConversationLedgerViolation(
                "Invalid prev_hash continuity: restore entry does not chain from ledger tail"
            )
        expected_hash = self._hash_entry(seq, role, content_digest, timestamp, prev_hash)
        if entry_hash != expected_hash:
            raise ConversationLedgerViolation(
                "Invalid entry_hash: canonical recomputation mismatch during restore "
                f"(expected={expected_hash[:12]}…, got={entry_hash[:12]}…)"
            )
        entry = {
            "seq": seq,
            "role": role,
            "content_digest": content_digest,
            "timestamp": timestamp,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }
        self._entries.append(entry)
        self._prev_hash = entry_hash
        return entry

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ("user", "assistant", "system"):
            raise ConversationLedgerViolation(f"Invalid role: {role!r}")

    def verify(self) -> tuple[bool, str]:
        """Re-derive chain from genesis using seq-inclusive hash schema. Returns (valid, reason)."""
        prev = self.GENESIS_HASH
        for i, e in enumerate(self._entries):
            if e["prev_hash"] != prev:
                return False, f"Chain break at seq={i}: prev_hash mismatch"
            expected = self._hash_entry(
                e["seq"], e["role"], e["content_digest"], e["timestamp"], prev
            )
            if e["entry_hash"] != expected:
                return False, f"Chain break at seq={i}: entry_hash mismatch"
            prev = e["entry_hash"]
        return True, "chain_valid"

    def tail(self, n: int = 5) -> list[dict]:
        return self._entries[-n:]

    def __len__(self) -> int:
        return len(self._entries)


# ── Provider Health ────────────────────────────────────────────────────────────

class ProviderStatus:
    def __init__(self, name: str, healthy: bool, latency_ms: float, error: str | None = None):
        self.name = name
        self.healthy = healthy
        self.latency_ms = latency_ms
        self.error = error
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "timestamp": self.timestamp,
        }


class ProviderHealthRegistry:
    """
    Tracks health probes for all LLM provider backends.
    Maintains a configurable rolling window of probe results per provider.
    """

    DEFAULT_WINDOW_SIZE = int(os.getenv("DORK_PROVIDER_WINDOW_SIZE", "20"))

    def __init__(self, window_size: int | None = None):
        self._window_size = window_size if window_size is not None else self.DEFAULT_WINDOW_SIZE
        self._registry: dict[str, list[ProviderStatus]] = {}

    def record(self, status: ProviderStatus) -> None:
        """Record a probe result for a provider. DORK-PROV-0: never silently skips."""
        bucket = self._registry.setdefault(status.name, [])
        bucket.append(status)
        if len(bucket) > self._window_size:
            bucket.pop(0)

    def is_healthy(self, name: str) -> bool:
        """Return True if the most recent probe for this provider was healthy."""
        bucket = self._registry.get(name)
        if not bucket:
            return False
        return bucket[-1].healthy

    def availability(self, name: str) -> float:
        """Return fraction of recent probes that were healthy (0.0–1.0)."""
        bucket = self._registry.get(name)
        if not bucket:
            return 0.0
        return sum(1 for s in bucket if s.healthy) / len(bucket)

    def circuit_open(self, name: str, min_probes: int = 3, threshold: float = 0.34) -> bool:
        """
        Return True if the circuit breaker should trip for this provider.
        Circuit opens when availability < threshold over at least min_probes.
        Prevents repeated calls to a failing backend.
        """
        bucket = self._registry.get(name)
        if not bucket or len(bucket) < min_probes:
            return False
        return self.availability(name) < threshold

    def summary(self) -> dict:
        return {
            name: {
                "healthy": self.is_healthy(name),
                "availability": round(self.availability(name), 3),
                "circuit_open": self.circuit_open(name),
                "probe_count": len(bucket),
                "last_error": next(
                    (s.error for s in reversed(bucket) if s.error), None
                ),
            }
            for name, bucket in self._registry.items()
        }


# ── Legacy state-bus helpers ──────────────────────────────────────────────────

def fetch_adaad_state():
    """Fetches the full system state from the live ADAAD server."""
    state = {}
    try:
        conn = http.client.HTTPConnection("localhost", PORT, timeout=1.0)

        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        if resp.status == 200:
            state["health"] = json.loads(resp.read().decode())

        conn.request("GET", "/api/governance/health")
        resp = conn.getresponse()
        if resp.status == 200:
            state["governance"] = json.loads(resp.read().decode())

        conn.request("GET", "/api/readiness")
        resp = conn.getresponse()
        if resp.status == 200:
            state["readiness"] = json.loads(resp.read().decode())

        conn.close()
    except Exception:
        pass
    return state


def get_state_summary() -> str:
    """Returns a condensed string summary of the system state for the LLM."""
    state = fetch_adaad_state()
    if not state:
        return "STATE BUS: UNAVAILABLE (Local Server Down)"

    summary = ["### LIVE STATE BUS SUMMARY"]
    health = state.get("health", {})
    gov = state.get("governance", {})
    readiness = state.get("readiness", {})

    summary.append(f"- Gate Status: {'🔴 LOCKED' if gov.get('gate', {}).get('locked') else '🟢 PASS'}")
    summary.append(f"- Epoch/Phase: {health.get('epoch', '—')} / {health.get('phase', '—')}")
    summary.append(f"- Readiness: {readiness.get('readiness_score', 0.0):.2f}")

    return "\n".join(summary)
