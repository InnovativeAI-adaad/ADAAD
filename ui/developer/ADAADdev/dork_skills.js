(function initDorkSkills(global) {
  'use strict';

  const SCHEMA_VERSION = 'dork_skill_router_v1';
  const LOW_CONFIDENCE_THRESHOLD = 0.67;
  const ROUTER_OUTPUT_KEYS = Object.freeze([
    'schema',
    'intent',
    'command',
    'confidence',
    'markdown',
    'needs_clarification',
    'clarifying_question',
    'failure_reason',
  ]);

  function toFinite(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, toFinite(value, 0)));
  }

  function pickRuntimeSnapshot(stateBus) {
    const src = stateBus && typeof stateBus === 'object' ? stateBus : {};
    if (src.S && src.S.gov && src.S.gov.runtime) return src.S.gov.runtime;
    if (src.gov && src.gov.runtime) return src.gov.runtime;
    return src;
  }

  function stableList(values) {
    if (!Array.isArray(values)) return [];
    return values.map((v) => String(v)).filter(Boolean);
  }

  function parseIntent(rawText) {
    const text = String(rawText || '').trim();
    const lower = text.toLowerCase();
    if (!text) return { intent: 'unknown', command: '', confidence: 0 };

    const slashMatch = lower.match(/^\/(gate|replay|blockers|phase|evidence|health)\b/);
    if (slashMatch) {
      return {
        intent: slashMatch[1],
        command: '/' + slashMatch[1],
        confidence: 0.99,
      };
    }

    const INTENT_HINTS = [
      { intent: 'gate', terms: ['gate', 'governance', 'tier', 'lock'] },
      { intent: 'replay', terms: ['replay', 'divergence', 'determinism'] },
      { intent: 'blockers', terms: ['blocker', 'blocked', 'readiness'] },
      { intent: 'phase', terms: ['phase', 'milestone', 'version'] },
      { intent: 'evidence', terms: ['evidence', 'claims', 'matrix', 'attestation'] },
      { intent: 'health', terms: ['health', 'status', 'triad', 'agent'] },
    ];

    let top = { intent: 'unknown', score: 0 };
    for (const hint of INTENT_HINTS) {
      const score = hint.terms.reduce((acc, term) => acc + (lower.includes(term) ? 1 : 0), 0) / hint.terms.length;
      if (score > top.score) top = { intent: hint.intent, score };
    }

    if (top.score === 0) return { intent: 'unknown', command: '', confidence: 0 };
    return {
      intent: top.intent,
      command: '/' + top.intent,
      confidence: Number((0.4 + top.score * 0.5).toFixed(2)),
    };
  }

  function fmtGate(runtime) {
    const locked = Boolean(runtime.gov && runtime.gov.locked);
    const tier = String((runtime.gov && runtime.gov.tier) || 'unknown');
    const constitution = String((runtime.gov && runtime.gov.constitution_version) || 'unknown');
    return [
      '### /gate',
      '',
      `- status: **${locked ? 'LOCKED' : 'PASS'}**`,
      `- tier: **${tier}**`,
      `- constitution: **${constitution}**`,
    ].join('\n');
  }

  function fmtReplay(runtime) {
    const score = clamp01(runtime.rep && runtime.rep.score);
    const divergence = toFinite(runtime.rep && runtime.rep.divergence, 0);
    const mode = String((runtime.rep && runtime.rep.mode) || 'unknown');
    return [
      '### /replay',
      '',
      `- replay_score: **${score.toFixed(3)}**`,
      `- divergence: **${divergence}**`,
      `- mode: **${mode}**`,
    ].join('\n');
  }

  function fmtBlockers(runtime) {
    const blockers = stableList(runtime.ready && runtime.ready.blockers);
    const score = clamp01(runtime.ready && runtime.ready.readiness_score);
    return [
      '### /blockers',
      '',
      `- readiness_score: **${Math.round(score * 100)}%**`,
      `- blocker_count: **${blockers.length}**`,
      blockers.length ? blockers.map((b) => `  - ${b}`).join('\n') : '  - none',
    ].join('\n');
  }

  function fmtPhase(runtime) {
    const phase = String(runtime.phase || (runtime.epoch && runtime.epoch.phase) || 'unknown');
    const epoch = String((runtime.epoch && runtime.epoch.epoch) || 'unknown');
    const version = String(runtime.version || 'unknown');
    return [
      '### /phase',
      '',
      `- phase: **${phase}**`,
      `- epoch: **${epoch}**`,
      `- version: **${version}**`,
    ].join('\n');
  }

  function fmtEvidence(runtime) {
    const matrixState = String((runtime.evidence && runtime.evidence.matrix_status) || 'unknown');
    const rowsPending = toFinite(runtime.evidence && runtime.evidence.pending_rows, 0);
    const attestations = toFinite(runtime.evidence && runtime.evidence.attestations, 0);
    return [
      '### /evidence',
      '',
      `- matrix_status: **${matrixState}**`,
      `- pending_rows: **${rowsPending}**`,
      `- attestations: **${attestations}**`,
    ].join('\n');
  }

  function fmtHealth(runtime) {
    const triad = (runtime.agents && runtime.agents.agents) || {};
    const architect = String((triad.architect && triad.architect.status) || 'unknown');
    const dream = String((triad.dream && triad.dream.status) || 'unknown');
    const beast = String((triad.beast && triad.beast.status) || 'unknown');
    return [
      '### /health',
      '',
      `- architect: **${architect}**`,
      `- dream: **${dream}**`,
      `- beast: **${beast}**`,
    ].join('\n');
  }

  const SKILL_REGISTRY = Object.freeze({
    '/gate': { intent: 'gate', handler: fmtGate },
    '/replay': { intent: 'replay', handler: fmtReplay },
    '/blockers': { intent: 'blockers', handler: fmtBlockers },
    '/phase': { intent: 'phase', handler: fmtPhase },
    '/evidence': { intent: 'evidence', handler: fmtEvidence },
    '/health': { intent: 'health', handler: fmtHealth },
  });

  function routeSkill(text, stateBus) {
    const parsed = parseIntent(text);
    const command = parsed.command || '';
    const runtime = pickRuntimeSnapshot(stateBus);
    if (!command || !(command in SKILL_REGISTRY)) {
      return {
        schema: SCHEMA_VERSION,
        intent: parsed.intent,
        command,
        confidence: parsed.confidence,
        markdown: '',
        needs_clarification: true,
        clarifying_question: 'I can run /gate, /replay, /blockers, /phase, /evidence, or /health. Which one should I execute?',
        failure_reason: command ? 'command_not_registered' : 'intent_not_recognized',
      };
    }

    if (parsed.confidence < LOW_CONFIDENCE_THRESHOLD) {
      return {
        schema: SCHEMA_VERSION,
        intent: parsed.intent,
        command,
        confidence: parsed.confidence,
        markdown: '',
        needs_clarification: true,
        clarifying_question: `Did you want ${command}? Reply with ${command} to confirm.`,
        failure_reason: 'low_confidence',
      };
    }

    const markdown = SKILL_REGISTRY[command].handler(runtime);
    return {
      schema: SCHEMA_VERSION,
      intent: parsed.intent,
      command,
      confidence: parsed.confidence,
      markdown,
      needs_clarification: false,
      clarifying_question: '',
      failure_reason: '',
    };
  }

  global.DORK_SKILLS = {
    SCHEMA_VERSION,
    LOW_CONFIDENCE_THRESHOLD,
    ROUTER_OUTPUT_KEYS,
    SKILL_REGISTRY,
    parseIntent,
    routeSkill,
    pickRuntimeSnapshot,
  };
})(window);
