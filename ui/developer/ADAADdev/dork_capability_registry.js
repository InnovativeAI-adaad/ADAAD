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

  function toFiniteNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function trimSha(value) {
    const raw = String(value || '').trim();
    return raw ? raw.slice(0, 10) : '';
  }

  function evidenceTag(entry, idx) {
    if (!entry || typeof entry !== 'object') return 'event:unknown-' + idx;
    const epoch = String(entry.epoch || entry.epoch_id || '').trim();
    const sha = trimSha(entry.sha || entry.hash);
    const eventId = String(entry.event_id || entry.id || ('evt-' + idx)).trim();
    return [epoch ? 'epoch:' + epoch : '', sha ? 'sha:' + sha : '', eventId ? 'event:' + eventId : ''].filter(Boolean).join(' · ') || 'event:unknown-' + idx;
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
      id: 'replay_causal_graph',
      label: 'replay causal graph',
      intents: ['replay', 'causal', 'graph', 'divergence'],
      triggers: [/\bcausal\b/i, /\broot cause\b/i, /\bdivergence\b/i, /\border(?:ing)? mismatch\b/i, /\bhydration\b/i],
      dependencies: [
        { id: 'replay.score', path: 'rep.score', required: true, fallback: 'score_unavailable' },
        { id: 'replay.divergence', path: 'rep.divergence', required: true, fallback: 'divergence_assumed_zero' },
        { id: 'mutations.recent', path: 'muts.mutations', required: false, fallback: 'mutations_unavailable' },
        { id: 'ledger.entries', path: 'ledger.entries', required: false, fallback: 'agent_actions_unavailable' },
      ],
      execute(context) {
        const deps = dependencySnapshot(context, this.dependencies);
        const score = toFiniteNumber(readPath(context, 'rep.score'), 0);
        const divergence = toFiniteNumber(readPath(context, 'rep.divergence'), 0);
        const divergenceMeta = readPath(context, 'rep.divergence_metadata') || readPath(context, 'rep.divergence_meta') || {};
        const recentMutations = Array.isArray(readPath(context, 'muts.mutations')) ? readPath(context, 'muts.mutations').slice(-8) : [];
        const ledgerEntries = Array.isArray(readPath(context, 'ledger.entries')) ? readPath(context, 'ledger.entries').slice(-12) : [];
        const agentHealth = readPath(context, 'agents.agents') || {};
        const fallbackUsed = readPath(context, 'rep.score') === undefined;

        const metaFlags = new Set(Array.isArray(divergenceMeta.flags) ? divergenceMeta.flags.map((v) => String(v).toLowerCase()) : []);
        const latestEvents = Array.isArray(divergenceMeta.latest_events) ? divergenceMeta.latest_events : [];
        latestEvents.forEach((ev) => {
          const evText = JSON.stringify(ev).toLowerCase();
          if (evText.includes('provider')) metaFlags.add('provider');
          if (evText.includes('ordering')) metaFlags.add('ordering');
          if (evText.includes('hydration') || evText.includes('hydrate')) metaFlags.add('hydration');
          if (evText.includes('input') || evText.includes('prompt')) metaFlags.add('input');
        });

        const mutationText = recentMutations.map((m) => JSON.stringify(m).toLowerCase()).join(' ');
        const ledgerText = ledgerEntries.map((e) => JSON.stringify(e).toLowerCase()).join(' ');
        const actionText = mutationText + ' ' + ledgerText;

        const scores = {
          provider_nondeterminism: Math.max(0, (1 - score) * 0.55 + (metaFlags.has('provider') ? 0.35 : 0) + ((actionText.match(/provider|ollama|groq|engine/g) || []).length * 0.03)),
          input_drift: Math.max(0, (metaFlags.has('input') ? 0.34 : 0.08) + ((actionText.match(/prompt|input|seed|context/g) || []).length * 0.04) + (divergence > 0 ? 0.1 : 0)),
          ordering_mismatch: Math.max(0, (metaFlags.has('ordering') ? 0.34 : 0.06) + ((actionText.match(/reorder|ordering|sequence|out_of_order/g) || []).length * 0.05) + (divergence > 0 ? 0.14 : 0)),
          state_hydration_mismatch: Math.max(0, (metaFlags.has('hydration') ? 0.34 : 0.05) + ((actionText.match(/hydrate|snapshot|restore|state/g) || []).length * 0.05) + (divergence > 0 ? 0.12 : 0)),
        };

        const evidencePool = [...latestEvents, ...recentMutations, ...ledgerEntries].slice(-14);
        const evidence = evidencePool.map((entry, idx) => evidenceTag(entry, idx + 1)).filter(Boolean);

        const nodeCatalog = [
          { id: 'provider_nondeterminism', label: 'provider nondeterminism', mitigation: 'Pin deterministic provider route (single model + fixed decoding), freeze provider fallback order, and lock seed for replay windows.' },
          { id: 'input_drift', label: 'input drift', mitigation: 'Freeze canonical input envelope (prompt + context hash), diff every epoch input bundle, and reject un-hashed input mutations.' },
          { id: 'ordering_mismatch', label: 'ordering mismatch', mitigation: 'Force stable event ordering by sequence key, replay sorted mutation/action streams, and block non-monotonic event IDs.' },
          { id: 'state_hydration_mismatch', label: 'state hydration mismatch', mitigation: 'Hydrate from a single signed snapshot digest, verify state fingerprint pre/post replay, and invalidate stale cache hydrations.' },
        ];

        const ranked = nodeCatalog
          .map((node) => ({ ...node, score: Number(scores[node.id] || 0) }))
          .sort((a, b) => b.score - a.score);
        const top3 = ranked.slice(0, 3).map((node, idx) => ({
          rank: idx + 1,
          cause_id: node.id,
          cause: node.label,
          probability: Number(Math.max(0.05, Math.min(0.98, node.score)).toFixed(3)),
          evidence_links: evidence.slice(idx * 2, idx * 2 + 2),
          mitigation: node.mitigation,
        }));

        const summary = top3.length
          ? `Top cause: ${top3[0].cause} (${Math.round(top3[0].probability * 100)}%) · replay ${score.toFixed(3)} · divergence ${divergence}.`
          : `Replay causal graph built with limited evidence · replay ${score.toFixed(3)} · divergence ${divergence}.`;
        const details = top3.map((item) => `#${item.rank} ${item.cause} (${Math.round(item.probability * 100)}%) — evidence ${item.evidence_links.join(' | ') || 'none'}`);
        const nextActions = top3.map((item) => item.mitigation);
        const confidence = fallbackUsed ? 0.53 : Math.max(0.58, Math.min(0.96, 0.62 + (top3[0] ? top3[0].probability * 0.25 : 0)));

        return {
          ...buildCard(this.id, summary, details, nextActions, confidence, deps, fallbackUsed),
          graph: {
            nodes: ranked.map((node) => ({ id: node.id, label: node.label, score: Number(node.score.toFixed(3)) })),
            edges: [
              { from: 'provider_nondeterminism', to: 'ordering_mismatch', weight: 0.38 },
              { from: 'input_drift', to: 'ordering_mismatch', weight: 0.29 },
              { from: 'ordering_mismatch', to: 'state_hydration_mismatch', weight: 0.43 },
              { from: 'input_drift', to: 'state_hydration_mismatch', weight: 0.26 },
            ],
            top_causes: top3,
            context: {
              replay_score: score,
              divergence,
              epoch_ids: evidence.filter((tag) => tag.includes('epoch:')).slice(0, 5),
              sha_fragments: evidence.filter((tag) => tag.includes('sha:')).slice(0, 5),
              event_ids: evidence.filter((tag) => tag.includes('event:')).slice(0, 5),
              agents: Object.keys(agentHealth || {}),
            },
          },
        };
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
      id: 'epoch_delta_interpreter',
      label: 'epoch delta',
      intents: ['epoch', 'delta', 'changes', 'interpretation'],
      triggers: [/\bwhat changed\b/i, /\bchanged since\b/i, /\blast epoch\b/i, /\bdelta\b/i],
      dependencies: [
        { id: 'before.governance', path: 'before.gov', required: true, fallback: 'before_snapshot_missing' },
        { id: 'after.governance', path: 'after.gov', required: true, fallback: 'after_snapshot_missing' },
        { id: 'after.replay', path: 'after.rep', required: false, fallback: 'replay_unavailable' },
        { id: 'after.readiness', path: 'after.ready', required: false, fallback: 'readiness_unavailable' },
      ],
      execute(context) {
        const before = context && context.before ? context.before : {};
        const after = context && context.after ? context.after : context || {};
        const deps = dependencySnapshot({ before, after }, this.dependencies);
        const fallbackUsed = !before || !before.gov;
        const semantic = [];
        const impacted = new Set();
        const actions = [];
        let risk = 0;

        const beforeLocked = Boolean(readPath(before, 'gov.locked'));
        const afterLocked = Boolean(readPath(after, 'gov.locked'));
        if (beforeLocked !== afterLocked) {
          impacted.add('governance');
          if (afterLocked) {
            risk += 55;
            semantic.push('Governance gate moved to LOCKED.');
            actions.push('Resolve governance lock reason before mutations.');
          } else {
            risk += 10;
            semantic.push('Governance gate reopened to PASS.');
          }
        }

        const beforeDiv = Number(readPath(before, 'rep.divergence') || 0);
        const afterDiv = Number(readPath(after, 'rep.divergence') || 0);
        if (beforeDiv !== afterDiv) {
          impacted.add('replay');
          if (afterDiv > beforeDiv) {
            risk += 30;
            semantic.push('Replay divergence increased.');
            actions.push('Run strict replay verification and inspect latest manifest diff.');
          } else {
            semantic.push('Replay divergence improved.');
          }
        }

        const beforeReady = Number(readPath(before, 'ready.readiness_score') || 0);
        const afterReady = Number(readPath(after, 'ready.readiness_score') || 0);
        if (beforeReady !== afterReady) {
          impacted.add('release_readiness');
          if (afterReady < beforeReady) {
            risk += 24;
            semantic.push('Readiness score regressed.');
            actions.push('Prioritize readiness blockers before release gate.');
          } else {
            semantic.push('Readiness score improved.');
          }
        }

        const beforeMut = Number(readPath(before, 'muts.total') || 0);
        const afterMut = Number(readPath(after, 'muts.total') || 0);
        if (beforeMut !== afterMut) {
          impacted.add('mutation_pipeline');
          const delta = afterMut - beforeMut;
          semantic.push('Mutation queue ' + (delta >= 0 ? 'grew' : 'shrunk') + ' by ' + Math.abs(delta) + '.');
          if (delta > 0) {
            risk += delta >= 5 ? 20 : 10;
            actions.push('Review queued mutations for constitutional compliance.');
          }
        }

        if (!semantic.length) {
          semantic.push('No material semantic shifts detected across tracked feeds.');
        }
        const riskLevel = risk >= 80 ? 'critical' : risk >= 45 ? 'high' : risk >= 20 ? 'medium' : 'low';
        const confidence = fallbackUsed ? 0.58 : Math.min(0.97, 0.72 + semantic.length * 0.05);
        const summary = 'What changed since last epoch? risk=' + riskLevel + ' · impacted=' + (Array.from(impacted).join(', ') || 'none') + '.';
        return buildCard(this.id, summary, semantic.slice(0, 3), Array.from(new Set(actions)).slice(0, 3), confidence, deps, fallbackUsed);
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
