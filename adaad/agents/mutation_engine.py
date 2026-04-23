# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
_AGENT_CONTRACT_EXCLUDED = True  # infrastructure module — not a governed agent contract
"""
Lightweight mutation strategy selector using UCB1-style scoring.
"""


import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from adaad.agents.mutation_request import MutationRequest
from adaad.agents.mutation_strategies import DEFAULT_REGISTRY
from runtime.api.app_layer import ROOT_DIR, metrics, summarize_preflight_rejections, top_preflight_rejections

EMA_ALPHA = float(os.getenv("ADAAD_MUTATION_EMA_ALPHA", "0.3"))
LOW_IMPACT_THRESHOLD = float(os.getenv("ADAAD_MUTATION_LOW_IMPACT_THRESHOLD", "0.3"))
SKILL_WEIGHT_COEF = float(os.getenv("ADAAD_MUTATION_SKILL_WEIGHT_COEF", "0.6"))
PATTERN_SCORE_COEF = float(os.getenv("ADAAD_MUTATION_PATTERN_SCORE_COEF", "0.8"))
PATTERN_CONFIDENCE_MIN = float(os.getenv("ADAAD_MUTATION_PATTERN_CONFIDENCE_MIN", "0.25"))
PATTERN_DECAY_HALFLIFE_DAYS = float(os.getenv("ADAAD_MUTATION_PATTERN_DECAY_HALFLIFE_DAYS", "14"))
PATTERN_MIN_SAMPLE_SIZE = int(os.getenv("ADAAD_MUTATION_PATTERN_MIN_SAMPLE_SIZE", "3"))
PATTERN_ACCEPTANCE_SCORE = float(os.getenv("ADAAD_MUTATION_PATTERN_ACCEPTANCE_SCORE", "0.6"))
PATTERN_PRIOR = float(os.getenv("ADAAD_MUTATION_PATTERN_PRIOR", "0.5"))


class MutationEngine:
    """
    Chooses which mutation strategy to run based on historical rewards.
    """

    def __init__(self, metrics_path: Path, state_path: Path | None = None) -> None:
        self.metrics_path = metrics_path
        self.state_path = state_path or (ROOT_DIR / "data" / "mutation_engine_state.json")
        self.patterns_path = ROOT_DIR / "runtime" / "patterns.json"

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"cursor": 0, "stats": {}}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"cursor": 0, "stats": {}}

    def _persist_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    def _ensure_stats(self, state: Dict[str, Any], strategy_id: str) -> Dict[str, float]:
        stats = state.setdefault("stats", {})
        entry = stats.setdefault(
            strategy_id,
            {"n": 0.0, "reward": 0.0, "fail": 0.0, "ema": None, "low_impact": 0.0, "skill_weight": None},
        )
        return entry

    @staticmethod
    def _parse_iso8601(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _load_pattern_store(self) -> Dict[str, Any]:
        if not self.patterns_path.exists():
            return {"schema_version": "1.0", "patterns": []}
        try:
            data = json.loads(self.patterns_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"schema_version": "1.0", "patterns": []}
        if not isinstance(data, dict):
            return {"schema_version": "1.0", "patterns": []}
        data.setdefault("schema_version", "1.0")
        if not isinstance(data.get("patterns"), list):
            data["patterns"] = []
        return data

    def _persist_pattern_store(self, store: Dict[str, Any]) -> None:
        self.patterns_path.parent.mkdir(parents=True, exist_ok=True)
        self.patterns_path.write_text(json.dumps(store, sort_keys=True, indent=2), encoding="utf-8")

    def _resolve_pattern_context(self, payload: Dict[str, Any]) -> str:
        context = payload.get("context")
        if isinstance(context, str) and context.strip():
            return context.strip()
        return "global"

    def _record_pattern_update(
        self,
        *,
        strategy_id: str,
        context: str,
        accepted: bool,
        score: float,
        evaluated_at: str,
    ) -> None:
        store = self._load_pattern_store()
        patterns = store.setdefault("patterns", [])
        match = next(
            (
                entry
                for entry in patterns
                if isinstance(entry, dict)
                and entry.get("pattern_id") == strategy_id
                and entry.get("context") == context
            ),
            None,
        )
        if match is None:
            match = {
                "pattern_id": strategy_id,
                "context": context,
                "success_rate": PATTERN_PRIOR,
                "sample_size": 0,
                "last_used_at": evaluated_at,
            }
            patterns.append(match)

        sample_size = int(match.get("sample_size", 0) or 0)
        current_rate = float(match.get("success_rate", PATTERN_PRIOR) or PATTERN_PRIOR)
        score_signal = max(0.0, min(1.0, score))
        outcome = score_signal if accepted else 0.0
        updated_size = sample_size + 1
        updated_rate = ((current_rate * sample_size) + outcome) / max(updated_size, 1)
        match["success_rate"] = round(max(0.0, min(1.0, updated_rate)), 6)
        match["sample_size"] = updated_size
        match["last_used_at"] = evaluated_at
        self._persist_pattern_store(store)
        metrics.log(
            event_type="pattern_update_emitted",
            payload={
                "pattern_id": strategy_id,
                "context": context,
                "accepted": accepted,
                "acceptance_criteria": f"mutation_score >= {PATTERN_ACCEPTANCE_SCORE:.2f}",
                "sample_size": updated_size,
                "success_rate": match["success_rate"],
            },
            level="INFO",
        )

    def _update_state_from_metrics(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not self.metrics_path.exists():
            # CF-4 fix: metrics file absent (deleted or never created).
            # Reset cursor to 0 so stats accumulate correctly when the file
            # is recreated. Prior code returned early without resetting cursor,
            # leaving cursor=917 with stats={} permanently — a silent failure.
            state["cursor"] = 0
            return state
        cursor = int(state.get("cursor", 0) or 0)
        try:
            size = self.metrics_path.stat().st_size
        except OSError:
            return state
        if cursor > size:
            cursor = 0
        new_cursor = cursor
        with self.metrics_path.open("rb") as handle:
            handle.seek(cursor)
            chunk = handle.read()
            new_cursor = handle.tell()
        if not chunk:
            state["cursor"] = new_cursor
            return state

        for raw_line in chunk.splitlines():
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload", {}) or {}
            event = record.get("event")
            sid = payload.get("strategy_id")
            if not sid:
                continue
            entry = self._ensure_stats(state, sid)
            if event == "mutation_score":
                score = float(payload.get("score", 0.0))
                entry["n"] += 1.0
                entry["reward"] += score
                if entry["ema"] is None:
                    entry["ema"] = score
                else:
                    entry["ema"] = (EMA_ALPHA * score) + ((1 - EMA_ALPHA) * float(entry["ema"]))
                if score < LOW_IMPACT_THRESHOLD:
                    entry["low_impact"] += 1.0
                accepted = score >= PATTERN_ACCEPTANCE_SCORE
                evaluated_at = str(record.get("timestamp") or record.get("ts") or "")
                if not evaluated_at:
                    evaluated_at = datetime.now(timezone.utc).isoformat()
                self._record_pattern_update(
                    strategy_id=sid,
                    context=self._resolve_pattern_context(payload),
                    accepted=accepted,
                    score=score,
                    evaluated_at=evaluated_at,
                )
            if event == "mutation_failed":
                entry["fail"] += 1.0
                evaluated_at = str(record.get("timestamp") or record.get("ts") or "")
                if not evaluated_at:
                    evaluated_at = datetime.now(timezone.utc).isoformat()
                self._record_pattern_update(
                    strategy_id=sid,
                    context=self._resolve_pattern_context(payload),
                    accepted=False,
                    score=0.0,
                    evaluated_at=evaluated_at,
                )
            if event == "skill_feedback":
                score = float(payload.get("score", 0.0))
                if entry["skill_weight"] is None:
                    entry["skill_weight"] = score
                else:
                    entry["skill_weight"] = (EMA_ALPHA * score) + (
                        (1 - EMA_ALPHA) * float(entry["skill_weight"])
                    )
        state["cursor"] = new_cursor
        return state

    def refresh_state_from_metrics(self) -> None:
        """
        Update persisted state from the metrics log.
        """
        state = self._load_state()
        state = self._update_state_from_metrics(state)
        self._persist_state(state)

    def _load_history(self) -> Dict[str, Dict[str, float]]:
        """
        Return {strategy_id: {"n": count, "reward": total_reward, "fail": failures}}.
        """
        state = self._load_state()
        return state.get("stats", {}) or {}

    def _ucb1(self, history: Dict[str, Dict[str, float]], strategy_id: str, total: float) -> float:
        stats = history.get(strategy_id, {"n": 0.0, "reward": 0.0, "fail": 0.0})
        n = stats["n"]
        if n == 0:
            return float("inf")
        avg = stats["reward"] / n
        return avg + math.sqrt(2 * math.log(max(total, 1.0)) / n)

    def _pattern_signal(self, strategy_id: str, context: str = "global") -> Tuple[float, float]:
        store = self._load_pattern_store()
        now_utc = datetime.now(timezone.utc)
        for entry in store.get("patterns", []) or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("pattern_id") != strategy_id or entry.get("context") != context:
                continue
            sample_size = int(entry.get("sample_size", 0) or 0)
            if sample_size <= 0:
                return 0.0, 0.0
            success_rate = float(entry.get("success_rate", PATTERN_PRIOR) or PATTERN_PRIOR)
            last_used = self._parse_iso8601(entry.get("last_used_at"))
            age_days = 0.0
            if last_used is not None:
                age_days = max(0.0, (now_utc - last_used).total_seconds() / 86400.0)
            decay = math.pow(0.5, age_days / max(PATTERN_DECAY_HALFLIFE_DAYS, 0.1))
            effective_samples = float(sample_size) * decay
            confidence = max(0.0, min(1.0, effective_samples / max(float(PATTERN_MIN_SAMPLE_SIZE), 1.0)))
            decayed_rate = PATTERN_PRIOR + ((success_rate - PATTERN_PRIOR) * decay)
            delta = decayed_rate - PATTERN_PRIOR
            return delta, confidence
        return 0.0, 0.0

    def _extract_op_paths(self, request: MutationRequest) -> List[str]:
        paths: List[str] = []
        if request.targets:
            for target in request.targets:
                if isinstance(target.path, str) and target.path.strip():
                    paths.append(target.path)
                for op in target.ops:
                    if not isinstance(op, dict):
                        continue
                    for key in ("file", "filepath", "target"):
                        value = op.get(key)
                        if isinstance(value, str) and value.strip():
                            paths.append(value)
            return paths
        for op in request.ops:
            if not isinstance(op, dict):
                continue
            for key in ("file", "filepath", "target"):
                value = op.get(key)
                if isinstance(value, str) and value.strip():
                    paths.append(value)
            files = op.get("files")
            if isinstance(files, list):
                paths.extend([entry for entry in files if isinstance(entry, str) and entry.strip()])
        return paths

    def _has_code_payload(self, request: MutationRequest) -> bool:
        if request.targets:
            for target in request.targets:
                for op in target.ops:
                    if not isinstance(op, dict):
                        continue
                    for key in ("content", "source", "code", "value"):
                        value = op.get(key)
                        if isinstance(value, str) and value.strip():
                            return True
            return False
        for op in request.ops:
            if not isinstance(op, dict):
                continue
            for key in ("content", "source", "code", "value"):
                value = op.get(key)
                if isinstance(value, str) and value.strip():
                    return True
        return False

    def _mentions_imports(self, request: MutationRequest) -> bool:
        if request.targets:
            for target in request.targets:
                for op in target.ops:
                    if not isinstance(op, dict):
                        continue
                    for key in ("content", "source", "code", "value"):
                        value = op.get(key)
                        if isinstance(value, str) and "import " in value:
                            return True
            return False
        for op in request.ops:
            if not isinstance(op, dict):
                continue
            for key in ("content", "source", "code", "value"):
                value = op.get(key)
                if isinstance(value, str) and "import " in value:
                    return True
        return False

    def _apply_preflight_bias(self, request: MutationRequest, score: float) -> Tuple[float, Dict[str, float]]:
        penalties: Dict[str, float] = {}
        top_rejections = top_preflight_rejections(limit=500, top_n=3)
        summary = summarize_preflight_rejections(limit=500)
        reasons = [reason for reason, _ in top_rejections]
        if not reasons:
            return score, penalties

        paths = self._extract_op_paths(request)
        unique_paths = {path for path in paths if path}
        if "multi_file_mutation" in reasons and len(unique_paths) > 1:
            penalties["multi_file_mutation"] = 0.75
            score -= penalties["multi_file_mutation"]

        if any(reason.startswith("syntax_error:") for reason in reasons) and self._has_code_payload(request):
            penalties["syntax_error"] = 0.4
            score -= penalties["syntax_error"]

        if any(reason.startswith("missing_dependency:") for reason in reasons) and self._mentions_imports(request):
            penalties["missing_dependency"] = 0.3
            score -= penalties["missing_dependency"]

        if penalties:
            metrics.log(
                event_type="mutation_bias_applied",
                payload={
                    "strategy_id": request.intent or "default",
                    "penalties": penalties,
                    "top_rejections": reasons,
                    "window": summary.get("window", 0),
                },
                level="INFO",
            )
        return score, penalties

    def bias_details(self, request: MutationRequest) -> Dict[str, Any]:
        """
        Return preflight bias details without altering selection logic.
        """
        score, penalties = self._apply_preflight_bias(request, 0.0)
        return {
            "penalties": penalties,
            "score_delta": score,
        }

    def select(self, requests: List[MutationRequest]) -> Tuple[MutationRequest | None, Dict[str, float]]:
        """
        Pick the best candidate request. Returns (request or None, scores).
        """
        if not requests:
            return None, {}
        history = self._load_history()
        total = sum(v.get("n", 0.0) for v in history.values()) or 1.0
        scores: Dict[str, float] = {}
        best: MutationRequest | None = None
        best_score = -float("inf")
        for req in requests:
            sid = req.intent or "default"
            stats = history.get(sid, {"n": 0.0, "reward": 0.0, "fail": 0.0, "ema": None, "low_impact": 0.0})
            failures = stats.get("fail", 0.0)
            attempts = max(stats.get("n", 0.0), 1.0)
            failure_rate = failures / attempts
            s = self._ucb1(history, sid, total)
            ema = stats.get("ema")
            if ema is not None:
                s += float(ema) * 0.5
            skill_weight = stats.get("skill_weight")
            if skill_weight is None:
                skill_weight = DEFAULT_REGISTRY.get_skill_weight(sid)
            if skill_weight is not None:
                s += float(skill_weight) * SKILL_WEIGHT_COEF
            pattern_delta, pattern_confidence = self._pattern_signal(sid, context="global")
            if pattern_confidence >= PATTERN_CONFIDENCE_MIN:
                s += pattern_delta * pattern_confidence * PATTERN_SCORE_COEF
            low_impact = stats.get("low_impact", 0.0)
            if attempts:
                s -= (low_impact / attempts) * 0.4
            s -= failure_rate * 0.5
            s, _ = self._apply_preflight_bias(req, s)
            scores[sid] = s
            if s > best_score:
                best_score = s
                best = req
        return best, scores


__all__ = ["MutationEngine"]
