# SPDX-License-Identifier: Apache-2.0
"""
AI Mutation Proposer — connects the Claude API to the ADAAD mutation pipeline.

Architecture:
- Three specialised agent personas (Architect, Dream, Beast) each produce a
  statistically distinct set of MutationCandidate proposals via Claude.
- All HTTP calls use pure urllib.request — zero third-party dependencies,
  Android/Pydroid3 safe.
- JSON schema is injected into every system prompt; markdown fence stripping
  handles Claude's occasional formatting non-compliance.
- propose_from_all_agents() is the primary entry point for the EvolutionLoop.

Design decisions:
- Model: claude-sonnet-4-20250514  (best instruction-following + JSON fidelity)
- max_tokens: 2048  (3-6 proposals × ~300 tokens + JSON overhead)
- temperature: default (1.0) for proposal diversity
- Error propagation: failures are normalised into structured AgentProposalBatch
  payloads; silent failure is forbidden (see failover contract below).

Failover governance:
- Policy contract: docs/governance/LLM_FAILOVER_CONTRACT.md
- per_call_timeout_s: 30  (floor — never reduce without constitutional amendment)
- max_retries_per_agent: 1  (total attempts = 2)
- global_timeout_budget_s: 90  (wall-clock across all 3 concurrent agents)
- Zero-proposal epoch: epoch SKIPPED, no mutation applied, evidence required.
- All failure outcomes captured in AgentProposalBatch.failures as structured
  payloads. Silent swallowing of LLM exceptions is a BLOCKING violation.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from runtime.autonomy.mutation_scaffold import MutationCandidate
from runtime.evolution.mutation_operator_framework import OperatorOutcome, OperatorSelectionProfile
from runtime.state.ledger_store import ScoringLedgerStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"
MAX_TOKENS     = 2048

VALID_AGENTS     = {"architect", "dream", "beast"}
VALID_MUT_TYPES  = {"structural", "behavioral", "performance", "coverage", "experimental"}
CANONICAL_AGENT_ORDER: Tuple[str, ...] = ("architect", "dream", "beast")
CONTEXT_HASH_V2_HEX_LEN: int = 16
CONTEXT_HASH_V1_HEX_LEN: int = 8

PROPOSAL_SCHEMA = """
Return ONLY a JSON array. No markdown, no preamble. Each element must have:
{
  "mutation_id"    : "<agent>-<slug>-<unix_ts>",
  "description"    : "<one sentence>",
  "expected_gain"  : <float 0.0-1.0>,
  "risk_score"     : <float 0.0-1.0>,
  "complexity"     : <float 0.0-1.0>,
  "coverage_delta" : <float 0.0-1.0>,
  "target_files"   : ["file.py"],
  "mutation_type"  : "structural|behavioral|performance|coverage|experimental"
}
Produce exactly 3-5 proposals.
"""

AGENT_SYSTEM_PROMPTS: Dict[str, str] = {
    "architect": (
        "You are the Architect agent in the ADAAD system. Your role is to propose "
        "structural mutations: module reorganisation, abstraction improvements, "
        "dependency refactoring, and interface contract tightening. "
        "You never propose implementation-level changes — only structural shapes. "
        "Expected gains are medium (0.3-0.6). Risk is low-medium (0.1-0.4). "
        "mutation_type must always be 'structural'.\n\n" + PROPOSAL_SCHEMA
    ),
    "dream": (
        "You are the Dream agent in the ADAAD system. Your role is to propose "
        "high-novelty, exploratory mutations. You favour breadth over safety. "
        "Cross-domain patterns, experimental approaches, and alternative "
        "architectures are your domain. Your proposals are high-gain (0.5-0.9), "
        "higher-risk (0.4-0.8). mutation_type should be 'experimental' or 'behavioral'.\n\n"
        + PROPOSAL_SCHEMA
    ),
    "beast": (
        "You are the Beast agent in the ADAAD system. Your role is to propose "
        "conservative, measurable, safe mutations: micro-optimisations, dead code "
        "removal, coverage additions, and performance improvements. "
        "You never propose speculative changes. "
        "Expected gain is low-medium (0.2-0.5). Risk is very low (0.05-0.2). "
        "mutation_type should be 'performance' or 'coverage'.\n\n" + PROPOSAL_SCHEMA
    ),
}


@dataclass(frozen=True)
class AgentProposalBatch:
    """Container returned by propose_from_all_agents for EvolutionLoop consumption."""

    proposals_by_agent: Dict[str, List[MutationCandidate]]
    failures_by_agent: Dict[str, Dict[str, Any]]


def _failure_payload(
    *,
    agent: str,
    code: str,
    timeout_seconds: int,
    attempts: int,
    detail: str,
) -> Dict[str, Any]:
    """Standardized failure payload for EvolutionLoop telemetry/fallback paths."""
    return {
        "agent": agent,
        "code": code,
        "timeout_seconds": timeout_seconds,
        "attempts": attempts,
        "detail": detail,
    }


def _build_selection_profile(context: "CodebaseContext", agent: str) -> OperatorSelectionProfile:
    preferred = ""
    if agent == "architect":
        preferred = "refactor"
    elif agent == "beast":
        preferred = "performance_rewrite"
    elif agent == "dream":
        preferred = "ast_transform"
    return OperatorSelectionProfile(
        explore_ratio=float(context.explore_ratio),
        recent_failures_count=len(context.recent_failures),
        preferred_operator_hint=preferred,
    )


def _load_operator_outcome_history() -> Dict[str, OperatorOutcome]:
    store = ScoringLedgerStore(path=Path("runtime/state/scoring_ledger.jsonl"), backend="json")
    summary = store.operator_outcome_history()
    history: Dict[str, OperatorOutcome] = {}
    for key, value in summary.items():
        history[key] = OperatorOutcome(
            successes=int(value.get("successes", 0)),
            failures=int(value.get("failures", 0)),
        )
    return history


# ---------------------------------------------------------------------------
# CodebaseContext
# ---------------------------------------------------------------------------


@dataclass
class CodebaseContext:
    """
    Snapshot of the codebase state passed to proposal agents.

    file_summaries: {relative_path: docstring_or_summary}
    recent_failures: list of failing test names from last CI run
    current_epoch_id: epoch identifier string
    explore_ratio: 0.0 = pure exploit, 1.0 = pure explore
    soulbound_annotation: optional replay context digest injected by
        ContextReplayInterface (Phase 9). When set, appended as a
        supplemental annotation block in the proposal user message.
        Content is a serialised dict; digest is SHA-256 of the ledger window.
    learning_context: optional cross-epoch learning signal injected by
        LearningSignalExtractor (Phase 52). When set, appended as an
        advisory block summarising top-performing agents, strategies, and
        fitness trends from the EpochMemoryStore window. Advisory only —
        agents may not follow it verbatim.
    """
    file_summaries:       Dict[str, str]
    recent_failures:      List[str]
    current_epoch_id:     str
    explore_ratio:        float = 0.5
    soulbound_annotation: Optional[str] = None
    learning_context:     Optional[str] = None  # Phase 52: cross-epoch learning signal

    def _canonical_context_payload(self) -> str:
        """Deterministic JSON payload used for context hash derivation."""
        return json.dumps(
            {
                "files": sorted(self.file_summaries.keys()),
                "failures": sorted(self.recent_failures),
                "epoch": self.current_epoch_id,
            },
            sort_keys=True,
        )

    def context_hash_legacy(self) -> str:
        """Legacy 8-hex MD5 context hash retained for compatibility reads/migrations."""
        payload = self._canonical_context_payload()
        return hashlib.md5(payload.encode()).hexdigest()[:CONTEXT_HASH_V1_HEX_LEN]

    def context_hash(self) -> str:
        """Stable 16-hex SHA-256-derived context hash for lineage tracing."""
        payload = self._canonical_context_payload()
        return hashlib.sha256(payload.encode()).hexdigest()[:CONTEXT_HASH_V2_HEX_LEN]

    def as_prompt_block(self) -> str:
        """Format context as a human-readable block for injection into prompts."""
        lines = [
            f"Epoch: {self.current_epoch_id}",
            f"Explore ratio: {self.explore_ratio:.2f}",
            "",
            "Files under consideration:",
        ]
        for path, summary in sorted(self.file_summaries.items()):
            lines.append(f"  {path}: {summary[:120]}")
        if self.recent_failures:
            lines.append("")
            lines.append("Recent test failures:")
            for f in self.recent_failures[:10]:
                lines.append(f"  - {f}")
        if self.soulbound_annotation:
            lines.append("")
            lines.append("--- Soulbound context (advisory — do not repeat verbatim) ---")
            lines.append(self.soulbound_annotation)
            lines.append("--- end soulbound context ---")
        if self.learning_context:
            lines.append("")
            lines.append(self.learning_context)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal: Claude API call
# ---------------------------------------------------------------------------


def _call_claude(
    system_prompt: str,
    user_message:  str,
    api_key:       str,
    timeout:       int = 30,
) -> str:
    """
    Single Claude API call. Returns raw response text.

    Raises:
    - urllib.error.HTTPError on non-2xx status.
    - urllib.error.URLError on network failure.
    """
    payload = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_message}],
    }).encode()

    req = urllib.request.Request(
        CLAUDE_API_URL,
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())

    return body["content"][0]["text"]


def _stable_id_slug(raw_value: str) -> str:
    """Return a deterministic, mutation-id-safe slug for rebuilt proposal IDs."""
    slug = "".join(
        ch.lower() if ch.isalnum() else "-"
        for ch in raw_value.strip()
    ).strip("-")
    return slug or "auto"


def _deterministic_mutation_id_suffix(
    *,
    agent: str,
    epoch_id: str,
    context_hash: str,
    parent_id: Optional[str],
    proposal_index: int,
    proposal: Dict[str, Any],
) -> str:
    """Derive a stable suffix for repaired AI proposal mutation IDs.

    Rationale: AI proposal parsing is replay-sensitive; fallback mutation IDs
    must not depend on wall-clock time or process-local entropy. The suffix is
    a SHA-256 digest over stable lineage inputs plus canonical proposal content.

    Expected invariants:
    - identical inputs produce identical fallback IDs across parse calls;
    - proposals in the same batch differ by index/content and therefore remain
      uniquely addressable;
    - public parser/proposer function signatures remain unchanged.
    """
    payload = {
        "agent": agent,
        "epoch_id": epoch_id,
        "context_hash": context_hash,
        "parent_id": parent_id or "",
        "proposal_index": proposal_index,
        "proposal": proposal,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Internal: Parse proposals
# ---------------------------------------------------------------------------


def _parse_proposals(
    raw_text:    str,
    agent:       str,
    context:     CodebaseContext,
    parent_id:   Optional[str] = None,
    epoch_id:    str            = "",
) -> List[MutationCandidate]:
    """
    Parse Claude's JSON response into MutationCandidate objects.

    Robustness:
    - Strips markdown code fences (```json ... ```) if present.
    - Propagates JSONDecodeError to caller — never silently swallows.
    - Validates mutation_type against VALID_MUT_TYPES; defaults to agent
      persona's canonical type on unknown values.
    """
    text = raw_text.strip()
    # Strip markdown fences defensively
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("```")
        ).strip()

    proposals_raw = json.loads(text)  # JSONDecodeError propagates

    context_hash = context.context_hash()
    stable_epoch_id = epoch_id or context.current_epoch_id
    candidates: List[MutationCandidate] = []

    for proposal_index, p in enumerate(proposals_raw):
        mut_type = p.get("mutation_type", "structural")
        if mut_type not in VALID_MUT_TYPES:
            mut_type = "structural"

        # Ensure unique, agent-scoped mutation_id. Invalid or missing IDs are
        # rebuilt from stable lineage inputs only: agent, epoch, context hash,
        # parent, proposal index, and canonical proposal content. This preserves
        # replay determinism while keeping IDs distinct within a batch.
        raw_mutation_id = p.get("mutation_id")
        raw_id = str(raw_mutation_id) if raw_mutation_id is not None else ""
        if not raw_id.startswith(agent):
            suffix = _deterministic_mutation_id_suffix(
                agent=agent,
                epoch_id=stable_epoch_id,
                context_hash=context_hash,
                parent_id=parent_id,
                proposal_index=proposal_index,
                proposal=p,
            )
            slug_source = raw_id or "auto"
            raw_id = f"{agent}-{_stable_id_slug(slug_source)}-{suffix}"

        candidates.append(MutationCandidate(
            mutation_id=raw_id,
            expected_gain=float(p.get("expected_gain", 0.3)),
            risk_score=float(p.get("risk_score", 0.3)),
            complexity=float(p.get("complexity", 0.3)),
            coverage_delta=float(p.get("coverage_delta", 0.1)),
            parent_id=parent_id,
            generation=0,
            agent_origin=agent,
            epoch_id=epoch_id,
            source_context_hash=context_hash,
            python_content=p.get("python_content") or None,
        ))

    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def propose_mutations(
    agent:     str,
    context:   CodebaseContext,
    api_key:   str,
    parent_id: Optional[str] = None,
    timeout:   int           = 30,
) -> List[MutationCandidate]:
    """
    Call Claude as the specified agent persona and return mutation proposals.

    Args:
        agent:     One of 'architect', 'dream', 'beast'.
        context:   Current codebase snapshot.
        api_key:   Anthropic API key.
        parent_id: Optional parent mutation_id for lineage chaining.
        timeout:   HTTP timeout in seconds.

    Returns:
        List of MutationCandidate objects (>= 1).

    Raises:
        ValueError: Unknown agent name.
        urllib.error.HTTPError: API call failed.
        json.JSONDecodeError: Claude returned non-JSON output.
    """
    if agent not in VALID_AGENTS:
        raise ValueError(f"Unknown agent '{agent}'. Must be one of {VALID_AGENTS}.")

    system_prompt = AGENT_SYSTEM_PROMPTS[agent]
    user_message = (
        f"Analyse this codebase context and propose {agent}-persona mutations:\n\n"
        f"{context.as_prompt_block()}"
    )

    raw = _call_claude(system_prompt, user_message, api_key, timeout=timeout)
    return _parse_proposals(
        raw,
        agent=agent,
        context=context,
        parent_id=parent_id,
        epoch_id=context.current_epoch_id,
    )


def propose_from_all_agents(
    context: CodebaseContext,
    api_key: str,
    timeout: int = 30,
    *,
    max_workers: int = 3,
    max_in_flight: int = 3,
    retries: int = 1,
    global_timeout_budget: Optional[float] = None,
) -> AgentProposalBatch:
    """
    Call all three agents and return proposals keyed by agent name.

    Returns deterministic ordering with per-agent isolation and structured
    failures for EvolutionLoop fallback logic.
    """
    proposals_by_agent: Dict[str, List[MutationCandidate]] = {
        agent: [] for agent in CANONICAL_AGENT_ORDER
    }
    failures_by_agent: Dict[str, Dict[str, Any]] = {}
    outcome_history = _load_operator_outcome_history()

    def _propose_with_retry(agent: str) -> Tuple[str, List[MutationCandidate], Optional[Dict[str, Any]]]:
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                proposals = propose_mutations(agent, context, api_key, timeout=timeout)
                return agent, proposals, None
            except TimeoutError as exc:
                if attempts > retries:
                    return agent, [], _failure_payload(
                        agent=agent,
                        code="agent_timeout",
                        timeout_seconds=timeout,
                        attempts=attempts,
                        detail=str(exc) or "timeout",
                    )
            except Exception as exc:  # noqa: BLE001 - intentionally normalized into payload
                if attempts > retries:
                    return agent, [], _failure_payload(
                        agent=agent,
                        code="agent_error",
                        timeout_seconds=timeout,
                        attempts=attempts,
                        detail=f"{type(exc).__name__}: {exc}",
                    )
        return agent, [], _failure_payload(
            agent=agent,
            code="agent_error",
            timeout_seconds=timeout,
            attempts=attempts,
            detail="retry_exhausted",
        )

    effective_workers = max(1, min(max_workers, max_in_flight, len(CANONICAL_AGENT_ORDER)))
    budget = global_timeout_budget if global_timeout_budget is not None else float(timeout * len(CANONICAL_AGENT_ORDER))
    deadline = time.monotonic() + budget

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        future_to_agent: Dict[Future[Tuple[str, List[MutationCandidate], Optional[Dict[str, Any]]]], str] = {
            executor.submit(_propose_with_retry, agent): agent
            for agent in CANONICAL_AGENT_ORDER
        }

        pending = set(future_to_agent.keys())
        while pending:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0.0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            for fut in done:
                agent, proposals, failure = fut.result()
                if proposals:
                    from runtime.autonomy.mutation_scaffold import apply_operator_registry

                    proposals = apply_operator_registry(
                        proposals,
                        outcome_history=outcome_history,
                        profile=_build_selection_profile(context, agent),
                    )
                proposals_by_agent[agent] = proposals
                if failure is not None:
                    failures_by_agent[agent] = failure

        for fut in pending:
            agent = future_to_agent[fut]
            fut.cancel()
            failures_by_agent[agent] = _failure_payload(
                agent=agent,
                code="global_timeout",
                timeout_seconds=timeout,
                attempts=0,
                detail="global timeout budget exhausted",
            )

    ordered = {agent: proposals_by_agent[agent] for agent in CANONICAL_AGENT_ORDER}
    return AgentProposalBatch(proposals_by_agent=ordered, failures_by_agent=failures_by_agent)
