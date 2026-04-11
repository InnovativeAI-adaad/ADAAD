# SPDX-License-Identifier: Apache-2.0
"""
WORK-66-B gate tests — LineageLedgerV2 streaming verification invariants.

Closes: FINDING-66-005

Three invariants verified:

  INV-LINEAGE-STREAM-1:
    _verified_tail_hash MUST be None on fresh instantiation (reload).
    Cache must not survive a new LineageLedgerV2() instantiation from the
    same path; each instance starts cold.

  INV-LINEAGE-STREAM-2:
    verify_integrity(max_lines=k) for k < total entries MUST set
    _verified_tail_hash to the last verified prefix hash (not full-chain tip).

  INV-LINEAGE-STREAM-3:
    append_event() on a warm cache (non-None _verified_tail_hash) MUST NOT
    re-scan the full ledger. One full scan per cold-start only.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.regression_standard

from runtime.evolution.lineage_v2 import LineageLedgerV2, _TAIL_CACHE, _TAIL_CACHE_LOCK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ledger_with_entries(path: Path, n: int) -> LineageLedgerV2:
    """Create a fresh ledger at *path* and append *n* events."""
    ledger = LineageLedgerV2(path)
    for i in range(n):
        ledger.append_event("test_event", {"seq": i})
    return ledger


# ---------------------------------------------------------------------------
# INV-LINEAGE-STREAM-1: reload clears cache
# ---------------------------------------------------------------------------

class TestInvLineageStream1ReloadClearsCache:
    """_verified_tail_hash MUST be None on new instantiation from same path."""

    def test_fresh_instance_has_none_tail_hash(self, tmp_path):
        """New instance starts with _verified_tail_hash = None (cold)."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = LineageLedgerV2(ledger_path)
        assert ledger._verified_tail_hash is None

    def test_cache_set_after_full_verify(self, tmp_path):
        """Full verify_integrity() sets _verified_tail_hash to a non-None value."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 3)
        # After appends the cache is warm; reset it to test verify path
        ledger._verified_tail_hash = None
        ledger.verify_integrity()
        assert ledger._verified_tail_hash is not None

    def test_new_instance_same_path_starts_cold(self, tmp_path):
        """A second LineageLedgerV2 pointing at the same file starts cold."""
        ledger_path = tmp_path / "ledger.jsonl"
        first = _ledger_with_entries(ledger_path, 4)
        # first has warm cache after appends
        assert first._verified_tail_hash is not None

        second = LineageLedgerV2(ledger_path)
        # second is a new instance — cache must be None until it verifies
        assert second._verified_tail_hash is None, (
            "Reload must not inherit the cache from a prior instance. "
            "INV-LINEAGE-STREAM-1 violated."
        )

    def test_reload_instance_can_warm_cache_by_verify(self, tmp_path):
        """Reloaded instance can warm its own cache via verify_integrity()."""
        ledger_path = tmp_path / "ledger.jsonl"
        _ledger_with_entries(ledger_path, 3)

        reloaded = LineageLedgerV2(ledger_path)
        assert reloaded._verified_tail_hash is None  # cold
        reloaded.verify_integrity()
        assert reloaded._verified_tail_hash is not None  # now warm

    def test_reload_tail_hash_matches_original(self, tmp_path):
        """Reloaded and verified tail hash must match the original chain tail."""
        ledger_path = tmp_path / "ledger.jsonl"
        original = _ledger_with_entries(ledger_path, 5)
        original_tail = original._verified_tail_hash

        reloaded = LineageLedgerV2(ledger_path)
        reloaded.verify_integrity()
        assert reloaded._verified_tail_hash == original_tail, (
            "Hash chain tail must be deterministic across instances."
        )


# ---------------------------------------------------------------------------
# INV-LINEAGE-STREAM-2: partial scan must NOT set cache
# ---------------------------------------------------------------------------

class TestInvLineageStream2PartialScanNoCachePoison:
    """verify_integrity(max_lines=k) for k < total sets verified prefix tail hash."""

    def test_partial_verify_sets_verified_prefix_tail_hash(self, tmp_path):
        """Truncated verification sets _verified_tail_hash to verified prefix tail."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 6)
        expected_prefix_tail = ledger.read_all()[2]["hash"]
        # Force cold cache so verify_integrity owns the update.
        ledger._verified_tail_hash = None
        # Verify only first 3 of 6 entries
        ledger.verify_integrity(max_lines=3)
        assert ledger._verified_tail_hash == expected_prefix_tail, (
            "Partial verify must cache the last verified prefix tail hash. "
            "INV-LINEAGE-STREAM-2 violated."
        )

    def test_full_verify_does_set_tail_hash(self, tmp_path):
        """Control: full verify (no max_lines) DOES set _verified_tail_hash."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 6)
        ledger._verified_tail_hash = None
        ledger.verify_integrity()  # no max_lines → full scan
        assert ledger._verified_tail_hash is not None

    def test_max_lines_equal_to_total_sets_tail_hash(self, tmp_path):
        """verify_integrity(max_lines=n) where n == total entries sets the cache."""
        ledger_path = tmp_path / "ledger.jsonl"
        n = 4
        ledger = _ledger_with_entries(ledger_path, n)
        ledger._verified_tail_hash = None
        # max_lines == total → full scan completes without early return
        ledger.verify_integrity(max_lines=n)
        assert ledger._verified_tail_hash is not None

    def test_max_lines_exceeds_total_sets_tail_hash(self, tmp_path):
        """verify_integrity(max_lines > total) scans all entries, sets cache."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 3)
        ledger._verified_tail_hash = None
        ledger.verify_integrity(max_lines=999)
        assert ledger._verified_tail_hash is not None

    def test_partial_then_full_verify_sets_cache(self, tmp_path):
        """Partial verify followed by full verify correctly sets _verified_tail_hash."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 5)
        expected_prefix_tail = ledger.read_all()[1]["hash"]
        ledger._verified_tail_hash = None
        ledger.verify_integrity(max_lines=2)   # partial — cache set to prefix tail
        assert ledger._verified_tail_hash == expected_prefix_tail
        ledger.verify_integrity()              # full — cache set
        assert ledger._verified_tail_hash is not None


# ---------------------------------------------------------------------------
# INV-LINEAGE-STREAM-3: warm-cache append must not re-scan
# ---------------------------------------------------------------------------

class TestInvLineageStream3WarmCacheNoRescan:
    """append_event() on warm cache must not call verify_integrity() (no re-scan)."""

    def test_warm_cache_append_skips_verify_integrity(self, tmp_path):
        """With _verified_tail_hash set, append_event() must not re-scan."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 3)
        # Cache is warm after appends
        assert ledger._verified_tail_hash is not None

        call_count = {"n": 0}
        original_verify = ledger.verify_integrity

        def counting_verify(*args, **kwargs):
            call_count["n"] += 1
            return original_verify(*args, **kwargs)

        with patch.object(ledger, "verify_integrity", side_effect=counting_verify):
            ledger.append_event("test_event", {"seq": 99})

        assert call_count["n"] == 0, (
            f"verify_integrity called {call_count['n']} time(s) on a warm-cache append. "
            "INV-LINEAGE-STREAM-3 violated: O(n) re-scan must not occur on warm path."
        )

    def test_cold_cache_append_uses_tail_scan_without_verify(self, tmp_path):
        """Cold append uses tail scan path and does not call verify_integrity()."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 3)
        # Force cold cache
        ledger._verified_tail_hash = None
        with _TAIL_CACHE_LOCK:
            _TAIL_CACHE.pop(str(ledger_path.resolve()), None)

        call_count = {"n": 0}
        original_verify = ledger.verify_integrity

        def counting_verify(*args, **kwargs):
            call_count["n"] += 1
            return original_verify(*args, **kwargs)

        with patch.object(ledger, "verify_integrity", side_effect=counting_verify):
            ledger.append_event("test_event", {"seq": 100})

        assert call_count["n"] == 0, (
            f"Expected 0 verify calls on cold-path append, got {call_count['n']}."
        )

    def test_successive_warm_appends_do_not_rescan(self, tmp_path):
        """Multiple successive appends on a warm cache never trigger re-scan."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 2)
        assert ledger._verified_tail_hash is not None

        call_count = {"n": 0}
        original_verify = ledger.verify_integrity

        def counting_verify(*args, **kwargs):
            call_count["n"] += 1
            return original_verify(*args, **kwargs)

        with patch.object(ledger, "verify_integrity", side_effect=counting_verify):
            for i in range(5):
                ledger.append_event("test_event", {"seq": i + 10})

        assert call_count["n"] == 0, (
            f"verify_integrity called {call_count['n']} times across 5 warm appends. "
            "Each warm append must advance the cache without re-scanning."
        )

    def test_cache_advances_after_each_warm_append(self, tmp_path):
        """After each warm append, _verified_tail_hash advances to new entry hash."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = _ledger_with_entries(ledger_path, 2)
        tail_before = ledger._verified_tail_hash

        entry = ledger.append_event("test_event", {"seq": 50})
        tail_after = ledger._verified_tail_hash

        assert tail_after == entry["hash"], (
            "Warm-cache append must set _verified_tail_hash to the new entry hash."
        )
        assert tail_after != tail_before, (
            "Cache must advance after each append."
        )
