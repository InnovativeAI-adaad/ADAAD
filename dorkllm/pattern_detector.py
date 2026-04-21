"""
dorkllm/pattern_detector.py
DORK Persistent Memory (DPM) — Pattern Detector

INNOV-51 · Phase 145 · v9.78.0
Constitutional invariant: DPM-DETERM-0

Detects recurrent patterns in query/response pairs that merit crystallisation
into durable memory. All scoring is deterministic: identical inputs produce
identical scores. No randomness. No model calls.

Pattern categories (mirrors DORK intent taxonomy):
  - governance   : governance decisions, phase completions, invariant records
  - architecture : subsystem design decisions, blueprint facts
  - tooling      : CLI flags, command patterns, env vars, known-good invocations
  - identity     : HUMAN-0 identity facts, project constants
  - error        : known failure modes and their resolutions
"""

from __future__ import annotations

import re
from typing import Any

# ── Keyword taxonomy ──────────────────────────────────────────────────────────

_TAXONOMY: dict[str, list[str]] = {
    "governance": [
        "phase", "innov", "invariant", "ratif", "signoff", "ila", "human-0",
        "human0", "dustin", "gate", "ga-block", "constitution", "version bump",
        "canonical", "changelog", "gpg", "tag", "adaadell",
    ],
    "architecture": [
        "blueprint", "subsystem", "pipeline", "ledger", "hmac", "append-only",
        "deterministic", "replay", "engine", "module", "schema", "contract",
        "invariant class", "hard-class", "soft-class",
    ],
    "tooling": [
        "pytest", "--ignore", "git", "push", "merge", "no-ff", "pat",
        "remote set-url", "pyproject", "sed", "grep", "python3",
        "pip install", "break-system-packages",
    ],
    "identity": [
        "innovadaad", "innovative ai", "blackwell", "adaad", "dork",
        "devadaad", "mutationagent", "architectagent", "human-0",
    ],
    "error": [
        "error", "fail", "violation", "corrupt", "missing", "mismatch",
        "broken", "stale", "drift", "null", "finding", "audit",
    ],
}


def _score_text(text: str, keywords: list[str]) -> float:
    """Count normalised keyword hits in text (case-insensitive)."""
    lower = text.lower()
    hits = sum(1 for kw in keywords if kw in lower)
    return round(hits / max(len(keywords), 1), 6)


# ── Pattern detection ─────────────────────────────────────────────────────────

def detect_patterns(
    query: str,
    response: str = "",
) -> list[dict[str, Any]]:
    """
    DPM-DETERM-0: Analyse query+response for crystallisable patterns.
    Returns a list of detected pattern dicts, each with:
      category, confidence, topic, content, tags
    Deterministic: same input → same output, always.
    """
    combined = (query + " " + response).strip()
    if not combined:
        return []

    patterns: list[dict[str, Any]] = []

    for category, keywords in _TAXONOMY.items():
        score = _score_text(combined, keywords)
        if score < 0.05:
            continue
        topic = _extract_topic(combined, category)
        content = _extract_content(combined, category)
        tags = _extract_tags(combined, keywords)
        patterns.append(
            {
                "category": category,
                "confidence": min(score * 4.0, 0.99),  # scale to [0, 0.99]
                "topic": topic,
                "content": content,
                "tags": tags,
                "source": "pattern_detector",
            }
        )

    # Sort deterministically: confidence desc, then category asc
    patterns.sort(key=lambda p: (-p["confidence"], p["category"]))
    return patterns


def _extract_topic(text: str, category: str) -> str:
    """Extract a short topic label from text for a given category."""
    # Try to find a version string
    ver_match = re.search(r"v?\d+\.\d+\.\d+", text)
    phase_match = re.search(r"[Pp]hase\s+(\d+)", text)
    innov_match = re.search(r"INNOV-(\d+)", text)

    if category == "governance":
        if phase_match and innov_match:
            return f"Phase {phase_match.group(1)} INNOV-{innov_match.group(1)}"
        if phase_match:
            return f"Phase {phase_match.group(1)}"
        if ver_match:
            return f"Version {ver_match.group(0)}"
        return "governance-record"

    if category == "architecture":
        for kw in ["memory", "engine", "ledger", "pipeline", "schema", "replay"]:
            if kw in text.lower():
                return f"architecture:{kw}"
        return "architecture-decision"

    if category == "tooling":
        for kw in ["pytest", "git", "pip", "sed", "python3"]:
            if kw in text.lower():
                return f"tooling:{kw}"
        return "tooling-pattern"

    if category == "identity":
        return "project-identity"

    if category == "error":
        finding = re.search(r"FINDING-[\w-]+", text)
        if finding:
            return f"error:{finding.group(0)}"
        audit = re.search(r"AUDIT-\d+", text)
        if audit:
            return f"error:{audit.group(0)}"
        return "error-pattern"

    return f"{category}-general"


def _extract_content(text: str, category: str) -> str:
    """Extract a concise content string (max 300 chars) relevant to category."""
    # Take the first 300 chars of text, stripped of excess whitespace
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= 300:
        return cleaned
    # Try to end at a sentence boundary within 300 chars
    truncated = cleaned[:300]
    last_period = truncated.rfind(". ")
    if last_period > 150:
        return truncated[: last_period + 1]
    return truncated + "…"


def _extract_tags(text: str, keywords: list[str]) -> list[str]:
    """Return sorted list of keywords that appear in text (max 6)."""
    lower = text.lower()
    hits = sorted(kw for kw in keywords if kw in lower)
    return hits[:6]


# ── Crystallisation threshold ─────────────────────────────────────────────────

def should_crystallise(pattern: dict[str, Any]) -> bool:
    """
    Return True if pattern confidence meets the crystallisation threshold (0.6).
    This is the gate that memory_engine.store_memory() enforces independently;
    this function provides an upstream pre-check.
    """
    return pattern.get("confidence", 0.0) >= 0.6
