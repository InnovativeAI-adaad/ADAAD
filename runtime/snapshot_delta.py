# SPDX-License-Identifier: Apache-2.0
"""Semantic interpretation of runtime snapshot deltas for Dork/epoch reviews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class SnapshotDeltaInterpretation:
    """Structured interpretation payload suitable for cards and ledger events."""

    risk_level: RiskLevel
    impacted_subsystems: list[str]
    likely_operator_actions: list[str]
    confidence_score: float
    summary: str
    semantic_deltas: list[str]
    raw_field_diffs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "impacted_subsystems": list(self.impacted_subsystems),
            "likely_operator_actions": list(self.likely_operator_actions),
            "confidence_score": float(self.confidence_score),
            "summary": self.summary,
            "semantic_deltas": list(self.semantic_deltas),
            "raw_field_diffs": list(self.raw_field_diffs),
        }


class SnapshotDeltaInterpreter:
    """Compute semantic deltas between before/after state feeds.

    Expected feed keys: governance, replay, readiness, mutation.
    """

    _SUBSYSTEM_PATHS: tuple[tuple[str, str], ...] = (
        ("governance", "governance"),
        ("replay", "replay"),
        ("readiness", "release_readiness"),
        ("mutation", "mutation_pipeline"),
    )

    @staticmethod
    def _read(feed: dict[str, Any], *path: str) -> Any:
        current: Any = feed
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _raw_diffs(self, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        diffs: list[str] = []
        for key, _ in self._SUBSYSTEM_PATHS:
            before_payload = before.get(key, {}) if isinstance(before.get(key), dict) else {}
            after_payload = after.get(key, {}) if isinstance(after.get(key), dict) else {}
            union = sorted(set(before_payload.keys()) | set(after_payload.keys()))
            for field in union:
                if before_payload.get(field) != after_payload.get(field):
                    diffs.append(f"{key}.{field}")
        return diffs

    def interpret(self, *, before: dict[str, Any], after: dict[str, Any]) -> SnapshotDeltaInterpretation:
        semantic: list[str] = []
        actions: list[str] = []
        impacted: list[str] = []
        risk_score = 0

        before_locked = bool(self._read(before, "governance", "locked"))
        after_locked = bool(self._read(after, "governance", "locked"))
        if before_locked != after_locked:
            impacted.append("governance")
            if after_locked:
                risk_score += 55
                semantic.append("Governance gate transitioned into LOCKED state.")
                actions.extend([
                    "Inspect governance lock reason and fail-closed blockers.",
                    "Pause promotion/mutation actions until lock clears.",
                ])
            else:
                risk_score += 12
                semantic.append("Governance gate transitioned to PASS state.")
                actions.append("Resume normal governed flow while monitoring blocker recurrence.")

        before_divergence = float(self._read(before, "replay", "divergence") or 0.0)
        after_divergence = float(self._read(after, "replay", "divergence") or 0.0)
        if after_divergence != before_divergence:
            impacted.append("replay")
            if after_divergence > before_divergence:
                risk_score += 35
                semantic.append(f"Replay divergence increased ({before_divergence} → {after_divergence}).")
                actions.append("Run strict replay verification and inspect latest mutation diff.")
            else:
                risk_score += 6
                semantic.append(f"Replay divergence improved ({before_divergence} → {after_divergence}).")

        before_readiness = float(self._read(before, "readiness", "readiness_score") or 0.0)
        after_readiness = float(self._read(after, "readiness", "readiness_score") or 0.0)
        if after_readiness != before_readiness:
            impacted.append("release_readiness")
            if after_readiness < before_readiness:
                risk_score += 24
                semantic.append(f"Release readiness regressed ({before_readiness:.2f} → {after_readiness:.2f}).")
                actions.append("Prioritize readiness blockers before attempting release gates.")
            else:
                risk_score += 4
                semantic.append(f"Release readiness improved ({before_readiness:.2f} → {after_readiness:.2f}).")

        before_blockers = set(self._read(before, "readiness", "blockers") or [])
        after_blockers = set(self._read(after, "readiness", "blockers") or [])
        new_blockers = sorted(after_blockers - before_blockers)
        resolved_blockers = sorted(before_blockers - after_blockers)
        if new_blockers or resolved_blockers:
            impacted.append("release_readiness")
            if new_blockers:
                risk_score += 22
                semantic.append(f"New readiness blockers detected: {', '.join(new_blockers)}.")
            if resolved_blockers:
                semantic.append(f"Resolved blockers: {', '.join(resolved_blockers)}.")

        before_total = int(self._read(before, "mutation", "total") or 0)
        after_total = int(self._read(after, "mutation", "total") or 0)
        if after_total != before_total:
            impacted.append("mutation_pipeline")
            delta = after_total - before_total
            if delta > 0:
                semantic.append(f"Mutation queue grew by {delta} item(s).")
                risk_score += 10 if delta < 5 else 20
                actions.append("Review newly queued mutations for constitutional fit.")
            else:
                semantic.append(f"Mutation queue decreased by {abs(delta)} item(s).")

        risk_level: RiskLevel
        if risk_score >= 80:
            risk_level = "critical"
        elif risk_score >= 45:
            risk_level = "high"
        elif risk_score >= 20:
            risk_level = "medium"
        else:
            risk_level = "low"

        unique_impacted = sorted(set(impacted))
        unique_actions = list(dict.fromkeys(actions))
        raw_field_diffs = self._raw_diffs(before, after)
        confidence = 0.64
        if raw_field_diffs:
            confidence = min(0.98, 0.7 + min(len(raw_field_diffs), 8) * 0.03)
        if not semantic:
            semantic = ["No material semantic shifts detected across tracked feeds."]
            confidence = max(confidence, 0.8)

        summary = f"{len(semantic)} semantic change(s), risk={risk_level}, impacted={', '.join(unique_impacted) or 'none'}."
        return SnapshotDeltaInterpretation(
            risk_level=risk_level,
            impacted_subsystems=unique_impacted,
            likely_operator_actions=unique_actions,
            confidence_score=round(confidence, 3),
            summary=summary,
            semantic_deltas=semantic,
            raw_field_diffs=raw_field_diffs,
        )


__all__ = ["SnapshotDeltaInterpretation", "SnapshotDeltaInterpreter", "RiskLevel"]
