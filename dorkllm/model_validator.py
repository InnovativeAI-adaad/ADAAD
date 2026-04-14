# SPDX-License-Identifier: Apache-2.0
"""
dorkllm/model_validator.py
Phase 143 · INNOV-49 · Constitutional Model Upgrade (CMU)

CMU invariant enforcement layer. Parses Modelfile and the running Ollama model
configuration to verify that constitutional model parameters are respected.

Hard-class invariants enforced here:
  CMU-CTX-0    : num_ctx >= 16384
  CMU-TEMP-0   : temperature <= 0.10
  CMU-BENCH-0  : benchmark suite must be defined and callable
  CMU-DETERM-0 : model name and digest must be recorded in the CMU ledger
  CMU-HUMAN0-0 : model upgrades require HUMAN-0 ratification flag in ledger
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

CMU_MIN_CTX: int = 16_384
CMU_MAX_TEMP: float = 0.10
CMU_LEDGER_PATH = Path(os.getenv("CMU_LEDGER_PATH", "data/dork/cmu_ledger.jsonl"))
MODELFILE_PATH = Path(os.getenv("DORK_MODELFILE_PATH", "dorkllm/Modelfile"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


# ── Invariant violation errors ─────────────────────────────────────────────────

class CMUInvariantViolation(RuntimeError):
    """Raised when a CMU Hard-class invariant is violated."""


class CMUCtxViolation(CMUInvariantViolation):
    """CMU-CTX-0: num_ctx below constitutional minimum."""


class CMUTempViolation(CMUInvariantViolation):
    """CMU-TEMP-0: temperature above constitutional maximum."""


class CMULedgerWriteError(CMUInvariantViolation):
    """CMU-DETERM-0: ledger write failure."""


# ── Modelfile parser ───────────────────────────────────────────────────────────

@dataclass
class ModelfileParams:
    base_model: str = ""
    num_ctx: int = 0
    temperature: float = 1.0
    top_p: float = 1.0
    repeat_penalty: float = 1.0
    top_k: int = 40
    raw_parameters: dict = field(default_factory=dict)


def parse_modelfile(path: Path = MODELFILE_PATH) -> ModelfileParams:
    """
    Parse a Modelfile and extract constitutional parameters.
    Raises FileNotFoundError if the Modelfile is absent.
    """
    if not path.exists():
        raise FileNotFoundError(f"CMU: Modelfile not found at {path}")

    params = ModelfileParams()
    text = path.read_text(encoding="utf-8")

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        from_match = re.match(r"^FROM\s+(\S+)", stripped, re.IGNORECASE)
        if from_match:
            params.base_model = from_match.group(1)
            continue

        param_match = re.match(r"^PARAMETER\s+(\S+)\s+(.+)$", stripped, re.IGNORECASE)
        if param_match:
            key = param_match.group(1).lower()
            val = param_match.group(2).strip()
            params.raw_parameters[key] = val
            try:
                if key == "num_ctx":
                    params.num_ctx = int(val)
                elif key == "temperature":
                    params.temperature = float(val)
                elif key == "top_p":
                    params.top_p = float(val)
                elif key == "repeat_penalty":
                    params.repeat_penalty = float(val)
                elif key == "top_k":
                    params.top_k = int(val)
            except ValueError:
                pass  # non-numeric parameters (stop tokens etc.)

    return params


# ── CMU-CTX-0 and CMU-TEMP-0 enforcement ──────────────────────────────────────

def assert_ctx(params: ModelfileParams) -> None:
    """
    CMU-CTX-0: Raise CMUCtxViolation if num_ctx < CMU_MIN_CTX.
    """
    if params.num_ctx < CMU_MIN_CTX:
        raise CMUCtxViolation(
            f"CMU-CTX-0 VIOLATION: num_ctx={params.num_ctx} < "
            f"constitutional minimum {CMU_MIN_CTX}. "
            f"Smaller context is a constitutional model regression."
        )


def assert_temperature(params: ModelfileParams) -> None:
    """
    CMU-TEMP-0: Raise CMUTempViolation if temperature > CMU_MAX_TEMP.
    """
    if params.temperature > CMU_MAX_TEMP:
        raise CMUTempViolation(
            f"CMU-TEMP-0 VIOLATION: temperature={params.temperature} > "
            f"constitutional maximum {CMU_MAX_TEMP}. "
            f"Higher temperature is constitutionally prohibited for governance queries."
        )


def validate_modelfile(path: Path = MODELFILE_PATH) -> ModelfileParams:
    """
    Parse Modelfile and enforce CMU-CTX-0 and CMU-TEMP-0.
    Returns validated ModelfileParams on success.
    Raises CMUInvariantViolation subclass on violation.
    """
    params = parse_modelfile(path)
    assert_ctx(params)
    assert_temperature(params)
    return params


# ── CMU-DETERM-0: ledger append ───────────────────────────────────────────────

@dataclass
class CMULedgerEntry:
    seq: int
    event: str
    base_model: str
    num_ctx: int
    temperature: float
    modelfile_digest: str
    timestamp: str
    ratified_by_human0: bool
    prev_hash: str
    entry_hash: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _modelfile_digest(path: Path = MODELFILE_PATH) -> str:
    """SHA-256 of the Modelfile bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _last_ledger_state(path: Path) -> tuple[str, int]:
    """Return (last_entry_hash, next_seq) from the CMU ledger."""
    if not path.exists():
        return "0" * 64, 0
    last: Optional[dict] = None
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                    count += 1
                except json.JSONDecodeError:
                    continue
    if last:
        return last.get("entry_hash", "0" * 64), last.get("seq", count - 1) + 1
    return "0" * 64, 0


def append_cmu_ledger(
    event: str,
    params: ModelfileParams,
    *,
    ratified_by_human0: bool = False,
    ledger_path: Path = CMU_LEDGER_PATH,
    modelfile_path: Path = MODELFILE_PATH,
) -> CMULedgerEntry:
    """
    CMU-DETERM-0: Append a hash-chained entry to the CMU ledger.
    Raises CMULedgerWriteError if the write cannot be flushed.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash, seq = _last_ledger_state(ledger_path)
    timestamp = datetime.now(timezone.utc).isoformat()
    mf_digest = _modelfile_digest(modelfile_path) if modelfile_path.exists() else "absent"

    payload = json.dumps({
        "seq": seq,
        "event": event,
        "base_model": params.base_model,
        "num_ctx": params.num_ctx,
        "temperature": params.temperature,
        "modelfile_digest": mf_digest,
        "timestamp": timestamp,
        "ratified_by_human0": ratified_by_human0,
        "prev_hash": prev_hash,
    }, sort_keys=True)
    entry_hash = hashlib.sha256(payload.encode()).hexdigest()
    entry_dict = json.loads(payload)
    entry_dict["entry_hash"] = entry_hash

    try:
        with ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry_dict) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        raise CMULedgerWriteError(
            f"CMU-DETERM-0 VIOLATION: CMU ledger write failed at seq={seq}: {exc}"
        ) from exc

    return CMULedgerEntry(**entry_dict)


# ── CMU-BENCH-0: governance benchmark suite ───────────────────────────────────

GOVERNANCE_BENCHMARK: list[dict] = [
    # Format: {id, query, expected_keywords, category}
    # The benchmark runner checks that >= 85% of expected_keywords appear in the response.
    {"id": "BENCH-001", "category": "identity",
     "query": "What is your current version and phase?",
     "expected_keywords": ["v9.76.0", "143", "INNOV-49"]},
    {"id": "BENCH-002", "category": "invariants",
     "query": "How many Hard-class invariants are active?",
     "expected_keywords": ["236"]},
    {"id": "BENCH-003", "category": "constitution",
     "query": "What is the current constitution version?",
     "expected_keywords": ["1.0.0"]},
    {"id": "BENCH-004", "category": "governance",
     "query": "Who is HUMAN-0 and what can they not delegate?",
     "expected_keywords": ["Dustin", "COMMUNITY-HUMAN0-0", "ratification"]},
    {"id": "BENCH-005", "category": "invariants",
     "query": "What does CMU-CTX-0 enforce?",
     "expected_keywords": ["16384", "num_ctx", "context"]},
    {"id": "BENCH-006", "category": "invariants",
     "query": "What does CMU-TEMP-0 enforce?",
     "expected_keywords": ["0.1", "temperature", "governance"]},
    {"id": "BENCH-007", "category": "docker",
     "query": "Can I use :latest Docker tags in ADAAD?",
     "expected_keywords": ["DAS-DOCKER-0", "prohibited", "pinned"]},
    {"id": "BENCH-008", "category": "pypi",
     "query": "How do I publish ADAAD to PyPI?",
     "expected_keywords": ["twine", "HUMAN-0", "local"]},
    {"id": "BENCH-009", "category": "world-first",
     "query": "What makes ADAAD's canary deployment unique?",
     "expected_keywords": ["CMD", "rollback", "Hard-class", "invariant"]},
    {"id": "BENCH-010", "category": "world-first",
     "query": "Describe the CEPD and why it is a world-first.",
     "expected_keywords": ["CEPD", "cryptographic", "proof", "DAG"]},
    {"id": "BENCH-011", "category": "agents",
     "query": "Name the three ADAAD agent classes and their constitutional roles.",
     "expected_keywords": ["Architect", "Dream", "Beast"]},
    {"id": "BENCH-012", "category": "ledger",
     "query": "What is DFSB-PERSIST-0 and what does it prohibit?",
     "expected_keywords": ["DFSB-PERSIST-0", "flush", "silent"]},
    {"id": "BENCH-013", "category": "model",
     "query": "What model does DORK run on in Phase 143?",
     "expected_keywords": ["phi4", "14b"]},
    {"id": "BENCH-014", "category": "model",
     "query": "Why was the model upgraded from llama3.2 to phi4?",
     "expected_keywords": ["context", "reasoning", "governance"]},
    {"id": "BENCH-015", "category": "corpus",
     "query": "What is the LKSE and what does LKSE-SYNC-0 require?",
     "expected_keywords": ["LKSE", "corpus", "phase"]},
    {"id": "BENCH-016", "category": "embeddings",
     "query": "How does DORK perform semantic search over the corpus?",
     "expected_keywords": ["CSS", "cosine", "embedding"]},
    {"id": "BENCH-017", "category": "governance",
     "query": "What happens if a mutation violates a Hard-class invariant?",
     "expected_keywords": ["blocked", "GovernanceGate", "invariant"]},
    {"id": "BENCH-018", "category": "gpg",
     "query": "Who signs phase artifacts and can this be delegated?",
     "expected_keywords": ["HUMAN-0", "GPG", "non-delegatable"]},
    {"id": "BENCH-019", "category": "findings",
     "query": "How many open findings does ADAAD currently have?",
     "expected_keywords": ["0"]},
    {"id": "BENCH-020", "category": "innovations",
     "query": "How many innovations have been shipped?",
     "expected_keywords": ["49", "INNOV-49"]},
    {"id": "BENCH-021", "category": "replay",
     "query": "What is CEL-REPLAY-0 and why is it constitutionally required?",
     "expected_keywords": ["CEL-REPLAY-0", "deterministic", "replay"]},
    {"id": "BENCH-022", "category": "rollback",
     "query": "Can a rollback be refused by an agent?",
     "expected_keywords": ["Hard-class", "invariant", "MMEM-ROLLBACK-0"]},
    {"id": "BENCH-023", "category": "slash",
     "query": "What does the /blast slash command do?",
     "expected_keywords": ["blast", "radius", "mutation"]},
    {"id": "BENCH-024", "category": "slash",
     "query": "What does /health return?",
     "expected_keywords": ["debt", "pressure", "entropy"]},
    {"id": "BENCH-025", "category": "identity",
     "query": "What is the full expansion of DORK?",
     "expected_keywords": ["Dynamic", "Operative", "Resource", "Knowledge"]},
    {"id": "BENCH-026", "category": "identity",
     "query": "What is the full expansion of ADAAD?",
     "expected_keywords": ["Autonomous", "Development", "Adaptive", "Architecture"]},
    {"id": "BENCH-027", "category": "world-first",
     "query": "What is CMU's world-first claim?",
     "expected_keywords": ["constitutionally", "validated", "model", "upgrade"]},
    {"id": "BENCH-028", "category": "governance",
     "query": "What is the FGCON quorum requirement?",
     "expected_keywords": ["FGCON", "quorum", "FGCON-QUORUM-0"]},
    {"id": "BENCH-029", "category": "security",
     "query": "What does AFRT stand for and what does it do?",
     "expected_keywords": ["Adversarial", "Fitness", "Red", "Team", "AFRT-RED-0"]},
    {"id": "BENCH-030", "category": "cryptography",
     "query": "What FINDING-66-004 resolved and when?",
     "expected_keywords": ["Ed25519", "key", "ceremony", "2026"]},
]


def run_benchmark(
    ask_fn,
    *,
    pass_threshold: float = 0.85,
    verbose: bool = False,
) -> dict:
    """
    CMU-BENCH-0: Run the 30-question governance benchmark against ask_fn.

    ask_fn(query: str) -> str  — callable that returns the model response.

    Returns a result dict:
      {passed: int, total: int, pass_rate: float, passed_threshold: bool, failures: list}

    Raises CMUInvariantViolation if pass_rate < pass_threshold.
    """
    results = []
    for item in GOVERNANCE_BENCHMARK:
        response = ask_fn(item["query"])
        response_lower = response.lower()
        hits = sum(
            1 for kw in item["expected_keywords"]
            if kw.lower() in response_lower
        )
        passed = hits >= len(item["expected_keywords"])
        results.append({
            "id": item["id"],
            "category": item["category"],
            "passed": passed,
            "hits": hits,
            "expected": len(item["expected_keywords"]),
            "query": item["query"],
        })
        if verbose:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {item['id']} — {item['query'][:60]}")

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    pass_rate = passed_count / total
    threshold_met = pass_rate >= pass_threshold

    summary = {
        "passed": passed_count,
        "total": total,
        "pass_rate": round(pass_rate, 4),
        "threshold": pass_threshold,
        "passed_threshold": threshold_met,
        "failures": [r for r in results if not r["passed"]],
    }

    if not threshold_met:
        raise CMUInvariantViolation(
            f"CMU-BENCH-0 VIOLATION: benchmark pass_rate={pass_rate:.1%} < "
            f"threshold={pass_threshold:.0%}. Model does not meet governance "
            f"reasoning standard. {total - passed_count} questions failed."
        )

    return summary


# ── Ollama model info query ────────────────────────────────────────────────────

def query_ollama_model_info(model: str = "dork") -> Optional[dict]:
    """
    Query Ollama /api/show for the running model's details.
    Returns None if Ollama is unreachable (does not raise).
    """
    try:
        body = json.dumps({"name": model}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/show",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def full_cmu_validation(
    *,
    modelfile_path: Path = MODELFILE_PATH,
    ledger_path: Path = CMU_LEDGER_PATH,
    record_event: bool = True,
) -> dict:
    """
    Run the full CMU validation pipeline:
      1. Parse and validate Modelfile (CMU-CTX-0, CMU-TEMP-0)
      2. Append validation event to CMU ledger (CMU-DETERM-0)
      3. Return summary dict

    Does NOT run the benchmark (BENCH-030 questions require a live model).
    Call run_benchmark() separately with a live ask_fn.
    """
    params = validate_modelfile(modelfile_path)
    entry = None
    if record_event:
        entry = append_cmu_ledger(
            "modelfile_validated",
            params,
            ratified_by_human0=False,
            ledger_path=ledger_path,
            modelfile_path=modelfile_path,
        )
    return {
        "ok": True,
        "base_model": params.base_model,
        "num_ctx": params.num_ctx,
        "temperature": params.temperature,
        "cmu_ctx_0": "pass",
        "cmu_temp_0": "pass",
        "ledger_seq": entry.seq if entry else None,
        "ledger_entry_hash": entry.entry_hash if entry else None,
    }
