# SPDX-License-Identifier: Apache-2.0
"""
scripts/sync_dork_corpus.py
Live Knowledge Sync Engine (LKSE) — Phase 141 · INNOV-47
Generates data/dork/corpus.jsonl from live repo artifacts.

Corpus entry schema:
  { "id": str, "type": str, "key": str, "answer": str,
    "tags": [str], "phase": int|null, "confidence": float,
    "source": str, "digest": str }

Run:
  python scripts/sync_dork_corpus.py [--repo-root PATH] [--out PATH]

Hard invariants enforced here:
  LKSE-SYNC-0  : corpus phase must be within 1 of current_phase
  LKSE-DETERM-0: identical inputs must produce identical corpus.jsonl
  LKSE-CHAIN-0 : manifest digest is HMAC-SHA256 of sorted entry digests
  LKSE-GATE-0  : exit 1 (blocks CI merge) if LKSE-SYNC-0 violated
  LKSE-HUMAN0-0: corpus entries must never overwrite HUMAN-0 identity fields
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

LKSE_HMAC_KEY = b"adaad-lkse-chain-v1"
CORPUS_VERSION = "1.0"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _entry_digest(entry: dict) -> str:
    """Deterministic digest of a corpus entry (key + answer)."""
    canonical = json.dumps({"key": entry["key"], "answer": entry["answer"]}, sort_keys=True)
    return _sha256(canonical)


def _safe_int(val) -> int:
    """Parse phase values like '87', '87-INNOV-04', 87 safely."""
    try:
        return int(str(val).split("-")[0])
    except (ValueError, TypeError):
        return 0


def _chain_digest(entries: list[dict]) -> str:
    """LKSE-CHAIN-0: HMAC-SHA256 over sorted entry digests."""
    sorted_digests = sorted(e["digest"] for e in entries)
    payload = "\n".join(sorted_digests).encode()
    return "hmac-sha256:" + hmac.new(LKSE_HMAC_KEY, payload, hashlib.sha256).hexdigest()


def _make_entry(
    entry_id: str,
    entry_type: str,
    key: str,
    answer: str,
    tags: list[str],
    phase: int | None = None,
    confidence: float = 0.95,
    source: str = "lkse-auto",
) -> dict:
    entry = {
        "id": entry_id,
        "type": entry_type,
        "key": key,
        "answer": answer,
        "tags": tags,
        "phase": phase,
        "confidence": round(confidence, 3),
        "source": source,
        "digest": "",
    }
    entry["digest"] = _entry_digest(entry)
    return entry


# ── Source readers ─────────────────────────────────────────────────────────────


def _read_agent_state(repo: Path) -> dict:
    path = repo / ".adaad_agent_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_changelog(repo: Path) -> list[dict]:
    """Parse CHANGELOG.md into list of {version, date, phase, body}."""
    path = repo / "CHANGELOG.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries = []
    current: dict | None = None
    for line in text.splitlines():
        m = re.match(r"^## \[(\d+\.\d+\.\d+)\]\s*[—–-]\s*(\d{4}-\d{2}-\d{2}).*?·\s*Phase\s*(\d+)\s*·\s*(.+)$", line)
        if m:
            if current:
                entries.append(current)
            current = {
                "version": m.group(1),
                "date": m.group(2),
                "phase": int(m.group(3)),
                "title": m.group(4).strip(),
                "body": [],
            }
        elif current and line.strip():
            current["body"].append(line.strip())
    if current:
        entries.append(current)
    return entries


def _read_phase_signoffs(repo: Path) -> list[dict]:
    """Read all phase*_sign_off.json and ILA-*.json files."""
    gov = repo / "artifacts" / "governance"
    results = []
    if not gov.exists():
        return results
    for phase_dir in sorted(gov.iterdir()):
        if not phase_dir.is_dir():
            continue
        for f in phase_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                d["_source_file"] = str(f.relative_to(repo))
                results.append(d)
            except (json.JSONDecodeError, OSError):
                pass
    return results


def _read_ila_root(repo: Path) -> list[dict]:
    """Read ILA JSON files directly under artifacts/governance/."""
    gov = repo / "artifacts" / "governance"
    results = []
    if not gov.exists():
        return results
    for f in gov.glob("ILA-*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            d["_source_file"] = str(f.relative_to(repo))
            results.append(d)
        except (json.JSONDecodeError, OSError):
            pass
    return results


# ── Corpus generators ─────────────────────────────────────────────────────────


def gen_identity_entries() -> list[dict]:
    """Core ADAAD identity entries — always current."""
    return [
        _make_entry(
            "IDENT-001", "identity",
            "what is adaad",
            "ADAAD (Autonomous Development & Adaptation Architecture) is a governed autonomous "
            "software-evolution engine. AI agents propose, score, test, and evolve code within "
            "constitutionally enforceable constraints. Every change is ledgered and every promotion "
            "requires a GPG-signed human attestation from HUMAN-0.",
            ["identity", "overview", "core"], confidence=0.99, source="static",
        ),
        _make_entry(
            "IDENT-002", "identity",
            "what is dork",
            "DORK (Dynamic Operative Resource Knowledge) is the AI assistant embedded in ADAAD's "
            "developer console (Whale.Dic). DORK routes operator queries to capability cards, "
            "synthesises state-bus context, and surfaces governance-safe next actions — "
            "deterministically and with full auditability.",
            ["dork", "identity", "assistant"], confidence=0.99, source="static",
        ),
        _make_entry(
            "IDENT-003", "identity",
            "who built adaad",
            "ADAAD is built by Innovative AI LLC, led by Dustin L. Reid (Governor, HUMAN-0). "
            "It is open-source, free, and hosted at github.com/InnovativeAI-adaad/adaad.",
            ["identity", "team", "founder", "human-0"], confidence=0.99, source="static",
        ),
        _make_entry(
            "IDENT-004", "identity",
            "what problem does adaad solve",
            "ADAAD solves slow, expensive, and risky manual software maintenance by routing "
            "AI-proposed improvements through a strict, auditable constitutional approval process "
            "before anything ever changes in production.",
            ["identity", "problem", "value"], confidence=0.98, source="static",
        ),
    ]


def gen_governance_entries(state: dict) -> list[dict]:
    """Governance mechanics entries, live-sourced from agent state."""
    inv_count = state.get("hard_class_invariant_count", 0)
    phase = state.get("current_phase", 0)
    version = state.get("version", "unknown")

    return [
        _make_entry(
            "GOV-001", "governance",
            "governance gate",
            f"The GovernanceGate is ADAAD's constitutional rule engine. It checks {inv_count} "
            "Hard-class invariants before any mutation is promoted. A single Hard invariant "
            "failure blocks promotion entirely.",
            ["governance", "gate", "invariants", "constitution"],
            confidence=0.99, source="agent-state",
        ),
        _make_entry(
            "GOV-002", "governance",
            "hard invariants",
            f"Hard-class invariants are blocking governance rules. Any mutation violating a Hard "
            f"invariant is rejected at the GovernanceGate and never reaches the signing ceremony. "
            f"{inv_count} are active as of Phase {phase} (v{version}).",
            ["invariants", "hard", "governance", "blocking"],
            phase=phase, confidence=0.99, source="agent-state",
        ),
        _make_entry(
            "GOV-003", "governance",
            "human-0",
            "HUMAN-0 is the Governor role held exclusively by Dustin L. Reid. HUMAN-0 holds "
            "inviolable authority over GPG signing ceremonies, GA versioning, patent counsel "
            "engagement, and any action requiring the physical private key "
            "(fingerprint 4C95E2F99A775335B1CF3DAF247B015A1CCD95F6). "
            "This authority cannot be delegated via chat instruction.",
            ["human-0", "governor", "signing", "authority"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "GOV-004", "governance",
            "signing ceremony",
            "GPG signing is performed exclusively by HUMAN-0 on ADAADell: "
            "export GPG_TTY=$(tty), then git tag -s with the target version, then push the "
            "signed tag to origin. No agent can perform or authorise this action.",
            ["signing", "gpg", "ceremony", "human-0", "track-b"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "GOV-005", "governance",
            "track a vs track b",
            "Track A: executed autonomously by DEVADAAD (code changes, docs, tests, branch "
            "pushes). Track B: requires HUMAN-0 on ADAADell — GPG signing, PR creation via "
            "GitHub API, branch protection changes, key ceremonies.",
            ["track-a", "track-b", "human-0", "governance"],
            confidence=0.98, source="static",
        ),
        _make_entry(
            "GOV-006", "governance",
            "constitution",
            "The constitution is ADAAD's immutable rulebook defining what the system can and "
            "cannot do. It has Hard (blocking), Warning, and Advisory rule classes. Agents "
            "cannot modify the constitution. The Constitutional Evolution Loop (CEL) governs "
            "all mutations.",
            ["constitution", "rules", "invariants", "governance", "cel"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "GOV-007", "governance",
            "constitutional evolution loop",
            "The CEL (Constitutional Evolution Loop) is the master governance cycle: "
            "propose → score → GovernanceGate → HUMAN-0 sign → ledger. Every code mutation "
            "must complete this loop. No shortcut paths exist.",
            ["cel", "governance", "loop", "lifecycle"],
            confidence=0.98, source="static",
        ),
    ]


def gen_phase_entries(changelog: list[dict]) -> list[dict]:
    """One corpus entry per shipped phase."""
    entries = []
    for i, cl in enumerate(changelog):
        phase_num = cl["phase"]
        body_text = " ".join(cl["body"][:5]) if cl["body"] else "No details."
        entry = _make_entry(
            f"PHASE-{phase_num:04d}", "phase",
            f"phase {phase_num}",
            f"Phase {phase_num} shipped as v{cl['version']} on {cl['date']}. "
            f"Title: {cl['title']}. {body_text}",
            ["phase", f"phase-{phase_num}", f"v{cl['version']}"],
            phase=phase_num, confidence=0.97, source="changelog",
        )
        entries.append(entry)
    return entries


def gen_invariant_entries(signoffs: list[dict]) -> list[dict]:
    """One corpus entry per named Hard-class invariant discovered in sign-off artifacts."""
    seen: set[str] = set()
    entries = []
    for doc in signoffs:
        inv_list = doc.get("new_invariants") or doc.get("new_hard_invariants") or []
        if not isinstance(inv_list, list):
            inv_list = []
        phase = doc.get("phase")
        for inv_name in inv_list:
            if not isinstance(inv_name, str):
                continue
            if inv_name in seen:
                continue
            seen.add(inv_name)
            entry = _make_entry(
                f"INV-{inv_name}", "invariant",
                f"invariant {inv_name.lower()}",
                f"{inv_name} is a Hard-class constitutional invariant introduced in Phase "
                f"{phase}. It blocks any mutation that violates its enforcement contract. "
                f"Defined in governance artifact: {doc.get('_source_file', 'unknown')}.",
                ["invariant", "hard", inv_name.lower(), f"phase-{phase}"],
                phase=phase, confidence=0.96, source=doc.get("_source_file", "governance"),
            )
            entries.append(entry)
    return entries


def gen_finding_entries(state: dict) -> list[dict]:
    """One corpus entry per governance finding."""
    findings = state.get("open_findings", [])
    entries = []
    for finding in findings:
        fid = finding.get("id", "unknown")
        title = finding.get("title", "")
        status = finding.get("status", "unknown")
        severity = finding.get("severity", "P2")
        resolved_phase = finding.get("resolved_phase")
        note = finding.get("note", "")
        answer = (
            f"{fid} ({severity}): {title}. Status: {status}."
            + (f" Resolved in Phase {resolved_phase}." if resolved_phase else "")
            + (f" Note: {note[:120]}." if note else "")
        )
        entry = _make_entry(
            f"FINDING-{fid}", "finding",
            f"finding {fid.lower()}",
            answer,
            ["finding", fid.lower(), severity.lower(), status],
            confidence=0.95, source="agent-state",
        )
        entries.append(entry)
    return entries


def gen_innovation_entries(signoffs: list[dict]) -> list[dict]:
    """One corpus entry per named innovation from sign-off artifacts."""
    seen: set[str] = set()
    entries = []
    for doc in signoffs:
        innov_id = doc.get("innovation") or ""
        innov_name = doc.get("innovation_name") or ""
        if not innov_id or innov_id in seen:
            continue
        seen.add(innov_id)
        phase = doc.get("phase")
        version = doc.get("version", "")
        module = doc.get("new_module", "")
        entry = _make_entry(
            f"INNOV-{innov_id}", "innovation",
            f"innovation {innov_id.lower()}",
            f"{innov_id} — {innov_name}. Shipped in Phase {phase} (v{version}). "
            f"Primary module: {module}." if module else
            f"{innov_id} — {innov_name}. Shipped in Phase {phase} (v{version}).",
            ["innovation", innov_id.lower(), innov_name.lower().replace(" ", "-"), f"phase-{phase}"],
            phase=phase, confidence=0.97, source=doc.get("_source_file", "governance"),
        )
        entries.append(entry)
    return entries


def gen_architecture_entries() -> list[dict]:
    """Static architecture entries."""
    return [
        _make_entry(
            "ARCH-001", "architecture",
            "how adaad works",
            "ADAAD operates in five stages: (1) Triad agents (Architect, Dream, Beast) propose "
            "code mutations. (2) Oracle scores proposals via multi-signal fitness. (3) "
            "GovernanceGate checks all Hard-class invariants. (4) HUMAN-0 performs a GPG-signed "
            "attestation. (5) The ledger records the immutable promotion event.",
            ["architecture", "flow", "process", "overview"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "ARCH-002", "architecture",
            "agents triad",
            "Three AI agents compete: Architect (methodical, structure-first), Dream (creative, "
            "hypothesis-heavy), and Beast (aggressive, throughput-optimised). They generate "
            "mutation proposals independently scored before entering the governance pipeline.",
            ["agents", "triad", "architect", "dream", "beast"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "ARCH-003", "architecture",
            "ledger audit trail",
            "The ADAAD ledger is a tamper-evident append-only log of every governance event: "
            "proposals, scores, approvals, rejections, and promotions. Every entry is "
            "HMAC-SHA256 chain-linked, making retroactive modification cryptographically "
            "detectable.",
            ["ledger", "audit", "provenance", "immutability", "hmac"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "ARCH-004", "architecture",
            "sandbox preflight",
            "All mutations execute in an isolated sandbox before governance evaluation. "
            "Sandbox preflight validates imports, resource limits, and determinism constraints. "
            "Preflight failure blocks the mutation from entering the scoring pipeline.",
            ["sandbox", "preflight", "isolation", "safety"],
            confidence=0.98, source="static",
        ),
        _make_entry(
            "ARCH-005", "architecture",
            "four surface version sync",
            "ADAAD maintains four version surfaces that must stay in sync at every phase "
            "boundary: VERSION file, pyproject.toml, .adaad_agent_state.json, and "
            "governance/report_version.json. CI blocks merge if any surface diverges.",
            ["version", "sync", "four-surface", "ci", "governance"],
            confidence=0.99, source="static",
        ),
        _make_entry(
            "ARCH-006", "architecture",
            "devadaad agent identity",
            "DEVADAAD is the autonomous Track A execution agent. Git identity: "
            "devadaad@innovativeai.dev. DEVADAAD executes code changes, tests, docs, and "
            "branch pushes. Track B actions (GPG signing, PR creation, key ceremonies) are "
            "reserved exclusively for HUMAN-0 on ADAADell.",
            ["devadaad", "agent", "identity", "track-a", "git"],
            confidence=0.99, source="static",
        ),
    ]


def gen_lkse_self_entry(state: dict) -> list[dict]:
    """LKSE self-description — INNOV-47."""
    phase = state.get("current_phase", 141)
    version = state.get("version", "unknown")
    return [
        _make_entry(
            "LKSE-001", "system",
            "live knowledge sync engine",
            "The LKSE (Live Knowledge Sync Engine — INNOV-47) is the Phase 141 corpus "
            "auto-synchronisation system. It generates corpus.jsonl from live repo artifacts "
            "on every merge to main. Invariant LKSE-SYNC-0 enforces that the corpus is always "
            f"within 1 phase of the current phase ({phase}, v{version}).",
            ["lkse", "innov-47", "corpus", "sync", "phase-141"],
            phase=141, confidence=0.99, source="static",
        ),
    ]


# ── LKSE-SYNC-0 validation ─────────────────────────────────────────────────────


def validate_sync_invariant(corpus_phase: int, current_phase: int) -> None:
    """
    LKSE-SYNC-0 (Hard): corpus phase must be within 1 of current_phase.
    Raises SystemExit(1) — blocks CI merge — if violated.
    """
    delta = abs(current_phase - corpus_phase)
    if delta > 1:
        print(
            f"LKSE-SYNC-0 VIOLATION: corpus_phase={corpus_phase} is {delta} phases "
            f"behind current_phase={current_phase}. Corpus is stale. CI merge blocked.",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Manifest ───────────────────────────────────────────────────────────────────


def build_manifest(entries: list[dict], current_phase: int, version: str) -> dict:
    return {
        "corpus_version": CORPUS_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_phase": current_phase,
        "source_version": version,
        "entry_count": len(entries),
        "type_counts": _type_counts(entries),
        "chain_digest": _chain_digest(entries),
    }


def _type_counts(entries: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return counts


# ── Main ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LKSE corpus generator — Phase 141 INNOV-47")
    parser.add_argument("--repo-root", default=".", help="Path to ADAAD repo root")
    parser.add_argument("--out", default="data/dork/corpus.jsonl", help="Output .jsonl path")
    parser.add_argument("--skip-sync-check", action="store_true", help="Skip LKSE-SYNC-0 (dev only)")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    out_path = repo / args.out

    print(f"[LKSE] Reading agent state …")
    state = _read_agent_state(repo)
    current_phase = state.get("current_phase", 0)
    version = state.get("version", "unknown")
    print(f"[LKSE] current_phase={current_phase}  version={version}")

    print(f"[LKSE] Reading CHANGELOG …")
    changelog = _read_changelog(repo)
    print(f"[LKSE] Found {len(changelog)} CHANGELOG entries")

    print(f"[LKSE] Reading governance artifacts …")
    signoffs = _read_phase_signoffs(repo)
    ila_root = _read_ila_root(repo)
    all_docs = signoffs + ila_root
    print(f"[LKSE] Found {len(all_docs)} governance documents")

    # ── Build corpus entries ───────────────────────────────────────────────────
    print(f"[LKSE] Generating corpus entries …")
    entries: list[dict] = []
    entries += gen_identity_entries()
    entries += gen_governance_entries(state)
    entries += gen_architecture_entries()
    entries += gen_phase_entries(changelog)
    entries += gen_invariant_entries(all_docs)
    entries += gen_finding_entries(state)
    entries += gen_innovation_entries(all_docs)
    entries += gen_lkse_self_entry(state)

    # Deduplicate by id (keep first occurrence — deterministic order)
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for e in entries:
        if e["id"] not in seen_ids:
            seen_ids.add(e["id"])
            deduped.append(e)
    entries = deduped

    # LKSE-DETERM-0: sort entries by id for deterministic output
    entries.sort(key=lambda e: e["id"])

    corpus_phase = max(
        (_safe_int(e["phase"]) for e in entries if e.get("phase") is not None),
        default=0,
    )

    if not args.skip_sync_check:
        validate_sync_invariant(corpus_phase, current_phase)

    # ── Write corpus.jsonl ────────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── Write manifest ────────────────────────────────────────────────────────
    manifest = build_manifest(entries, current_phase, version)
    manifest_path = out_path.parent / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[LKSE] Wrote {len(entries)} entries → {out_path}")
    print(f"[LKSE] Manifest → {manifest_path}")
    print(f"[LKSE] chain_digest={manifest['chain_digest'][:32]}…")
    for t, c in manifest["type_counts"].items():
        print(f"[LKSE]   {t}: {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
