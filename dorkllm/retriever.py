# SPDX-License-Identifier: Apache-2.0
# DORK Knowledge Retriever Module
# Phase 137 · INNOV-44 · DORK Intelligence Hardening & Capability Expansion
# Handles retrieval from the deterministic Aligned Knowledge Base (KB)

import json
import re
from functools import lru_cache
from pathlib import Path

KB_PATH = Path("ui/developer/ADAADdev/dork_knowledge_base.js")

# ── KB Cache ──────────────────────────────────────────────────────────────────
# Cache the parsed KB in-process to avoid repeated disk reads and regex
# parsing on every query. Invalidated only on process restart (intentional:
# KB changes require redeploy under ADAAD's governed mutation model).

@lru_cache(maxsize=1)
def _load_kb() -> list[dict]:
    """
    Parse the JS knowledge base into a list of {key, answer, tags} records.
    Returns [] on any parse error — never raises (fail-open for KB miss).

    Supports both array-of-objects and loose JS-object KB structures.
    Uses JSON extraction as primary strategy; regex as fallback.
    """
    if not KB_PATH.exists():
        return []

    try:
        raw = KB_PATH.read_text(encoding="utf-8")
    except OSError:
        return []

    records: list[dict] = []

    # Strategy 1: extract JSON array from `const KB = [...]`
    json_match = re.search(r"const\s+KB\s*=\s*(\[.*?\]);", raw, re.DOTALL)
    if json_match:
        try:
            # Normalize trailing commas for JSON compatibility
            blob = re.sub(r",\s*([}\]])", r"\1", json_match.group(1))
            parsed = json.loads(blob)
            for item in parsed:
                if isinstance(item, dict) and "key" in item and "answer" in item:
                    records.append({
                        "key": str(item["key"]),
                        "answer": str(item["answer"]),
                        "tags": list(item.get("tags", [])),
                    })
            if records:
                return records
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 2: regex object extraction (legacy structure)
    kb_block = re.search(r"const\s+KB\s*=\s*\[(.*?)\];", raw, re.DOTALL)
    if kb_block:
        for obj in re.finditer(r"\{(.*?)\}", kb_block.group(1), re.DOTALL):
            body = obj.group(1)
            k_m = re.search(r"""key\s*:\s*['"](.+?)['"]""", body)
            a_m = re.search(r"""answer\s*:\s*['"](.+?)['"]""", body, re.DOTALL)
            if k_m and a_m:
                ans = a_m.group(1)
                ans = ans.replace("\\'", "'").replace('\\"', '"')
                records.append({"key": k_m.group(1), "answer": ans, "tags": []})

    return records


def _score_match(query_words: set[str], record: dict) -> float:
    """
    Score a KB record against the query using normalized word overlap.
    Considers key tokens, tag tokens, and a partial answer token bonus.
    """
    key_words = set(re.findall(r"\w+", record["key"].lower()))
    tag_words: set[str] = set()
    for tag in record.get("tags", []):
        tag_words.update(re.findall(r"\w+", str(tag).lower()))
    answer_words = set(re.findall(r"\w+", record["answer"].lower()))

    if not key_words:
        return 0.0

    key_overlap = len(query_words & key_words) / len(key_words)
    tag_bonus = (len(query_words & tag_words) / len(tag_words)) * 0.3 if tag_words else 0.0
    # Small answer-token bonus for deep lexical match (capped at 0.1)
    answer_bonus = min(len(query_words & answer_words) / max(len(answer_words), 1), 0.1)

    return key_overlap + tag_bonus + answer_bonus


def get_kb_matches(query: str, threshold: float = 0.35, top_n: int = 1) -> dict | None:
    """
    Retrieve the best-scoring KB record for the given query.

    Returns the top match dict {score, answer, key} if score >= threshold,
    or None on miss. Never raises — KB errors produce a None result.
    """
    records = _load_kb()
    if not records:
        return None

    query_words = set(re.findall(r"\w+", query.lower()))
    if not query_words:
        return None

    scored = []
    for record in records:
        s = _score_match(query_words, record)
        if s > 0:
            scored.append((s, record))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_record = scored[0]

    if best_score < threshold:
        return None

    return {
        "score": round(best_score, 4),
        "key": best_record["key"],
        "answer": best_record["answer"],
    }


def get_kb_top_n(query: str, threshold: float = 0.35, top_n: int = 3) -> list[dict]:
    """
    Return the top_n KB matches above threshold, sorted by descending score.
    Used for multi-result enrichment in advanced DORK context builds.
    """
    records = _load_kb()
    if not records:
        return []

    query_words = set(re.findall(r"\w+", query.lower()))
    if not query_words:
        return []

    scored = []
    for record in records:
        s = _score_match(query_words, record)
        if s >= threshold:
            scored.append({"score": round(s, 4), "key": record["key"], "answer": record["answer"]})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def invalidate_kb_cache() -> None:
    """Invalidate the in-process KB cache. Useful after KB hot-reload in tests."""
    _load_kb.cache_clear()
