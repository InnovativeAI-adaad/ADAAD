/* dork_knowledge_base.js — ADAAD DORK Knowledge Base v2.0
 * Expanded corpus: 50+ entries covering all ADAAD subsystems.
 * Each entry: { key, answer, tags, confidence }
 * Lookup strategy: exact → partial → token-overlap → weak
 */
(function initDorkKnowledgeBase(global) {
  'use strict';

  const KB = [
    // ── Core Identity ──────────────────────────────────────────────────
    { key: 'what is adaad', answer: 'ADAAD (Autonomous Development & Adaptation Architecture) is a governed autonomous software-evolution engine. AI agents propose, score, test, and evolve code within constitutionally enforceable constraints. Every change is ledgered and every promotion requires a GPG-signed human attestation from HUMAN-0.', tags: ['identity','overview','core'], confidence: 0.99 },
    { key: 'what is dork', answer: 'DORK (Dynamic Operative Resource Knowledge) is the AI assistant embedded in ADAAD\'s developer console (Whale.Dic). DORK routes operator queries to capability cards, synthesises state-bus context, and surfaces governance-safe next actions — deterministically and with full auditability.', tags: ['dork','identity','assistant'], confidence: 0.99 },
    { key: 'problem', answer: 'ADAAD solves slow, expensive, and risky manual software maintenance by routing AI-proposed improvements through a strict, auditable constitutional approval process before anything ever changes in production.', tags: ['problem','value','motivation'], confidence: 0.98 },
    { key: 'who built it', answer: 'ADAAD is built by Innovative AI LLC, led by Dustin L. Reid (Governor, HUMAN-0). It is open-source, free, and hosted at InnovativeAI-adaad/adaad on GitHub.', tags: ['identity','team','founder'], confidence: 0.99 },
    { key: 'who is it for', answer: 'ADAAD targets software teams needing auditability, developers building AI-assisted tooling, compliance-sensitive organisations, governed-autonomy researchers, and Android users who want the free dashboard app.', tags: ['audience','users','value'], confidence: 0.97 },
    // ── Architecture ───────────────────────────────────────────────────
    { key: 'how it works', answer: 'ADAAD operates in five stages: (1) The triad agents (Architect, Dream, Beast) propose code mutations. (2) Oracle scores proposals via multi-signal fitness. (3) GovernanceGate checks 91+ Hard-class invariants. (4) HUMAN-0 performs a GPG-signed attestation. (5) The ledger records the immutable promotion event and the system adapts.', tags: ['architecture','flow','process'], confidence: 0.99 },
    { key: 'agents', answer: 'Three AI agents compete: Architect (methodical, structure-first), Dream (creative, hypothesis-heavy), and Beast (aggressive, throughput-optimised). They each generate mutation proposals independently scored before entering the governance pipeline.', tags: ['agents','triad','architect','dream','beast'], confidence: 0.99 },
    { key: 'architect agent', answer: 'Architect is the methodical triad agent. It focuses on structural correctness, dependency hygiene, and long-horizon consistency — the most conservative proposer and the first to flag invariant violations.', tags: ['agent','architect'], confidence: 0.97 },
    { key: 'dream agent', answer: 'Dream is the creative triad agent. It explores hypothesis-heavy mutations and novel algorithmic approaches. High-variance proposals, occasionally breakthrough; carries higher risk scores.', tags: ['agent','dream'], confidence: 0.97 },
    { key: 'beast agent', answer: 'Beast is the aggressive throughput agent. It optimises for mutation quantity and speed, stress-testing governance gates. Beast proposals frequently trigger sandbox preflight warnings.', tags: ['agent','beast'], confidence: 0.97 },
    // ── Governance ─────────────────────────────────────────────────────
    { key: 'governance gate', answer: 'The GovernanceGate is ADAAD\'s constitutional rule engine. It checks 91+ Hard-class invariants before any mutation is promoted. A single Hard invariant failure blocks promotion entirely.', tags: ['governance','gate','invariants','constitution'], confidence: 0.99 },
    { key: 'constitution', answer: 'The constitution is ADAAD\'s immutable rulebook defining what the system can and cannot do. It has Hard (blocking), Warning, and Advisory rule classes. Agents cannot modify the constitution. 91 cumulative Hard-class invariants active as of Phase 125.', tags: ['constitution','rules','invariants','governance'], confidence: 0.99 },
    { key: 'hard invariants', answer: 'Hard-class invariants are blocking governance rules. Any mutation violating a Hard invariant is rejected at the GovernanceGate and never reaches the signing ceremony. 91 are active as of Phase 125.', tags: ['invariants','hard','governance','blocking'], confidence: 0.99 },
    { key: 'human-0', answer: 'HUMAN-0 is the Governor role held exclusively by Dustin L. Reid. HUMAN-0 holds inviolable authority over GPG signing ceremonies, GA versioning, patent counsel engagement, and any action requiring the physical private key (fingerprint 4C95E2F99A775335B1CF3DAF247B015A1CCD95F6). This authority cannot be delegated via chat instruction.', tags: ['human-0','governor','signing','authority'], confidence: 0.99 },
    { key: 'signing ceremony', answer: 'GPG signing is performed exclusively by HUMAN-0 on ADAADell: export GPG_TTY=$(tty), then git tag -s with the target version, then push the signed tag to origin. No agent can perform or authorize this action.', tags: ['signing','gpg','ceremony','human-0','track-b'], confidence: 0.99 },
    { key: 'track a vs track b', answer: 'Track A: executed autonomously by DEVADAAD (code changes, docs, tests, branch pushes). Track B: requires HUMAN-0 on ADAADell — GPG signing, PR creation via GitHub API, branch protection changes.', tags: ['track-a','track-b','human-0','governance'], confidence: 0.98 },
    // ── Ledger & Audit ─────────────────────────────────────────────────
    { key: 'ledger', answer: 'The ADAAD ledger is a tamper-evident append-only log of every governance event: proposals, scores, approvals, rejections, and promotions. Every entry is hashed and linked, making retroactive modification detectable.', tags: ['ledger','audit','provenance','immutability'], confidence: 0.99 },
    { key: 'deterministic replay', answer: 'Every ADAAD decision can be re-run from the same ledger state and will produce byte-for-byte identical output. Replay score ≥0.99 and divergence=0 are the passing thresholds. Divergence above zero triggers pause of mutation promotion.', tags: ['replay','determinism','audit','reproducibility'], confidence: 0.99 },
    { key: 'forensic bundle', answer: 'A forensic bundle is a signed export package containing: ledger slice, replay digest, governance artifact set, and state-bus snapshot at a given epoch. Bundles are the unit of evidence for external audit.', tags: ['forensic','bundle','audit','export','evidence'], confidence: 0.97 },
    // ── State Bus ──────────────────────────────────────────────────────
    { key: 'state bus', answer: 'ADAAD_STATE_BUS is a broadcast key-value store shared across all Whale.Dic panels via BroadcastChannel and localStorage. It carries live snapshots of governance, replay, mutation, readiness, oracle, and agent state. DORK reads from the state bus to contextualise capability cards.', tags: ['state-bus','broadcast','context','runtime'], confidence: 0.98 },
    // ── Oracle ─────────────────────────────────────────────────────────
    { key: 'oracle', answer: 'The Oracle is ADAAD\'s projection and forecasting subsystem. It answers structured governance queries by synthesising ledger history, replay scores, and fitness signals. Oracle projections are typed (replay, readiness, fitness, governance) and stored in the state bus for DORK to interpret.', tags: ['oracle','projection','forecast','query'], confidence: 0.98 },
    { key: 'oracle dork alignment', answer: 'Oracle×Dork Alignment (Phase 95) established the semantic bridge between Oracle projections and DORK capability routing. Oracle query types now map directly to DORK capability IDs, enabling one-click drill-down from projection to actionable card.', tags: ['oracle','dork','alignment','bridge'], confidence: 0.96 },
    // ── Mutations ──────────────────────────────────────────────────────
    { key: 'mutations', answer: 'A mutation is an AI-proposed code or configuration change. Pipeline stages: proposal → scoring → GovernanceGate → sandbox preflight → GPG signing → ledger promotion. Each mutation carries a hash, epoch ID, proposing agent, and fitness score.', tags: ['mutations','pipeline','proposal','promotion'], confidence: 0.99 },
    { key: 'sandbox preflight', answer: 'Sandbox preflight runs the proposed mutation in an isolated environment before governance signing. It checks test pass rate, resource bounds, and determinism constraints. A failed preflight blocks promotion even if the GovernanceGate passes.', tags: ['sandbox','preflight','isolation','testing'], confidence: 0.98 },
    // ── Fitness ────────────────────────────────────────────────────────
    { key: 'fitness', answer: 'Fitness is the multi-signal score assigned to a mutation proposal by the Oracle. Signals: code quality, test coverage delta, replay score impact, readiness regression risk, and governance gate pass probability.', tags: ['fitness','scoring','oracle','signals'], confidence: 0.98 },
    { key: 'market fitness', answer: 'Market-Conditioned Fitness (INNOV-22, Phase 107) extends the standard fitness signal with external-demand context: feature demand signals, comparative adoption curves, and operator-weighted priority adjustments. Implemented in market_fitness.py.', tags: ['market','fitness','innov-22','innovation'], confidence: 0.96 },
    // ── Versioning & Release ───────────────────────────────────────────
    { key: 'versioning', answer: 'Four-surface version alignment: VERSION file, pyproject.toml, .adaad_agent_state.json, and governance/report_version.json must all carry the same semver string after every phase promotion.', tags: ['versioning','semver','alignment','release'], confidence: 0.99 },
    { key: 'current version', answer: 'ADAAD is currently at v9.60.0, Phase 127. Check .adaad_agent_state.json or the VERSION file for the authoritative current version at any time.', tags: ['version','current','phase'], confidence: 0.95 },
    { key: 'release readiness', answer: 'Release readiness is a 0–1 score derived from: active blockers, test pass rate, replay score, governance gate status, and documentation completeness. Score ≥0.9 with zero Hard blockers is the GA gate threshold.', tags: ['release','readiness','score','gate'], confidence: 0.98 },
    { key: 'ga release', answer: 'v1.1-GA is gated on FINDING-66-003 (patent filing). Patent counsel engagement is a pending HUMAN-0 action and a Hard gate block until resolved.', tags: ['ga','release','patent','finding-66-003','blocker'], confidence: 0.97 },
    // ── Phases & Roadmap ───────────────────────────────────────────────
    { key: 'phase execution', answer: 'Each phase: create feature branch → implement module → 30 acceptance tests → wire REST endpoint → build Aponi UI panel → four governance artifacts → bump four version surfaces → update CHANGELOG and ROADMAP → no-ff merge → GPG tag → push.', tags: ['phase','execution','sequence','workflow'], confidence: 0.99 },
    { key: 'governance artifacts', answer: 'Four standard artifacts per phase in artifacts/governance/phaseNN/: phase_sign_off.json, track_a_sign_off.json, replay_digest.txt, tier_summary.json.', tags: ['artifacts','governance','phase','evidence'], confidence: 0.99 },
    { key: 'phase 95 offset', answer: 'Phase 95 (Oracle×Dork Alignment) was non-INNOV and shifted all subsequent INNOV assignments one phase forward in the manifest. Correction is reflected in PHASE_94_114_EXECUTION_MANIFEST.md.', tags: ['phase-95','offset','manifest','innov'], confidence: 0.98 },
    // ── Infra & Tools ──────────────────────────────────────────────────
    { key: 'adaadell', answer: 'ADAADell is HUMAN-0\'s local Ubuntu machine (username: dust). All Track B actions — GPG signing, GitHub API PR creation, branch protection — must be executed directly on ADAADell.', tags: ['adaadell','machine','local','track-b'], confidence: 0.99 },
    { key: 'devadaad', answer: 'DEVADAAD is the AI agent identity used by Claude for Track A work. Git identity: user.email = devadaad@innovativeai.dev, user.name = DEVADAAD.', tags: ['devadaad','agent','identity','git'], confidence: 0.99 },
    { key: 'mcp server', answer: 'The ADAAD MCP proposal-writer server runs on port 8091 with JWT auth. Startup: cd ~/adaad → source .venv/bin/activate → export ADAAD_MCP_JWT_SECRET=devlocal2026 → python runtime/mcp/server.py.', tags: ['mcp','server','port','startup','jwt'], confidence: 0.97 },
    { key: 'autosync', answer: 'Automation pipelines run daily at 06:00 UTC (state sync) and 06:30 UTC (docs/assets sync), plus on every push to main touching canonical state paths. The [doc-sync] commit guard prevents loops but can cause merge conflicts if it writes between a merge and a subsequent push.', tags: ['autosync','pipeline','conflict','cron'], confidence: 0.98 },
    { key: 'github api limitation', answer: 'POST calls to the GitHub API (PR creation, branch protection) are blocked from the DEVADAAD container. Only GET requests succeed. PR creation and branch protection must be executed from ADAADell using curl or gh CLI.', tags: ['github','api','limitation','track-b'], confidence: 0.99 },
    // ── Android / UI ───────────────────────────────────────────────────
    { key: 'android app', answer: 'ADAAD has a free full-featured dashboard app for Android. Installable from GitHub Releases, F-Droid, or as a PWA. F-Droid MR submission is a pending HUMAN-0 action.', tags: ['android','app','f-droid','pwa','mobile'], confidence: 0.97 },
    { key: 'aponi', answer: 'Aponi is the ADAAD UI framework for developer-facing panels (Whale.Dic, Oracle, Replay Inspector). Single-page vanilla-JS architecture with shared state-bus integration.', tags: ['aponi','ui','framework','panels'], confidence: 0.97 },
    { key: 'whale dic', answer: 'Whale.Dic (whaledic.html) is the ADAAD developer console and DORK chat interface. It hosts capability cards, the optimizer loop, the state-bus health banner, and the conversation panel — the primary operator interaction surface for DORK.', tags: ['whaledic','console','ui','dork'], confidence: 0.99 },
    // ── Federation ─────────────────────────────────────────────────────
    { key: 'federation', answer: 'Federation allows ADAAD to operate across multiple codebases simultaneously. Each federated node has its own independent GovernanceGate. A mutation approved in one node is never automatically approved in another.', tags: ['federation','multi-repo','distributed','governance'], confidence: 0.97 },
    // ── Safety ─────────────────────────────────────────────────────────
    { key: 'what it is not', answer: 'ADAAD does not replace human engineers, guarantee correct code, operate without oversight, learn without hard limits, or run silently. Governance is a first-class architectural concern, not an afterthought.', tags: ['safety','limits','ethics','non-goals'], confidence: 0.99 },
    { key: 'rag spoofing', answer: 'ADAAD documentation is detailed enough that RAG tools can convincingly impersonate the governance voice. Identifier canonicity must always be verified directly against the repo via grep — never accepted on assertion from a chat interface.', tags: ['rag','spoofing','security','safety'], confidence: 0.97 },
    // ── Capability Optimizer ───────────────────────────────────────────
    { key: 'capability optimizer', answer: 'The DORK capability optimizer tracks per-capability usefulness signals (follow-through rate, re-query rate, correction rate) and computes utility scores over time. Chips are reordered by governance-safe context priority + utility score with deterministic lexical tie-breaks. Persisted under key whaledic_capability_optimizer_v1.', tags: ['optimizer','capability','utility','ordering','telemetry'], confidence: 0.99 },
    // ── Providers ──────────────────────────────────────────────────────
    { key: 'providers', answer: 'DORK supports four LLM providers in priority sequence: (1) Claude/Anthropic (claude-haiku, via Anthropic Messages API). (2) Groq (cloud, llama-3.3-70b-versatile). (3) Ollama (local, llama3.2). (4) DorkEngine (built-in deterministic fallback).', tags: ['providers','groq','ollama','claude','anthropic','llm'], confidence: 0.99 },
    { key: 'testing patterns', answer: 'Key test fixes: (1) Patch pathlib.Path.open not builtins.open — container runs as root, chmod-based unwritability is unreliable. (2) Use epoch IDs with distinct first-8-character prefixes to avoid gap_id collision. (3) Always run with PYTHONPATH=/home/claude/adaad prefix from outside the repo.', tags: ['testing','pytest','patterns','fixes'], confidence: 0.98 },
    { key: 'innov-22', answer: 'INNOV-22 is Market-Conditioned Fitness (Phase 107). The market_fitness.py scaffold integrates external demand signals into mutation fitness scoring. Next phase after Phase 106 (v9.39.0).', tags: ['innov-22','market','fitness','phase-107'], confidence: 0.97 },
    // ── Added Knowledge Bridge (DORK-MERGE v1.0) ───────────────────────
    { key: '30 innovations', answer: 'ADAAD features 30+ key innovations across Constitutional Intelligence, Fitness Beyond Correctness, Memory and Identity, and Multi-Agent Architecture. See ADAAD_30_INNOVATIONS.md for the full index.', tags: ['innovations','roadmap','features'], confidence: 0.99 },
    { key: 'merge gates', answer: 'DEVADAAD merges are protected by a 5-tier gate stack: Tier 0 (Baseline), Tier 1 (Full Test Suite), Tier 2 (Escalated Replay), Tier 3 (PR Completeness), and Tier M (Merge-specific Working Code Assertion).', tags: ['merge','gates','devadaad','security'], confidence: 0.99 },
    { key: 'plans', answer: 'ADAAD offers three plan tiers: Free (limited seats/approvals), Pro (expanded limits, full mutation epochs), and Enterprise (unlimited scale/approvals).', tags: ['pricing','plans','enterprise'], confidence: 0.98 },
    { key: 'current phase', answer: 'ADAAD is currently in Phase 127, executing Break-It Challenge Infrastructure (v9.60.0).', tags: ['phase','current','status'], confidence: 0.99 },
    { key: 'next phase', answer: 'The next planned milestone is Phase 128, focusing on mobile runtime graduation.', tags: ['phase','roadmap','future'], confidence: 0.95 },
  ];

  function tokenise(text) {
    return String(text || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(Boolean);
  }

  function overlap(setA, setB) {
    let count = 0;
    setA.forEach((t) => { if (setB.has(t)) count++; });
    return count;
  }

  function lookup(query) {
    const q = String(query || '').toLowerCase().trim();
    if (!q) return null;
    const exact = KB.find((e) => e.key === q);
    if (exact) return { ...exact, match: 'exact' };
    const partial = KB.find((e) => e.key.includes(q) || q.includes(e.key));
    if (partial) return { ...partial, match: 'partial' };
    const qTokens = new Set(tokenise(q));
    let best = null, bestScore = 0;
    for (const entry of KB) {
      const entryTokens = new Set([...tokenise(entry.key), ...(entry.tags || [])]);
      const score = overlap(qTokens, entryTokens);
      if (score > bestScore) { bestScore = score; best = entry; }
    }
    if (bestScore >= 2) return { ...best, match: 'token', matchScore: bestScore };
    if (bestScore === 1) return { ...best, match: 'weak', matchScore: bestScore };
    return null;
  }

  function listAll() { return KB.map((e) => ({ key: e.key, tags: e.tags, confidence: e.confidence })); }
  function listByTag(tag) { return KB.filter((e) => (e.tags || []).includes(tag)); }

  // ── Phase 132 · INNOV-41 entries ────────────────────────────────────────────
  KB.push(
    {
      key: 'what is dork living fleet',
      answer: 'The DORK Living Fleet (INNOV-41, Phase 132) is a governed multi-engine orchestrator that routes DORK queries through a living fleet of LLM provider backends, slash-command resolvers, and conversation ledger engines — all enforced under six Hard constitutional invariants (DORK-FLEET-0, DORK-CMD-0, DORK-STATE-0, DORK-PROV-0, DORK-CTX-0, DORK-OUTPUT-0). It is a world-first: a constitutional fail-closed provider fleet with hash-chained conversation ledger and Jaccard-taxonomy intent routing under HUMAN-0 governance.',
      tags: ['fleet', 'innov-41', 'phase-132', 'dork', 'innovation'],
      confidence: 0.99,
    },
    {
      key: 'what is dork-fleet-0',
      answer: 'DORK-FLEET-0 is a Hard constitutional invariant introduced in Phase 132. It states: DORKLivingFleet MUST NOT promote any mutation without a successful DorkCommandResolver pre-validation pass. Fleet health status MUST be queryable at all times — a fleet with no healthy providers is constitutionally BLOCKED and raises FleetBlockedError.',
      tags: ['invariant', 'fleet', 'constitutional', 'hard', 'phase-132'],
      confidence: 0.99,
    },
    {
      key: 'what are dork slash commands',
      answer: 'DORK slash commands are /dork:-prefixed operator shortcuts (e.g. /dork:gate, /dork:fleet, /dork:brief) validated by the DorkCommandResolver against the canonical slash_commands.json manifest (DORK-CMD-0). Phase 132 ships 15 commands covering gate, mutation, replay, ledger, agents, phase, sandbox, signing, fleet, rank, delta, oracle, market, and help. Unknown commands are rejected — never silently forwarded.',
      tags: ['slash', 'commands', 'dork', 'phase-132', 'cmd-resolver'],
      confidence: 0.98,
    },
    {
      key: 'what is context keyword taxonomy',
      answer: 'The CONTEXT_KEYWORD_TAXONOMY (dorkllm/context.py, DORK-CTX-0) is the canonical 8-category keyword registry used to classify all DORK queries via Jaccard similarity scoring. Categories: governance, mutation, replay, ledger, agent, fleet, release, sandbox. classify_query() returns the best-matching category and confidence score. Ad-hoc keyword routing outside this taxonomy is constitutionally prohibited.',
      tags: ['taxonomy', 'jaccard', 'context', 'dork-ctx-0', 'phase-132'],
      confidence: 0.98,
    },
    {
      key: 'what is conversation ledger',
      answer: 'The ConversationLedger (dorkllm/state.py, DORK-STATE-0) is an append-only, SHA-256 hash-chained record of every DORK conversation turn (user + assistant). Each entry seals role, content digest, timestamp, and prev_hash. Mutating a prior entry raises ConversationLedgerViolation. The full chain is verifiable end-to-end via verify().',
      tags: ['ledger', 'conversation', 'state', 'dork-state-0', 'phase-132'],
      confidence: 0.99,
    }
  );

  global.DORK_KB = { lookup, listAll, listByTag, _entries: KB };
  // backward-compat shim for code reading DORK_KNOWLEDGE_BASE
  global.DORK_KNOWLEDGE_BASE = KB.reduce((acc, e) => { acc[e.key] = e.answer; return acc; }, {});
})(window);
