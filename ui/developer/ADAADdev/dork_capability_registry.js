(function initDorkCapabilityRegistry(global) {
  'use strict';

  function readPath(obj, path) {
    if (!obj) return undefined;
    const parts = String(path).split('.');
    let cur = obj;
    for (const part of parts) {
      if (cur == null || typeof cur !== 'object' || !(part in cur)) {
        return undefined;
      }
      cur = cur[part];
    }
    return cur;
  }

  function hasDependency(context, dep) {
    return readPath(context, dep.path) !== undefined;
  }

  function dependencySnapshot(context, deps) {
    return deps.map((dep) => ({
      id: dep.id,
      path: dep.path,
      required: Boolean(dep.required),
      available: hasDependency(context, dep),
      fallback: dep.fallback,
    }));
  }

  function buildCard(id, summary, details, nextActions, confidence, dependencies, fallbackUsed) {
    return {
      capability_id: id,
      summary,
      details,
      next_actions: nextActions,
      confidence,
      dependencies,
      fallback_used: fallbackUsed,
    };
  }

  const CAPABILITIES = [
    {
      id: 'replay_health',
      label: 'replay health',
      intents: ['replay', 'health', 'determinism'],
      triggers: [/\breplay\b/i, /\bdivergence\b/i, /\bdetermin(istic|ism)\b/i],
      dependencies: [
        { id: 'replay.score', path: 'rep.score', required: true, fallback: 'score_unavailable' },
        { id: 'replay.divergence', path: 'rep.divergence', required: false, fallback: 'divergence_assumed_zero' },
        { id: 'replay.mode', path: 'rep.mode', required: false, fallback: 'mode_unknown' },
      ],
      execute(context) {
        const scoreRaw = readPath(context, 'rep.score');
        const score = Number.isFinite(Number(scoreRaw)) ? Number(scoreRaw) : null;
        const divergenceRaw = readPath(context, 'rep.divergence');
        const divergence = Number.isFinite(Number(divergenceRaw)) ? Number(divergenceRaw) : 0;
        const mode = readPath(context, 'rep.mode') || 'unknown';
        const deps = dependencySnapshot(context, this.dependencies);
        const fallbackUsed = score === null;
        const confidence = fallbackUsed ? 0.42 : score >= 0.99 && divergence === 0 ? 0.97 : score >= 0.9 ? 0.81 : 0.64;
        const summary = fallbackUsed
          ? 'Replay health unavailable from runtime snapshot; using deterministic fallback assumptions.'
          : `Replay score ${score.toFixed(3)} in ${mode} mode with divergence ${divergence}.`;
        const details = fallbackUsed
          ? ['No replay score found in context.', 'Assumed divergence=0 fallback for guidance only.']
          : [
              `Replay score threshold check: ${score >= 0.99 ? 'pass' : 'watch'}.`,
              `Divergence check: ${divergence === 0 ? 'stable' : 'non-zero divergence detected'}.`,
            ];
        const nextActions = fallbackUsed
          ? ['Refresh runtime state before gate decisions.', 'Query /api/replay/score for authoritative metrics.']
          : divergence > 0
            ? ['Pause mutation promotion.', 'Run replay verification and inspect latest manifest diff.']
            : ['Continue governed flow.', 'Monitor score drift over next epoch.'];

        return buildCard(this.id, summary, details, nextActions, confidence, deps, fallbackUsed);
      },
    },
    {
      id: 'governance_summary',
      label: 'governance summary',
      intents: ['governance', 'gate', 'tier'],
      triggers: [/\bgovernance\b/i, /\bgate\b/i, /\btier\b/i, /\bconstitution\b/i],
      dependencies: [
        { id: 'governance.locked', path: 'gov.locked', required: true, fallback: 'assume_unlocked' },
        { id: 'governance.tier', path: 'gov.tier', required: false, fallback: 'tier_unknown' },
        { id: 'governance.constitution_version', path: 'gov.constitution_version', required: false, fallback: 'version_unknown' },
      ],
      execute(context) {
        const locked = Boolean(readPath(context, 'gov.locked'));
        const tier = readPath(context, 'gov.tier') || 'unknown';
        const constitution = readPath(context, 'gov.constitution_version') || 'unknown';
        const deps = dependencySnapshot(context, this.dependencies);
        const fallbackUsed = readPath(context, 'gov.locked') === undefined;
        const confidence = fallbackUsed ? 0.5 : 0.93;
        const summary = `Governance gate is ${locked ? 'LOCKED' : 'PASS'} at tier ${tier} (constitution ${constitution}).`;
        const details = [
          `Mutation flow is ${readPath(context, 'gov.mutation_enabled') ? 'enabled' : 'disabled'} by policy signal.`,
          locked ? 'Lock state present; constrained path required.' : 'No active lock detected in current snapshot.',
        ];
        const nextActions = locked
          ? ['Resolve blocker checks before proposing mutations.', 'Re-run governance status endpoint and verify tier.']
          : ['Maintain gate checks and continue staged execution.', 'Track constitution version drift in release notes.'];
        return buildCard(this.id, summary, details, nextActions, confidence, deps, fallbackUsed);
      },
    },
    {
      id: 'agent_triad_diagnostics',
      label: 'agent triad diagnostics',
      intents: ['agents', 'triad', 'health'],
      triggers: [/\bagent\b/i, /\btriad\b/i, /\barchitect\b/i, /\bdream\b/i, /\bbeast\b/i],
      dependencies: [
        { id: 'agents.architect', path: 'agents.agents.architect.status', required: true, fallback: 'architect_unknown' },
        { id: 'agents.dream', path: 'agents.agents.dream.status', required: true, fallback: 'dream_unknown' },
        { id: 'agents.beast', path: 'agents.agents.beast.status', required: true, fallback: 'beast_unknown' },
      ],
      execute(context) {
        const arch = readPath(context, 'agents.agents.architect.status') || 'unknown';
        const dream = readPath(context, 'agents.agents.dream.status') || 'unknown';
        const beast = readPath(context, 'agents.agents.beast.status') || 'unknown';
        const deps = dependencySnapshot(context, this.dependencies);
        const allHealthy = [arch, dream, beast].every((s) => s === 'healthy');
        const fallbackUsed = [arch, dream, beast].includes('unknown');
        const confidence = fallbackUsed ? 0.58 : allHealthy ? 0.95 : 0.76;
        const summary = `Triad status — architect:${arch}, dream:${dream}, beast:${beast}.`;
        const details = [
          allHealthy ? 'All agents report healthy status.' : 'One or more agents require operator attention.',
          'Diagnostics are derived deterministically from latest triad snapshot.',
        ];
        const nextActions = allHealthy
          ? ['Proceed with normal orchestration cadence.', 'Keep monitoring per refresh cycle.']
          : ['Inspect failing agent telemetry.', 'Pause high-risk promotion until triad stabilizes.'];
        return buildCard(this.id, summary, details, nextActions, confidence, deps, fallbackUsed);
      },
    },
    {
      id: 'oracle_projection_explainer',
      label: 'oracle projection explainer',
      intents: ['oracle', 'projection', 'explain'],
      triggers: [/\boracle\b/i, /\bprojection\b/i, /\bforecast\b/i, /\bexplain\b/i],
      dependencies: [
        { id: 'oracle.query', path: 'stateBus.oracle_last_query', required: true, fallback: 'no_oracle_query' },
        { id: 'oracle.summary', path: 'stateBus.oracle_last_answer_summary', required: false, fallback: 'summary_unavailable' },
        { id: 'oracle.type', path: 'stateBus.oracle_last_query_type', required: false, fallback: 'generic' },
      ],
      execute(context) {
        const q = readPath(context, 'stateBus.oracle_last_query');
        const summaryRaw = readPath(context, 'stateBus.oracle_last_answer_summary');
        const type = readPath(context, 'stateBus.oracle_last_query_type') || 'generic';
        const deps = dependencySnapshot(context, this.dependencies);
        const fallbackUsed = !q;
        const confidence = fallbackUsed ? 0.45 : 0.9;
        const summary = fallbackUsed
          ? 'No Oracle projection exists in current session; explainer returned deterministic guidance fallback.'
          : `Oracle projection (${type}) interpreted for query: "${String(q).slice(0, 120)}".`;
        const details = fallbackUsed
          ? ['Oracle bridge has no prior query context.', 'Use Aponi Oracle panel to seed projection context.']
          : [
              `Projection summary: ${summaryRaw || 'summary not provided by source payload.'}`,
              'Interpretation anchored to latest ADAAD_STATE_BUS oracle fields.',
            ];
        const nextActions = fallbackUsed
          ? ['Run an Oracle query in Aponi.', 'Re-run explainer after state bus updates.']
          : ['Compare projection against replay/health metrics.', 'Convert high-confidence insight into checklist action.'];
        return buildCard(this.id, summary, details, nextActions, confidence, deps, fallbackUsed);
      },
    },
    {
      id: 'release_readiness_audit',
      label: 'release readiness audit',
      intents: ['release', 'readiness', 'audit', 'blockers'],
      triggers: [/\brelease\b/i, /\breadiness\b/i, /\bblocker\b/i, /\baudit\b/i],
      dependencies: [
        { id: 'readiness.score', path: 'ready.readiness_score', required: true, fallback: 'score_unavailable' },
        { id: 'readiness.blockers', path: 'ready.blockers', required: true, fallback: 'blockers_unknown' },
        { id: 'readiness.gate_ok', path: 'ready.gate_ok', required: false, fallback: 'gate_unknown' },
      ],
      execute(context) {
        const scoreRaw = readPath(context, 'ready.readiness_score');
        const blockers = Array.isArray(readPath(context, 'ready.blockers')) ? readPath(context, 'ready.blockers') : [];
        const gateOk = readPath(context, 'ready.gate_ok');
        const deps = dependencySnapshot(context, this.dependencies);
        const fallbackUsed = scoreRaw === undefined;
        const score = Number.isFinite(Number(scoreRaw)) ? Number(scoreRaw) : 0;
        const confidence = fallbackUsed ? 0.48 : blockers.length === 0 ? 0.94 : 0.82;
        const summary = `Release readiness ${Math.round(score * 100)}% with ${blockers.length} blocker(s).`;
        const details = [
          `Gate signal: ${gateOk === undefined ? 'unknown' : gateOk ? 'gate_ok' : 'gate_not_ok'}.`,
          blockers.length ? `Open blockers: ${blockers.join(', ')}.` : 'No active blockers reported.',
        ];
        const nextActions = blockers.length
          ? ['Address blockers in priority order.', 'Re-run release readiness endpoint after remediation.']
          : ['Proceed to release evidence verification.', 'Keep readiness checks in pre-merge cadence.'];
        return buildCard(this.id, summary, details, nextActions, confidence, deps, fallbackUsed);
      },
    },
  ];

  const REGISTRY = Object.freeze(CAPABILITIES.reduce((acc, capability) => {
    acc[capability.id] = Object.freeze(capability);
    return acc;
  }, {}));

  function listCapabilities() {
    return Object.values(REGISTRY);
  }

  function matchCapability(query) {
    const text = String(query || '');
    return listCapabilities().find((capability) => capability.triggers.some((pattern) => pattern.test(text))) || null;
  }

  function executeCapability(id, context) {
    const capability = REGISTRY[id];
    if (!capability) return null;
    return capability.execute(context || {});
  }

  function executeByQuery(query, context) {
    const matched = matchCapability(query);
    if (!matched) return null;
    return executeCapability(matched.id, context);
  }

  global.DORK_CAPABILITY_REGISTRY = {
    registry: REGISTRY,
    listCapabilities,
    matchCapability,
    executeCapability,
    executeByQuery,
  };
})(window);
