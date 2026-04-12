# SPDX-License-Identifier: Apache-2.0
# DORK Semantic Embedder
# Phase 142 · INNOV-48 · Contextual Semantic Search (CSS)
#
# Architecture:
#   Primary  — Ollama embeddings (nomic-embed-text or mxbai-embed-large)
#   Fallback — pure-Python TF-IDF bag-of-words (no native deps)
#
# Invariants enforced:
#   CSS-DETERM-0  : identical text → identical embedding vector (no randomness)
#   CSS-FALLBACK-0: TF-IDF fallback activates when Ollama is unreachable
#   CSS-DIM-0     : embedding dimension is fixed per-session and consistent
#   CSS-COSINE-0  : all similarity scores are cosine similarity ∈ [-1, 1]
#   CSS-PYDROID-0 : no C/native extension required; stdlib + optionally requests

from __future__ import annotations

import hashlib
import logging
import math
import re
import urllib.error
import urllib.request
import json
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "nomic-embed-text"
OLLAMA_TIMEOUT = 5  # seconds

_STOPWORDS = frozenset(
    "a an the and or but if in on at to of for with by from is are was were "
    "be been being have has had do does did will would could should may might "
    "shall can this that these those it its s t re ve ll m d".split()
)

# ── Session-level dimension lock (CSS-DIM-0) ──────────────────────────────────

_DIM_LOCK: Optional[int] = None


def _lock_dim(dim: int) -> None:
    global _DIM_LOCK
    if _DIM_LOCK is None:
        _DIM_LOCK = dim
        logger.debug("CSS-DIM-0: embedding dimension locked to %d", dim)
    elif _DIM_LOCK != dim:
        raise RuntimeError(
            f"CSS-DIM-0 violated: dimension changed from {_DIM_LOCK} to {dim}. "
            "All embeddings in a session must share a fixed dimension."
        )


# ── Ollama embedder ───────────────────────────────────────────────────────────


def _ollama_embed(text: str) -> Optional[List[float]]:
    """Call Ollama /api/embeddings. Returns float list or None on failure."""
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
            vec = body.get("embedding")
            if vec and isinstance(vec, list) and len(vec) > 0:
                return [float(v) for v in vec]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass
    return None


# ── TF-IDF fallback embedder (CSS-PYDROID-0 / CSS-FALLBACK-0) ─────────────────


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


@lru_cache(maxsize=1)
def _get_vocab(corpus_key: str) -> List[str]:
    """Return sorted vocabulary list; corpus_key is a deterministic hash of the corpus."""
    # Vocabulary is built lazily by embed_corpus; this cache is invalidated explicitly.
    return []


# Corpus-level IDF table — populated by embed_corpus()
_IDF: dict[str, float] = {}
_VOCAB: List[str] = []


def _tfidf_embed(text: str) -> List[float]:
    """
    Pure-Python TF-IDF embedding.
    If IDF table is empty (cold-start), falls back to binary bag-of-words
    over a deterministic hash-based feature space (CSS-DETERM-0).
    """
    tokens = _tokenize(text)
    if not tokens:
        # Return zero vector of fixed dim 256
        return [0.0] * 256

    if _IDF:
        # TF-IDF over known vocab
        tf: dict[str, float] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        total = float(len(tokens))
        vec = []
        for word in _VOCAB:
            tf_val = tf.get(word, 0.0) / total
            idf_val = _IDF.get(word, 0.0)
            vec.append(tf_val * idf_val)
        return vec
    else:
        # Cold-start: deterministic hash-space BoW (CSS-DETERM-0)
        DIM = 256
        vec = [0.0] * DIM
        for tok in tokens:
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM  # noqa: S324
            vec[idx] += 1.0
        return vec


# ── Core public API ───────────────────────────────────────────────────────────


def embed(text: str, *, force_fallback: bool = False) -> List[float]:
    """
    Embed *text* and return a float vector.

    Primary path: Ollama (nomic-embed-text).
    Fallback path: pure-Python TF-IDF / hash-BoW (CSS-FALLBACK-0).
    Dimension is locked after the first successful embed (CSS-DIM-0).
    Result is deterministic for identical text (CSS-DETERM-0).
    """
    if not force_fallback:
        vec = _ollama_embed(text)
        if vec is not None:
            _lock_dim(len(vec))
            return vec
        logger.warning(
            "CSS-FALLBACK-0: Ollama unavailable — switching to TF-IDF fallback"
        )

    vec = _tfidf_embed(text)
    _lock_dim(len(vec))
    return vec


# ── Cosine similarity (CSS-COSINE-0) ─────────────────────────────────────────


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity between two vectors ∈ [-1, 1].
    Returns 0.0 when either vector is the zero vector.
    CSS-COSINE-0: this is the canonical similarity function; no random component.
    """
    if len(a) != len(b):
        raise ValueError(
            f"CSS-COSINE-0: dimension mismatch — {len(a)} vs {len(b)}"
        )
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Corpus IDF builder (called by embed_corpus.py) ───────────────────────────


def build_idf(corpus_texts: List[str]) -> None:
    """
    Build the IDF table from a list of corpus texts.
    Populates module-level _IDF and _VOCAB.
    Called once per session by scripts/embed_corpus.py.
    """
    global _IDF, _VOCAB
    df: dict[str, int] = {}
    N = len(corpus_texts)
    if N == 0:
        return
    for text in corpus_texts:
        seen = set(_tokenize(text))
        for tok in seen:
            df[tok] = df.get(tok, 0) + 1
    _VOCAB = sorted(df.keys())
    _IDF = {
        word: math.log((N + 1) / (df[word] + 1)) + 1.0
        for word in _VOCAB
    }
    logger.info(
        "CSS: IDF table built — %d terms from %d documents", len(_VOCAB), N
    )


def reset_dim_lock() -> None:
    """Reset the session-level dimension lock (for testing / reinitialization)."""
    global _DIM_LOCK
    _DIM_LOCK = None
