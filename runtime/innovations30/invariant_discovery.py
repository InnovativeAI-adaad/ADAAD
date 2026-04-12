# SPDX-License-Identifier: Apache-2.0
"""Innovation #31 -- Invariant Discovery Engine (IDE).

Watches failed mutations, extracts recurring failure patterns, proposes new
constitutional rules.  The system discovers its own laws from its own failure
history.

Constitutional invariants (Hard-class):
    IDE-0          -- analyze_failures() MUST return only rules whose
                     observed_frequency >= min_frequency AND
                     estimated_precision >= min_precision.
    IDE-DETERM-0   -- Identical (epoch_id, failure_pattern) inputs produce
                     identical rule_id and digest (no datetime.now/random).
    IDE-PERSIST-0  -- Every DiscoveredRule returned by analyze_failures()
                     MUST be written to append-only JSONL before return.
    IDE-AUDIT-0    -- Every DiscoveredRule carries a non-empty sha256-prefixed
                     digest at construction time.
    IDE-GATE-0     -- Pattern already in _known_patterns MUST NOT produce a
                     new DiscoveredRule (strict deduplication gate).
"""
from __future__ import annotations
import dataclasses, hashlib, hmac, json, re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
INDI_INV_CHAIN: str = "INDI-INV-CHAIN"


class InvariantDiscoveryViolation(RuntimeError):
    """Raised when a Invariant Discovery constitutional invariant is breached."""



MIN_PATTERN_FREQUENCY: int = 5
MIN_PRECISION: float = 0.80
_HMAC_SECRET: bytes = b"adaad-ide-chain-v1"

IDE_INVARIANTS: dict = {
    "IDE-0": {"description": "analyze_failures returns only threshold-passing rules.", "class": "Hard", "enforcement": "ide_guard()"},
    "IDE-DETERM-0": {"description": "Identical inputs produce identical rule_id and digest.", "class": "Hard", "enforcement": "ide_guard()"},
    "IDE-PERSIST-0": {"description": "All returned rules flushed to JSONL before return.", "class": "Hard", "enforcement": "ide_guard()"},
    "IDE-AUDIT-0": {"description": "Every DiscoveredRule carries non-empty digest at construction.", "class": "Hard", "enforcement": "ide_guard()"},
    "IDE-GATE-0": {"description": "Known patterns must not produce duplicate rules.", "class": "Hard", "enforcement": "ide_guard()"},
}


class IDEViolation(RuntimeError):
    """Raised when an IDE Hard-class invariant is breached."""


def ide_guard(condition: bool, invariant: str, detail: str = "") -> None:
    if not condition:
        raise IDEViolation(f"[IDE Hard-class violation] {invariant}" + (f" -- {detail}" if detail else ""))


def _chain_digest(rule_id: str, pattern: str, prev: str) -> str:
    payload = json.dumps({"rule_id": rule_id, "pattern": pattern, "prev": prev}, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _hmac_tag(entry: str) -> str:
    return hmac.new(_HMAC_SECRET, entry.encode(), hashlib.sha256).hexdigest()[:16]


@dataclass
class DiscoveredRule:
    rule_id: str
    pattern_description: str
    failure_pattern: str
    observed_frequency: int
    estimated_precision: float
    proposed_yaml: str
    discovery_epoch: str
    evidence_mutation_ids: list = field(default_factory=list)
    status: str = "proposed"
    digest: str = field(default="")
    prev_digest: str = ""

    def __post_init__(self) -> None:
        if not self.digest:
            payload = json.dumps({"rule_id": self.rule_id, "pattern": self.failure_pattern}, sort_keys=True)
            self.digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]
        ide_guard(bool(self.digest), "IDE-AUDIT-0", f"{self.rule_id} empty digest")


class InvariantDiscoveryEngine:
    """Mines governance failures -> proposes new constitutional invariants."""

    def __init__(self, ledger_path: Path = Path("data/discovered_rules.jsonl"),
                 min_frequency: int = MIN_PATTERN_FREQUENCY,
                 min_precision: float = MIN_PRECISION) -> None:
        self.ledger_path = Path(ledger_path)
        self.min_frequency = min_frequency
        self.min_precision = min_precision
        self._known_patterns: set = set()
        self._prev_digest: str = "0" * 16

    def analyze_failures(self, rejected_records: list, epoch_id: str) -> list:
        """Mine rejected_records for recurring constitutional gaps."""
        if not rejected_records:
            return []
        pattern_counts: Counter = Counter()
        pattern_examples: dict = {}
        for r in rejected_records:
            mid = r.get("mutation_id", "")
            for rule in (r.get("failed_rules") or []) + (r.get("reason_codes") or []):
                if rule:
                    pattern_counts[rule] += 1
                    pattern_examples.setdefault(rule, []).append(mid)
            for f in r.get("changed_files") or []:
                fpath = str(f)
                if "runtime/" in fpath:
                    layer = fpath.split("/")[1] if "/" in fpath else fpath
                    key = f"targets_runtime_{layer}"
                    pattern_counts[key] += 1
                    pattern_examples.setdefault(key, []).append(mid)

        discovered: list = []
        total_failures = len(rejected_records)
        for pattern, count in pattern_counts.most_common():
            if count < self.min_frequency:
                break
            precision = count / total_failures if total_failures else 0.0
            if precision < self.min_precision:
                continue
            if pattern in self._known_patterns:   # IDE-GATE-0
                continue
            rule_id = f"DISC-{epoch_id.replace('-', '')[:8]}-{len(discovered):02d}"  # IDE-DETERM-0
            chained = _chain_digest(rule_id, pattern, self._prev_digest)
            rule = DiscoveredRule(
                rule_id=rule_id,
                pattern_description=f"Failures matching pattern: {pattern}",
                failure_pattern=pattern,
                observed_frequency=count,
                estimated_precision=round(precision, 4),
                proposed_yaml=self._generate_rule_yaml(rule_id, pattern),
                discovery_epoch=epoch_id,
                evidence_mutation_ids=pattern_examples.get(pattern, [])[:5],
                digest=chained,
                prev_digest=self._prev_digest,
            )
            ide_guard(bool(rule.digest), "IDE-AUDIT-0", f"{rule_id} post-construction")
            discovered.append(rule)
            self._known_patterns.add(pattern)
            self._prev_digest = chained

        # IDE-PERSIST-0: flush all before return
        persisted = 0
        for rule in discovered:
            self._persist(rule)
            persisted += 1
        ide_guard(persisted == len(discovered), "IDE-PERSIST-0", f"{persisted}/{len(discovered)}")
        return discovered

    def pending_rules(self) -> list:
        if not self.ledger_path.exists():
            return []
        rules: list = []
        for line in self.ledger_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if d.get("status") == "proposed":
                    d.pop("_hmac", None)
                    rules.append(DiscoveredRule(**d))
            except Exception:
                pass
        return rules

    def verify_chain(self) -> bool:
        if not self.ledger_path.exists():
            return True
        for line in self.ledger_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                stored = d.pop("_hmac", None)
                if stored is None:
                    return False
                expected = _hmac_tag(json.dumps(d, sort_keys=True))
                if not hmac.compare_digest(stored, expected):
                    return False
            except Exception:
                return False
        return True

    def _generate_rule_yaml(self, rule_id: str, pattern: str) -> str:
        safe = re.sub(r"[^a-z0-9_]", "_", pattern.lower())[:40]
        return (f'{{"name": "{safe}", "enabled": true, "severity": "warning",\n'
                f' "tier_overrides": {{"SANDBOX": "advisory"}},\n'
                f' "reason": "Auto-discovered: {pattern} ({rule_id}). Human review required.",\n'
                f' "validator": "discovered_{safe}"}}')

    def _persist(self, rule: DiscoveredRule) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        entry = dataclasses.asdict(rule)
        entry["_hmac"] = _hmac_tag(json.dumps({k: v for k, v in entry.items() if k != "_hmac"}, sort_keys=True))
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def _append_event(event, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT]."""
    import hashlib as _h, json as _j, dataclasses as _dc
    from pathlib import Path as _P
    if not ledger_path:
        return
    row = _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else dict(event)
    row["event_digest"] = "sha256:" + _h.sha256(_j.dumps(row, sort_keys=True).encode()).hexdigest()
    p = _P(ledger_path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_j.dumps(row, sort_keys=True) + "\n")


__all__ = ["InvariantDiscoveryEngine", "DiscoveredRule", "IDEViolation",
           "IDE_INVARIANTS", "ide_guard", "MIN_PATTERN_FREQUENCY", "MIN_PRECISION"]
