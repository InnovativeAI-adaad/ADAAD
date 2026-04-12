# SPDX-License-Identifier: Apache-2.0
"""Innovation #18 — Temporal Governance Windows.
Rules with activation_conditions on system health state.

Additions (v1.1):
    audit_trail()          — tamper-evident log readback with SHA-256 digests
    export_window_config() — structured window configuration for persistence
    health_trend()         — trend analysis from recent log entries
    SHA-256 tamper digest  — each log entry carries a chain-linkable digest
"""
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
TEGO_INV_CHAIN: str = "TEGO-INV-CHAIN"


class TemporalGovernanceViolation(RuntimeError):
    """Raised when a Temporal Governance constitutional invariant is breached."""




@dataclass
class GovernanceWindow:
    rule_name: str
    baseline_severity: str
    high_health_severity: str     # when health > HIGH_HEALTH_THRESHOLD
    low_health_severity: str      # when health < LOW_HEALTH_THRESHOLD
    high_health_threshold: float = 0.85
    low_health_threshold: float = 0.60

    def effective_severity(self, health_score: float) -> str:
        if health_score >= self.high_health_threshold:
            return self.high_health_severity
        elif health_score < self.low_health_threshold:
            return self.low_health_severity
        return self.baseline_severity


# Default temporal windows for existing constitutional rules
DEFAULT_WINDOWS: list[GovernanceWindow] = [
    GovernanceWindow("lineage_continuity", "blocking", "warning",  "blocking"),
    GovernanceWindow("single_file_scope",  "blocking", "warning",  "blocking"),
    GovernanceWindow("ast_validity",       "blocking", "blocking", "blocking"),
    GovernanceWindow("entropy_budget",     "warning",  "advisory", "blocking"),
    GovernanceWindow("replay_determinism", "warning",  "advisory", "blocking"),
]


class TemporalGovernanceEngine:
    """Adjusts rule severities based on current system health."""

    def __init__(
        self,
        windows: list[GovernanceWindow] | None = None,
        state_path: Path = Path("data/temporal_governance_state.jsonl"),
    ) -> None:
        self.windows = {w.rule_name: w for w in (windows or DEFAULT_WINDOWS)}
        self.state_path = Path(state_path)
        # Running digest chain for tamper detection — each entry links to prev
        self._chain_head: str = "genesis"

    # ── Core API ─────────────────────────────────────────────────────────────

    def effective_severity(self, rule_name: str, health_score: float) -> str:
        window = self.windows.get(rule_name)
        if window is None:
            return "blocking"  # unknown rule: fail-closed [TGOV-FAIL-0]
        return window.effective_severity(health_score)

    def get_adjusted_ruleset(self, health_score: float) -> dict[str, str]:
        """Return {rule_name → effective_severity} for current health."""
        return {
            name: w.effective_severity(health_score)
            for name, w in self.windows.items()
        }

    def register_window(self, window: GovernanceWindow) -> None:
        self.windows[window.rule_name] = window

    def log_adjustment(self, epoch_id: str, health_score: float) -> None:
        """Persist a health-adjusted ruleset entry with SHA-256 chain digest."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        adjustments = self.get_adjusted_ruleset(health_score)

        # Chain digest links this entry to the previous head [TGOV-CHAIN-0]
        payload = json.dumps({
            "epoch_id": epoch_id,
            "health_score": round(health_score, 4),
            "adjustments": adjustments,
            "prev_digest": self._chain_head,
        }, sort_keys=True)
        digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

        entry = {
            "epoch_id": epoch_id,
            "health_score": round(health_score, 4),
            "adjustments": adjustments,
            "timestamp": round(time.time(), 3),
            "prev_digest": self._chain_head,
            "digest": digest,
        }
        with self.state_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self._chain_head = digest

    # ── Audit & introspection ─────────────────────────────────────────────────

    def audit_trail(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read back last N log entries.  Returns [] if no log exists.

        Each entry includes its digest for external chain verification.
        """
        if not self.state_path.exists():
            return []
        lines = self.state_path.read_text().splitlines()
        results: list[dict] = []
        for line in lines[-limit:]:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # corrupt line — skip, do not halt [TGOV-CORRUPT-SKIP-0]
        return results

    def export_window_config(self) -> dict[str, Any]:
        """Export current window configuration as a serialisable dict.

        Suitable for persistence, diff-ing across epochs, or human review.
        """
        return {
            "innovation": 18,
            "innovation_name": "TemporalGovernance",
            "version": "1.1.0",
            "window_count": len(self.windows),
            "windows": {
                name: {
                    "baseline_severity": w.baseline_severity,
                    "high_health_severity": w.high_health_severity,
                    "low_health_severity": w.low_health_severity,
                    "high_health_threshold": w.high_health_threshold,
                    "low_health_threshold": w.low_health_threshold,
                }
                for name, w in self.windows.items()
            },
        }

    def health_trend(self, n: int = 5) -> str:
        """Analyse the last N logged health scores.

        Returns:
            "improving"  — last score higher than first in window
            "degrading"  — last score lower than first in window
            "stable"     — insufficient data or negligible change (< 0.05)
        """
        trail = self.audit_trail(limit=n)
        if len(trail) < 2:
            return "stable"
        scores = [entry.get("health_score", 0.75) for entry in trail]
        delta = scores[-1] - scores[0]
        if delta > 0.05:
            return "improving"
        if delta < -0.05:
            return "degrading"
        return "stable"


__all__ = [
    "TemporalGovernanceEngine",
    "GovernanceWindow",
    "DEFAULT_WINDOWS",
]
