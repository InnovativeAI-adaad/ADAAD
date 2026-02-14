# SPDX-License-Identifier: Apache-2.0
"""
Lightweight mutation strategy selector using UCB1-style scoring.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.agents.mutation_request import MutationRequest
from app.agents.mutation_strategies import DEFAULT_REGISTRY
from runtime import ROOT_DIR
from runtime import metrics
from runtime.metrics_analysis import summarize_preflight_rejections, top_preflight_rejections

EMA_ALPHA = float(os.getenv("ADAAD_MUTATION_EMA_ALPHA", "0.3"))
LOW_IMPACT_THRESHOLD = float(os.getenv("ADAAD_MUTATION_LOW_IMPACT_THRESHOLD", "0.3"))
SKILL_WEIGHT_COEF = float(os.getenv("ADAAD_MUTATION_SKILL_WEIGHT_COEF", "0.6"))


class MutationEngine:
    """
    Chooses which mutation strategy to run based on historical rewards.
    """

    def __init__(self, metrics_path: Path, state_path: Path | None = None) -> None:
        self.metrics_path = metrics_path
        self.state_path = state_path or (ROOT_DIR / "data" / "mutation_engine_state.json")

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

    def _update_state_from_metrics(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not self.metrics_path.exists():
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
            if event == "mutation_failed":
                entry["fail"] += 1.0
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
