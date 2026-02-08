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
from runtime import metrics
from runtime.metrics_analysis import summarize_preflight_rejections, top_preflight_rejections

EMA_ALPHA = float(os.getenv("ADAAD_MUTATION_EMA_ALPHA", "0.3"))
LOW_IMPACT_THRESHOLD = float(os.getenv("ADAAD_MUTATION_LOW_IMPACT_THRESHOLD", "0.3"))


class MutationEngine:
    """
    Chooses which mutation strategy to run based on historical rewards.
    """

    def __init__(self, metrics_path: Path) -> None:
        self.metrics_path = metrics_path

    def _load_history(self) -> Dict[str, Dict[str, float]]:
        """
        Return {strategy_id: {"n": count, "reward": total_reward, "fail": failures}}.
        """
        if not self.metrics_path.exists():
            return {}
        history: Dict[str, Dict[str, float]] = {}
        try:
            lines = self.metrics_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return history

        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload", {}) or {}
            event = record.get("event")
            sid = payload.get("strategy_id")
            if not sid:
                continue
            entry = history.setdefault(
                sid,
                {"n": 0.0, "reward": 0.0, "fail": 0.0, "ema": None, "low_impact": 0.0},
            )
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
        return history

    def _ucb1(self, history: Dict[str, Dict[str, float]], strategy_id: str, total: float) -> float:
        stats = history.get(strategy_id, {"n": 0.0, "reward": 0.0, "fail": 0.0})
        n = stats["n"]
        if n == 0:
            return float("inf")
        avg = stats["reward"] / n
        return avg + math.sqrt(2 * math.log(max(total, 1.0)) / n)

    def _extract_op_paths(self, request: MutationRequest) -> List[str]:
        paths: List[str] = []
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
        for op in request.ops:
            if not isinstance(op, dict):
                continue
            for key in ("content", "source", "code", "value"):
                value = op.get(key)
                if isinstance(value, str) and value.strip():
                    return True
        return False

    def _mentions_imports(self, request: MutationRequest) -> bool:
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

        if "ast_parse_failed" in reasons and self._has_code_payload(request):
            penalties["ast_parse_failed"] = 0.4
            score -= penalties["ast_parse_failed"]

        if "import_smoke_failed" in reasons and self._mentions_imports(request):
            penalties["import_smoke_failed"] = 0.3
            score -= penalties["import_smoke_failed"]

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
