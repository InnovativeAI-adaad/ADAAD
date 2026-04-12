#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# scripts/embed_corpus.py
# Phase 142 · INNOV-48 · Contextual Semantic Search (CSS)
#
# Pre-compute embeddings for every entry in data/dork/corpus.jsonl and write
# them to data/dork/corpus_embeddings.json.
#
# Usage:
#   python scripts/embed_corpus.py              # embed missing entries only
#   python scripts/embed_corpus.py --force      # re-embed everything
#   python scripts/embed_corpus.py --dry-run    # show what would be done
#   python scripts/embed_corpus.py --fallback   # force TF-IDF (no Ollama)
#
# Invariants enforced:
#   CSS-DETERM-0  : embeddings are written sorted by key; deterministic output
#   CSS-FALLBACK-0: --fallback flag forces TF-IDF path
#   CSS-DIM-0     : dimension is validated consistent across all vectors
#   CSS-PYDROID-0 : no C/native deps required

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dorkllm.embedder import build_idf, embed, reset_dim_lock
from dorkllm.retriever import CORPUS_PATH, EMBEDDINGS_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        logger.error("corpus.jsonl not found at %s", CORPUS_PATH)
        return []
    records = []
    for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if "key" in rec and "answer" in rec:
                records.append(rec)
        except json.JSONDecodeError:
            continue
    return records


def _entry_text(rec: dict) -> str:
    """Canonical text representation of a corpus entry for embedding."""
    parts = [rec["key"]]
    if rec.get("answer"):
        parts.append(rec["answer"])
    for tag in rec.get("tags", []):
        parts.append(str(tag))
    return " ".join(parts)


def _embeddings_digest(emb: dict) -> str:
    """SHA-256 over sorted JSON — used for staleness detection."""
    canonical = json.dumps(emb, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-compute corpus embeddings for CSS (Phase 142)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed all entries even if embeddings already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing any files.",
    )
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="Force TF-IDF fallback (skip Ollama — CSS-FALLBACK-0).",
    )
    parser.add_argument(
        "--output",
        default=str(EMBEDDINGS_PATH),
        help=f"Output path (default: {EMBEDDINGS_PATH})",
    )
    args = parser.parse_args()

    output_path = Path(args.output)

    # Load corpus
    records = _load_corpus()
    if not records:
        logger.error("No records found in corpus. Aborting.")
        return 1

    logger.info("Corpus loaded: %d entries from %s", len(records), CORPUS_PATH)

    # Build IDF table for TF-IDF fallback (CSS-PYDROID-0)
    corpus_texts = [_entry_text(r) for r in records]
    build_idf(corpus_texts)

    # Load existing embeddings
    existing: dict = {}
    if output_path.exists() and not args.force:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            logger.info(
                "Existing embeddings loaded: %d entries (staleness check active)",
                len(existing),
            )
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not parse existing embeddings — re-embedding all.")

    # Determine which entries need embedding
    to_embed = []
    for rec in records:
        key = rec["key"]
        if args.force or key not in existing:
            to_embed.append(rec)

    logger.info(
        "%d entries need embedding (force=%s, fallback=%s)",
        len(to_embed),
        args.force,
        args.fallback,
    )

    if args.dry_run:
        logger.info("[DRY-RUN] Would embed %d entries.", len(to_embed))
        for rec in to_embed[:5]:
            logger.info("  [DRY-RUN] key=%r", rec["key"])
        if len(to_embed) > 5:
            logger.info("  [DRY-RUN] ...and %d more.", len(to_embed) - 5)
        return 0

    if not to_embed:
        logger.info("All entries already embedded. Nothing to do.")
        return 0

    # Reset dim lock before embedding session (CSS-DIM-0)
    reset_dim_lock()

    # Embed
    updated = dict(existing)
    errors = 0
    for i, rec in enumerate(to_embed, 1):
        key = rec["key"]
        text = _entry_text(rec)
        try:
            vec = embed(text, force_fallback=args.fallback)
            updated[key] = vec
            if i % 25 == 0 or i == len(to_embed):
                logger.info("  Progress: %d/%d embedded", i, len(to_embed))
        except Exception as exc:  # noqa: BLE001
            logger.error("  Failed to embed key=%r: %s", key, exc)
            errors += 1

    # CSS-DETERM-0: write sorted by key
    sorted_embeddings = dict(sorted(updated.items()))

    # Validate dimension consistency (CSS-DIM-0)
    dims = set(len(v) for v in sorted_embeddings.values())
    if len(dims) > 1:
        logger.error(
            "CSS-DIM-0 VIOLATION: inconsistent dimensions found: %s", dims
        )
        return 2

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(sorted_embeddings, separators=(",", ":")), encoding="utf-8"
    )

    digest = _embeddings_digest(sorted_embeddings)
    logger.info(
        "Embeddings written: %d entries → %s (dim=%s, digest=%s…, errors=%d)",
        len(sorted_embeddings),
        output_path,
        next(iter(dims)) if dims else "n/a",
        digest[:12],
        errors,
    )

    return 0 if errors == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
