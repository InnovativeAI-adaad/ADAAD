# SPDX-License-Identifier: Apache-2.0
# DORK Context Synthesis Module
# Phase 137 · INNOV-44 · DORK Intelligence Hardening & Capability Expansion
# Constitutional invariants: DORK-CTX-0, DORK-KB-0

import os
from pathlib import Path

# ── DORK-CTX-0 ────────────────────────────────────────────────────────────────
# Hard invariant: Context synthesis MUST use the canonical CONTEXT_KEYWORD_TAXONOMY
# for intent classification. Ad-hoc keyword lists outside this taxonomy are
# constitutionally prohibited for any routing decision.
# ─────────────────────────────────────────────────────────────────────────────

# ── DORK-KB-0 ────────────────────────────────────────────────────────────────
# Hard invariant: Every call to get_relevant_context() MUST attempt a KB lookup
# via the retriever pipeline. KB match outcomes (hit/miss/score) MUST be
# recorded in the returned context block for downstream trace logging.
# Silent KB bypass is constitutionally prohibited.
# ─────────────────────────────────────────────────────────────────────────────

CONTEXT_KEYWORD_TAXONOMY: dict[str, list[str]] = {
    "governance": [
        "gate", "tier", "policy", "constitution", "invariant", "signoff",
        "gpg", "human0", "approval", "ratification", "compliance", "blocked",
    ],
    "mutation": [
        "mutation", "propose", "promote", "shadow", "lsme", "diff",
        "delta", "patch", "rollback", "revert", "changeset",
    ],
    "replay": [
        "replay", "determinism", "divergence", "causal", "hydration",
        "manifest", "snapshot", "convergence", "score",
    ],
    "ledger": [
        "ledger", "hash", "chain", "audit", "lineage", "digest",
        "hmac", "tamper", "cryptographic", "forensics",
    ],
    "agent": [
        "architect", "dream", "beast", "agent", "triad", "proposal",
        "innovation", "innov", "phase",
    ],
    "fleet": [
        "fleet", "living", "dork", "slash", "command", "resolver",
        "provider", "ollama", "model", "capability", "engine",
        "watchdog", "probe", "heal", "dfsb",
    ],
    "release": [
        "release", "version", "changelog", "roadmap", "tag", "pypi",
        "publish", "deploy", "readiness",
    ],
    "sandbox": [
        "sandbox", "das", "docker", "isolation", "test", "preflight",
        "harness", "fixture",
    ],
    "persist": [
        "persist", "restore", "restart", "hydrate", "fsync", "continuity",
        "dfsb", "conversation", "session", "ledger_path",
    ],
}


def jaccard_score(query_tokens: set[str], category_tokens: set[str]) -> float:
    """
    Compute Jaccard similarity: |intersection| / |union|.
    Returns 0.0 if union is empty.
    """
    if not query_tokens and not category_tokens:
        return 0.0
    intersection = len(query_tokens & category_tokens)
    union = len(query_tokens | category_tokens)
    return intersection / union if union else 0.0


def _tokenize(text: str) -> set[str]:
    """
    Tokenize a query string: lowercase, split on whitespace and punctuation.
    Produces unigrams plus bigrams for improved short-query coverage.
    """
    import re
    words = re.findall(r"[a-zA-Z0-9_\-]+", text.lower())
    unigrams = set(words)
    bigrams = {f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)}
    return unigrams | bigrams


def classify_query(query: str) -> tuple[str, float]:
    """
    Classify a natural-language DORK query against the CONTEXT_KEYWORD_TAXONOMY.
    Returns (best_category, confidence_score).

    DORK-CTX-0: uses ONLY the canonical taxonomy — no ad-hoc keyword lists.
    """
    tokens = _tokenize(query)
    best_cat = "governance"
    best_score = 0.0
    for cat, keywords in CONTEXT_KEYWORD_TAXONOMY.items():
        kw_set: set[str] = set()
        for kw in keywords:
            kw_set.update(kw.lower().split())
        score = jaccard_score(tokens, kw_set)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat, round(best_score, 4)


def get_taxonomy_hints(query: str, top_n: int = 3) -> list[dict]:
    """
    Return the top_n ranked categories for a query with Jaccard scores.
    """
    tokens = _tokenize(query)
    scored = []
    for cat, kws in CONTEXT_KEYWORD_TAXONOMY.items():
        kw_set: set[str] = set()
        for kw in kws:
            kw_set.update(kw.lower().split())
        scored.append({"category": cat, "score": jaccard_score(tokens, kw_set)})
    return sorted(scored, key=lambda x: x["score"], reverse=True)[:top_n]


def get_codebase_summary(limit_files: int = 20) -> str:
    """Returns a strategic summary of the project structure and key files."""
    summary = []
    summary.append("### PROJECT STRUCTURE SUMMARY")

    try:
        root_items = os.listdir(".")
        dirs = [d for d in root_items if os.path.isdir(d) and not d.startswith(".")]
        summary.append(f"Directories: {', '.join(dirs)}")
    except Exception:
        pass

    key_files = [
        "GEMINI.md", "ADAAD_30_INNOVATIONS.md", "ARCHITECTURE.md",
        "DORK.md", "pyproject.toml", "requirements.txt",
    ]

    summary.append("\n### KEY ARCHITECTURAL DOCUMENTS")
    for kf in key_files:
        if os.path.exists(kf):
            try:
                with open(kf) as f:
                    content = f.read(800)
                    summary.append(f"- {kf}: {content[:400]}...")
            except Exception:
                summary.append(f"- {kf}: (Found but unreadable)")

    return "\n".join(summary)


def get_relevant_context(query: str) -> str:
    """
    Return a structured context block enriched with taxonomy classification
    and KB retriever results.

    DORK-KB-0: KB lookup is mandatory — hit/miss/score recorded in block.
    Used by the DORK intelligence layer to ground LLM responses.
    """
    category, confidence = classify_query(query)
    hints = get_taxonomy_hints(query)
    codebase = get_codebase_summary()

    # DORK-KB-0: mandatory KB lookup
    kb_block = _build_kb_block(query)

    lines = [
        "### DORK CONTEXT BLOCK",
        f"- Query category: {category} (Jaccard={confidence:.4f})",
        f"- Top categories: {', '.join(h['category'] for h in hints)}",
        "",
        kb_block,
        "",
        codebase,
    ]
    return "\n".join(lines)


def _build_kb_block(query: str) -> str:
    """
    DORK-KB-0: attempt KB retrieval and return a structured block.
    Records hit/miss/score regardless of outcome.
    """
    try:
        from dorkllm.retriever import get_kb_matches
        result = get_kb_matches(query)
        if result:
            return (
                f"### KB RETRIEVAL HIT\n"
                f"- Key: {result['key']}\n"
                f"- Score: {result['score']:.4f}\n"
                f"- Answer: {result['answer'][:600]}"
            )
        return "### KB RETRIEVAL: MISS (no match above threshold)"
    except Exception as exc:
        return f"### KB RETRIEVAL: ERROR ({exc})"
