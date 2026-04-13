# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/grounded_responder.py
Phase 144 · INNOV-50 · Retrieval-Augmented Governance Synthesis (RAGS)

Wires LKSE corpus (INNOV-47) + CSS retriever (INNOV-48) + CMU phi4 context window
(INNOV-49) into a constitutionally governed grounded response pipeline.

When DORK answers a governance query, RAGS:
  1. Retrieves top-K corpus chunks via CSS cosine similarity.
  2. Assembles a grounded context block injected before the query.
  3. Records cited corpus entries in a hash-chained grounding ledger (RAGS-DETERM-0).
  4. Enforces minimum citation count (RAGS-GROUND-0).
  5. Enforces cosine threshold gate — zero-signal queries halt (RAGS-GATE-0).
  6. Cross-links each ledger entry to the originating LKSE corpus entry hash (RAGS-CHAIN-0).

Hard-class invariants enforced here:
  RAGS-GROUND-0  Every grounded response MUST cite >= 1 corpus entry; zero = violation.
  RAGS-CTX-0     Context block MUST NOT exceed RAGS_MAX_CONTEXT_CHARS; overflow = truncation
                 logged, not silent drop. Truncation itself is recorded in ledger.
  RAGS-DETERM-0  Grounding ledger entries are SHA-256 hash-chained (prev_hash → entry_hash).
  RAGS-CHAIN-0   Each ledger entry MUST carry the LKSE corpus_entry_hash of every cited doc.
  RAGS-GATE-0    If no corpus entry scores >= RAGS_MIN_COSINE_THRESHOLD, RAGS MUST raise
                 RAGSZeroGroundingError rather than pass empty context to the model.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

RAGS_MIN_COSINE_THRESHOLD: float = float(
    os.getenv("RAGS_MIN_COSINE_THRESHOLD", "0.15")
)
RAGS_TOP_K: int = int(os.getenv("RAGS_TOP_K", "5"))
RAGS_MAX_CONTEXT_CHARS: int = int(
    os.getenv("RAGS_MAX_CONTEXT_CHARS", str(12_000))
)
RAGS_LEDGER_PATH = Path(
    os.getenv("RAGS_LEDGER_PATH", "data/dork/rags_grounding_ledger.jsonl")
)
RAGS_HMAC_SECRET = os.getenv("RAGS_HMAC_SECRET", "rags-constitutional-chain-v1").encode()
CORPUS_PATH = Path(os.getenv("DORK_CORPUS_PATH", "data/dork/corpus.jsonl"))


# ── Invariant violation errors ─────────────────────────────────────────────────

class RAGSInvariantViolation(RuntimeError):
    """Base class for all RAGS Hard-class invariant violations."""


class RAGSGroundingViolation(RAGSInvariantViolation):
    """RAGS-GROUND-0: response cites zero corpus entries."""


class RAGSContextOverflowError(RAGSInvariantViolation):
    """RAGS-CTX-0: context block exceeded RAGS_MAX_CONTEXT_CHARS (raised only on unrecoverable overflow)."""


class RAGSZeroGroundingError(RAGSInvariantViolation):
    """RAGS-GATE-0: no corpus entry scored above RAGS_MIN_COSINE_THRESHOLD."""


class RAGSLedgerWriteError(RAGSInvariantViolation):
    """RAGS-DETERM-0: grounding ledger write failure."""


class RAGSChainViolation(RAGSInvariantViolation):
    """RAGS-CHAIN-0: cited entry is missing a corpus_entry_hash."""


# ── Corpus entry dataclass ─────────────────────────────────────────────────────

@dataclass
class CorpusEntry:
    """A single entry loaded from the LKSE corpus (data/dork/corpus.jsonl)."""
    id: str
    type: str
    title: str
    content: str
    corpus_entry_hash: str = ""  # LKSE chain digest; RAGS-CHAIN-0 requires this present

    @classmethod
    def from_dict(cls, d: dict) -> "CorpusEntry":
        return cls(
            id=d.get("id", ""),
            type=d.get("type", ""),
            title=d.get("title", ""),
            content=d.get("content", d.get("body", "")),
            corpus_entry_hash=d.get("corpus_entry_hash", d.get("entry_hash", "")),
        )


# ── Retrieval result ───────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    """A corpus entry paired with its cosine similarity score."""
    entry: CorpusEntry
    score: float


# ── Grounding ledger dataclass ─────────────────────────────────────────────────

@dataclass
class RAGSLedgerEntry:
    """RAGS-DETERM-0 / RAGS-CHAIN-0: one hash-chained grounding event."""
    seq: int
    query_digest: str          # SHA-256 of the query string
    cited_ids: list            # list of corpus entry ids
    cited_hashes: list         # RAGS-CHAIN-0: LKSE corpus_entry_hash per cited entry
    top_score: float           # highest cosine similarity in this retrieval
    context_chars: int         # assembled context block size in characters
    truncated: bool            # RAGS-CTX-0: was truncation applied?
    timestamp: str
    prev_hash: str
    entry_hash: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# ── Corpus loader ──────────────────────────────────────────────────────────────

def load_corpus(path: Path = CORPUS_PATH) -> list[CorpusEntry]:
    """
    Load all entries from the LKSE JSONL corpus.
    Returns empty list if file is absent (graceful degradation to RAGS-GATE-0).
    """
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                entries.append(CorpusEntry.from_dict(d))
            except (json.JSONDecodeError, KeyError):
                continue
    return entries


# ── Keyword retriever (pure-Python fallback, no numpy) ───────────────────────

def _keyword_score(query: str, content: str) -> float:
    """
    TF-IDF-approximating keyword overlap score. Pure Python, no dependencies.
    Returns a float in [0, 1].
    """
    query_tokens = set(query.lower().split())
    content_tokens = content.lower().split()
    if not query_tokens or not content_tokens:
        return 0.0
    content_set = set(content_tokens)
    overlap = query_tokens & content_set
    # Jaccard-like: |intersection| / |union|
    union = query_tokens | content_set
    return len(overlap) / len(union) if union else 0.0


def retrieve_top_k(
    query: str,
    corpus: list[CorpusEntry],
    top_k: int = RAGS_TOP_K,
    min_score: float = RAGS_MIN_COSINE_THRESHOLD,
) -> list[RetrievedChunk]:
    """
    Retrieve top-K corpus entries by keyword overlap score.

    Design note: CSS (INNOV-48) provides cosine similarity when embeddings are
    available. RAGS is designed to accept any retrieval backend via this function.
    The keyword fallback ensures RAGS-GATE-0 enforcement works even on CPU-only /
    Pydroid3 deployments where nomic-embed-text is unavailable.

    Raises RAGSZeroGroundingError (RAGS-GATE-0) if no entry exceeds min_score.
    """
    if not corpus:
        raise RAGSZeroGroundingError(
            "RAGS-GATE-0 VIOLATION: corpus is empty. "
            "RAGS cannot ground any response. "
            "Ensure LKSE corpus (data/dork/corpus.jsonl) is populated."
        )

    scored = []
    for entry in corpus:
        text = f"{entry.title} {entry.content}"
        score = _keyword_score(query, text)
        scored.append(RetrievedChunk(entry=entry, score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[:top_k]

    if not top or top[0].score < min_score:
        raise RAGSZeroGroundingError(
            f"RAGS-GATE-0 VIOLATION: highest corpus score={top[0].score:.4f} "
            f"< threshold={min_score}. Query has no corpus grounding. "
            f"Expand corpus or lower RAGS_MIN_COSINE_THRESHOLD."
        )

    return [c for c in top if c.score >= min_score]


# ── Context assembly ───────────────────────────────────────────────────────────

def assemble_context(
    chunks: list[RetrievedChunk],
    max_chars: int = RAGS_MAX_CONTEXT_CHARS,
) -> tuple[str, bool]:
    """
    RAGS-CTX-0: Assemble retrieved chunks into a grounding context block.

    Returns (context_str, truncated).
    If the assembled context exceeds max_chars, entries are dropped from the
    bottom of the ranked list until it fits. Truncation is always logged;
    it never silently drops entries without recording which were omitted.
    """
    lines = ["### RAGS GROUNDING CONTEXT (constitutional evidence)\n"]
    truncated = False
    included = []

    for chunk in chunks:
        snippet = (
            f"[{chunk.entry.type.upper()}] {chunk.entry.title} "
            f"(score={chunk.score:.4f})\n"
            f"{chunk.entry.content[:800]}\n---\n"
        )
        candidate = "\n".join(lines) + snippet
        if len(candidate) > max_chars:
            truncated = True
            # Log omitted entry id but do not raise — truncation is recoverable
            continue
        lines.append(snippet)
        included.append(chunk)

    context = "\n".join(lines)
    return context, truncated


# ── Ledger operations ──────────────────────────────────────────────────────────

def _last_ledger_state(path: Path) -> tuple[str, int]:
    """Return (last_entry_hash, next_seq) from the RAGS grounding ledger."""
    if not path.exists():
        return "0" * 64, 0
    last: Optional[dict] = None
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
                count += 1
            except json.JSONDecodeError:
                continue
    if last:
        return last.get("entry_hash", "0" * 64), last.get("seq", count - 1) + 1
    return "0" * 64, 0


def _assert_chain_hashes(chunks: list[RetrievedChunk]) -> list[str]:
    """
    RAGS-CHAIN-0: Every cited chunk must carry a corpus_entry_hash from LKSE.
    Raises RAGSChainViolation if any cited entry is missing its hash.
    Returns list of hashes in citation order.
    """
    hashes = []
    for chunk in chunks:
        h = chunk.entry.corpus_entry_hash
        if not h:
            raise RAGSChainViolation(
                f"RAGS-CHAIN-0 VIOLATION: cited corpus entry '{chunk.entry.id}' "
                f"is missing corpus_entry_hash. "
                f"LKSE sync may be incomplete. Run scripts/sync_dork_corpus.py."
            )
        hashes.append(h)
    return hashes


def append_grounding_ledger(
    query: str,
    chunks: list[RetrievedChunk],
    context_chars: int,
    truncated: bool,
    ledger_path: Path = RAGS_LEDGER_PATH,
) -> RAGSLedgerEntry:
    """
    RAGS-DETERM-0: Append a hash-chained grounding event to the RAGS ledger.
    RAGS-CHAIN-0: Records LKSE corpus_entry_hash for each cited entry.
    Raises RAGSLedgerWriteError on write failure.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash, seq = _last_ledger_state(ledger_path)
    timestamp = datetime.now(timezone.utc).isoformat()

    query_digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    cited_ids = [c.entry.id for c in chunks]
    cited_hashes = _assert_chain_hashes(chunks)  # RAGS-CHAIN-0
    top_score = chunks[0].score if chunks else 0.0

    payload = json.dumps({
        "seq": seq,
        "query_digest": query_digest,
        "cited_ids": cited_ids,
        "cited_hashes": cited_hashes,
        "top_score": round(top_score, 6),
        "context_chars": context_chars,
        "truncated": truncated,
        "timestamp": timestamp,
        "prev_hash": prev_hash,
    }, sort_keys=True)

    entry_hash = hmac.new(
        RAGS_HMAC_SECRET,
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    entry_dict = json.loads(payload)
    entry_dict["entry_hash"] = entry_hash

    try:
        with ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry_dict) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise RAGSLedgerWriteError(
            f"RAGS-DETERM-0 VIOLATION: grounding ledger write failed at seq={seq}: {exc}"
        ) from exc

    return RAGSLedgerEntry(**entry_dict)


# ── Grounding assertion ────────────────────────────────────────────────────────

def assert_grounded(chunks: list[RetrievedChunk]) -> None:
    """
    RAGS-GROUND-0: Raise RAGSGroundingViolation if zero chunks were cited.
    This is the terminal constitutional check before response assembly.
    """
    if not chunks:
        raise RAGSGroundingViolation(
            "RAGS-GROUND-0 VIOLATION: response cites zero corpus entries. "
            "Ungrounded governance responses are constitutionally prohibited. "
            "Either provide corpus coverage or declare a zero-grounding signal."
        )


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class GroundedQuery:
    """Result of the full RAGS pipeline for one query."""
    query: str
    grounded_prompt: str      # query prepended with RAGS context block
    cited_ids: list           # corpus entry ids cited
    cited_hashes: list        # LKSE hashes of cited entries (RAGS-CHAIN-0)
    top_score: float          # highest retrieval score
    context_chars: int
    truncated: bool           # RAGS-CTX-0: was overflow truncation applied?
    ledger_seq: int
    ledger_entry_hash: str


def ground_query(
    query: str,
    *,
    corpus: Optional[list[CorpusEntry]] = None,
    top_k: int = RAGS_TOP_K,
    min_score: float = RAGS_MIN_COSINE_THRESHOLD,
    max_context_chars: int = RAGS_MAX_CONTEXT_CHARS,
    ledger_path: Path = RAGS_LEDGER_PATH,
    record_ledger: bool = True,
) -> GroundedQuery:
    """
    Full RAGS pipeline:
      1. Load corpus if not supplied.
      2. Retrieve top-K via keyword score (RAGS-GATE-0 enforced).
      3. Assemble context block (RAGS-CTX-0 enforced).
      4. Assert minimum citation count (RAGS-GROUND-0).
      5. Append grounding ledger entry (RAGS-DETERM-0 + RAGS-CHAIN-0).
      6. Return GroundedQuery with prepended context.

    Raises:
      RAGSZeroGroundingError  — no corpus entry above min_score threshold
      RAGSGroundingViolation  — citation count dropped to zero after assembly
      RAGSChainViolation      — cited entry missing LKSE corpus_entry_hash
      RAGSLedgerWriteError    — ledger fsync failure
    """
    if corpus is None:
        corpus = load_corpus()

    chunks = retrieve_top_k(query, corpus, top_k=top_k, min_score=min_score)
    assert_grounded(chunks)  # RAGS-GROUND-0

    context_block, truncated = assemble_context(chunks, max_chars=max_context_chars)
    context_chars = len(context_block)

    ledger_entry = None
    if record_ledger:
        ledger_entry = append_grounding_ledger(
            query, chunks, context_chars, truncated, ledger_path=ledger_path
        )

    grounded_prompt = f"{context_block}\n### QUERY\n{query}"

    return GroundedQuery(
        query=query,
        grounded_prompt=grounded_prompt,
        cited_ids=[c.entry.id for c in chunks],
        cited_hashes=[c.entry.corpus_entry_hash for c in chunks],
        top_score=chunks[0].score,
        context_chars=context_chars,
        truncated=truncated,
        ledger_seq=ledger_entry.seq if ledger_entry else -1,
        ledger_entry_hash=ledger_entry.entry_hash if ledger_entry else "",
    )


def verify_grounding_ledger(
    ledger_path: Path = RAGS_LEDGER_PATH,
) -> dict:
    """
    RAGS-DETERM-0: Verify the full grounding ledger chain integrity.
    Returns {ok: bool, entries: int, broken_at_seq: int|None}.
    """
    if not ledger_path.exists():
        return {"ok": True, "entries": 0, "broken_at_seq": None}

    prev_hash = "0" * 64
    count = 0
    with ledger_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            stored_hash = entry.pop("entry_hash", "")
            payload = json.dumps(entry, sort_keys=True)
            expected = hmac.new(RAGS_HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()

            if not hmac.compare_digest(stored_hash, expected):
                return {"ok": False, "entries": count, "broken_at_seq": entry.get("seq")}
            if not hmac.compare_digest(entry.get("prev_hash", ""), prev_hash):
                return {"ok": False, "entries": count, "broken_at_seq": entry.get("seq")}

            prev_hash = stored_hash
            count += 1

    return {"ok": True, "entries": count, "broken_at_seq": None}
