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
// ── CAPABILITY REGISTRY EXTENSION v2.0 ───────────────────────────────────────
// Appended by DEVADAAD — dork-makeover-v2
// Adds 8 new capabilities and re-exports an enriched registry via
// DORK_CAPABILITY_REGISTRY_V2 (backward-compatible; merges with base registry).
(function extendDorkCapabilityRegistry(global) {
  'use strict';

  function readPath(obj, path) {
    if (!obj) return undefined;
    const parts = String(path).split('.');
    let cur = obj;
    for (const part of parts) {
      if (cur == null || typeof cur !== 'object' || !(part in cur)) return undefined;
      cur = cur[part];
    }
    return cur;
  }

  function buildCard(id, summary, details, nextActions, confidence, dependencies, fallbackUsed) {
    return { capability_id: id, summary, details, next_actions: nextActions, confidence, dependencies: dependencies || [], fallback_used: Boolean(fallbackUsed) };
  }

  function toFin(v, fb) { const n = Number(v); return Number.isFinite(n) ? n : fb; }

  const EXTENDED_CAPABILITIES = [
    // ── 1. Mutation Pipeline Inspector ──────────────────────────────────
    {
      id: 'mutation_pipeline_inspector',
      label: 'mutation pipeline',
      intents: ['mutation', 'pipeline', 'queue', 'promotion'],
      triggers: [/\bmutation\b/i, /\bpipeline\b/i, /\bpromotion\b/i, /\bqueue\b/i, /\bpatch\b/i],
      dependencies: [
        { id: 'muts.total', path: 'muts.total', required: true, fallback: 'queue_unknown' },
        { id: 'muts.pending', path: 'muts.pending', required: false, fallback: 'pending_unknown' },
        { id: 'muts.rejected', path: 'muts.rejected', required: false, fallback: 'rejected_unknown' },
      ],
      execute(context) {
        const total = toFin(readPath(context, 'muts.total'), null);
        const pending = toFin(readPath(context, 'muts.pending'), 0);
        const rejected = toFin(readPath(context, 'muts.rejected'), 0);
        const recent = Array.isArray(readPath(context, 'muts.mutations')) ? readPath(context, 'muts.mutations').slice(-5) : [];
        const fallbackUsed = total === null;
        const confidence = fallbackUsed ? 0.45 : pending === 0 ? 0.91 : 0.78;
        const summary = fallbackUsed
          ? 'Mutation pipeline data unavailable from state bus snapshot.'
          : `Pipeline: ${total} total · ${pending} pending · ${rejected} rejected.`;
        const details = fallbackUsed
          ? ['Connect state bus to ADAAD runtime for live mutation metrics.']
          : [
              `${pending} mutations awaiting GovernanceGate evaluation.`,
              `${rejected} mutations rejected in current epoch.`,
              recent.length ? `Latest: ${recent.map((m) => String(m.epoch_id || m.id || '?').slice(0, 8)).join(', ')}.` : 'No recent mutation IDs in snapshot.',
            ];
        const nextActions = pending > 5
          ? ['Review mutation backlog — high pending count may indicate governance bottleneck.', 'Run governance gate status check.']
          : pending > 0
          ? ['Advance pending mutations through governance evaluation cycle.']
          : ['Pipeline clear — continue normal evolution cadence.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 2. Ledger Forensics ──────────────────────────────────────────
    {
      id: 'ledger_forensics',
      label: 'ledger forensics',
      intents: ['ledger', 'forensics', 'audit', 'provenance', 'evidence'],
      triggers: [/\bledger\b/i, /\bforensic\b/i, /\bprovenance\b/i, /\baudit trail\b/i, /\bevidence\b/i],
      dependencies: [
        { id: 'ledger.entries', path: 'ledger.entries', required: true, fallback: 'ledger_unavailable' },
        { id: 'ledger.hash', path: 'ledger.hash', required: false, fallback: 'hash_unknown' },
      ],
      execute(context) {
        const entries = Array.isArray(readPath(context, 'ledger.entries')) ? readPath(context, 'ledger.entries') : null;
        const hash = readPath(context, 'ledger.hash') || 'unknown';
        const fallbackUsed = entries === null;
        const recent = fallbackUsed ? [] : entries.slice(-8);
        const confidence = fallbackUsed ? 0.4 : 0.93;
        const approvals = recent.filter((e) => e && String(e.type || e.event || '').toLowerCase().includes('approv')).length;
        const rejections = recent.filter((e) => e && String(e.type || e.event || '').toLowerCase().includes('reject')).length;
        const summary = fallbackUsed
          ? 'Ledger data not present in current state bus snapshot — forensics unavailable.'
          : `Ledger: ${entries.length} total entries · hash ${String(hash).slice(0, 12)} · last 8: ${approvals} approvals, ${rejections} rejections.`;
        const details = fallbackUsed
          ? ['Populate ledger.entries in state bus to enable forensics.']
          : [
              `Chain head hash: ${String(hash).slice(0, 16)}…`,
              `Last 8 entries cover ${approvals} approvals and ${rejections} rejections.`,
              recent.length ? `Most recent epoch IDs: ${recent.map((e) => String(e.epoch_id || e.id || '?').slice(0, 8)).join(' · ')}.` : 'No epoch IDs available.',
            ];
        const nextActions = fallbackUsed
          ? ['Connect ledger endpoint to state bus or import a forensic bundle.']
          : ['Export forensic bundle for external audit.', 'Cross-reference with replay digest to verify chain integrity.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 3. Constitution Diff ─────────────────────────────────────────
    {
      id: 'constitution_diff',
      label: 'constitution diff',
      intents: ['constitution', 'diff', 'amendment', 'invariant', 'rule change'],
      triggers: [/\bconstitution\b/i, /\bamendment\b/i, /\binvariant\b/i, /\brule change\b/i, /\bconst(?:itution)? diff\b/i],
      dependencies: [
        { id: 'gov.constitution_version', path: 'gov.constitution_version', required: true, fallback: 'version_unknown' },
        { id: 'gov.invariant_count', path: 'gov.invariant_count', required: false, fallback: 'count_unknown' },
      ],
      execute(context) {
        const version = readPath(context, 'gov.constitution_version') || null;
        const invariantCount = toFin(readPath(context, 'gov.invariant_count'), null);
        const amendments = Array.isArray(readPath(context, 'gov.amendments')) ? readPath(context, 'gov.amendments') : [];
        const fallbackUsed = version === null;
        const confidence = fallbackUsed ? 0.43 : amendments.length === 0 ? 0.88 : 0.94;
        const summary = fallbackUsed
          ? 'Constitution version not available in state bus snapshot.'
          : `Constitution v${version} · ${invariantCount !== null ? invariantCount : '?'} Hard invariants · ${amendments.length} recorded amendments.`;
        const details = fallbackUsed
          ? ['Hydrate gov.constitution_version from the governance endpoint.']
          : [
              `Current version: ${version}.`,
              `Active Hard invariants: ${invariantCount !== null ? invariantCount : 'count unavailable'}.`,
              amendments.length ? `Recent amendments: ${amendments.slice(-3).map((a) => a.id || a.label || '?').join(', ')}.` : 'No amendments recorded in snapshot.',
            ];
        const nextActions = fallbackUsed
          ? ['Run GET /api/governance/constitution to hydrate version data.']
          : amendments.length
          ? ['Review amendment details for invariant surface area impact.', 'Ensure CHANGELOG reflects constitution version bump.']
          : ['Constitution stable — continue normal governance cadence.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 4. Phase Progress Tracker ────────────────────────────────────
    {
      id: 'phase_progress_tracker',
      label: 'phase progress',
      intents: ['phase', 'progress', 'roadmap', 'milestone', 'current phase'],
      triggers: [/\bphase\b/i, /\bprogress\b/i, /\broadmap\b/i, /\bmilestone\b/i, /\bcurrent phase\b/i],
      dependencies: [
        { id: 'state.phase', path: 'phase', required: true, fallback: 'phase_unknown' },
        { id: 'state.version', path: 'version', required: false, fallback: 'version_unknown' },
      ],
      execute(context) {
        const phase = toFin(readPath(context, 'phase') || readPath(context, 'stateBus.phase'), null);
        const version = readPath(context, 'version') || readPath(context, 'stateBus.version') || null;
        const nextPhase = readPath(context, 'next_phase') || readPath(context, 'stateBus.next_phase') || null;
        const fallbackUsed = phase === null;
        const confidence = fallbackUsed ? 0.42 : 0.92;
        const summary = fallbackUsed
          ? 'Phase data not available in current state bus snapshot. ADAAD is at Phase 125, v9.58.0 per last known state.'
          : `Phase ${phase}${version ? ' · v' + version : ''}${nextPhase ? ' · next: Phase ' + nextPhase : ''}.`;
        const details = fallbackUsed
          ? ['Hydrate state bus with phase and version fields from .adaad_agent_state.json.', 'Last known state: Phase 125, v9.58.0.']
          : [
              `Active phase: ${phase}.`,
              version ? `Aligned version: v${version}.` : 'Version not in snapshot.',
              nextPhase ? `Next phase queued: ${nextPhase}.` : 'No next phase queued in snapshot.',
            ];
        const nextActions = fallbackUsed
          ? ['Connect ADAAD state bus to Whale.Dic for live phase tracking.']
          : ['Cross-reference ROADMAP.md for phase deliverable checklist.', 'Verify four-surface version alignment before next phase push.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 5. Sandbox Preflight Checker ─────────────────────────────────
    {
      id: 'sandbox_preflight_checker',
      label: 'sandbox preflight',
      intents: ['sandbox', 'preflight', 'isolation', 'test', 'dry-run'],
      triggers: [/\bsandbox\b/i, /\bpreflight\b/i, /\bisolat\b/i, /\bdry.?run\b/i, /\btest env\b/i],
      dependencies: [
        { id: 'sandbox.last_result', path: 'sandbox.last_result', required: true, fallback: 'no_preflight_data' },
        { id: 'sandbox.pass_rate', path: 'sandbox.pass_rate', required: false, fallback: 'pass_rate_unknown' },
      ],
      execute(context) {
        const lastResult = readPath(context, 'sandbox.last_result');
        const passRate = toFin(readPath(context, 'sandbox.pass_rate'), null);
        const warnings = Array.isArray(readPath(context, 'sandbox.warnings')) ? readPath(context, 'sandbox.warnings') : [];
        const fallbackUsed = !lastResult;
        const passed = lastResult === 'pass' || lastResult === true || lastResult === 'passed';
        const confidence = fallbackUsed ? 0.44 : passed && warnings.length === 0 ? 0.95 : 0.73;
        const summary = fallbackUsed
          ? 'No sandbox preflight result in state bus — cannot verify isolation status.'
          : `Sandbox preflight: ${passed ? 'PASS' : 'FAIL'}${passRate !== null ? ' · pass rate ' + Math.round(passRate * 100) + '%' : ''}${warnings.length ? ' · ' + warnings.length + ' warning(s)' : ''}.`;
        const details = fallbackUsed
          ? ['Run a sandbox preflight before advancing any mutation to signing.']
          : [
              `Last preflight result: ${String(lastResult)}.`,
              passRate !== null ? `Test pass rate: ${Math.round(passRate * 100)}%.` : 'Pass rate not in snapshot.',
              warnings.length ? `Warnings: ${warnings.slice(0, 3).join('; ')}.` : 'No preflight warnings.',
            ];
        const nextActions = !passed && !fallbackUsed
          ? ['Investigate failing preflight tests before advancing mutation.', 'Check resource bound violations in sandbox log.']
          : warnings.length
          ? ['Review preflight warnings — they do not block but may indicate governance surface area risks.']
          : ['Preflight clear — proceed to GovernanceGate evaluation.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 6. Agent Proposal Ranker ─────────────────────────────────────
    {
      id: 'agent_proposal_ranker',
      label: 'proposal ranker',
      intents: ['proposal', 'rank', 'score', 'fitness', 'compare agents'],
      triggers: [/\bproposal\b/i, /\brank(?:ing)?\b/i, /\bbest proposal\b/i, /\bcompare agent\b/i, /\bfitness rank\b/i],
      dependencies: [
        { id: 'proposals.list', path: 'proposals.list', required: true, fallback: 'proposals_unavailable' },
        { id: 'oracle.scores', path: 'oracle.scores', required: false, fallback: 'scores_unavailable' },
      ],
      execute(context) {
        const proposals = Array.isArray(readPath(context, 'proposals.list')) ? readPath(context, 'proposals.list') : null;
        const fallbackUsed = proposals === null;
        const ranked = fallbackUsed ? [] : proposals
          .map((p) => ({ ...p, _score: toFin(p.fitness_score || p.score, 0) }))
          .sort((a, b) => b._score - a._score)
          .slice(0, 5);
        const confidence = fallbackUsed ? 0.42 : ranked.length === 0 ? 0.55 : 0.89;
        const summary = fallbackUsed
          ? 'Proposal list not available in state bus — ranker cannot operate.'
          : ranked.length === 0
          ? 'No active proposals in current snapshot.'
          : `Top proposal: ${ranked[0].id || ranked[0].epoch_id || '?'} (agent: ${ranked[0].agent || '?'}, fitness: ${ranked[0]._score.toFixed(3)}).`;
        const details = fallbackUsed
          ? ['Populate proposals.list in state bus to enable ranking.']
          : ranked.map((p, i) => `#${i + 1} ${p.id || p.epoch_id || '?'} · agent: ${p.agent || '?'} · fitness: ${p._score.toFixed(3)}`);
        const nextActions = fallbackUsed
          ? ['Connect Oracle scoring endpoint to state bus.']
          : ranked.length
          ? ['Advance top-ranked proposal to GovernanceGate evaluation.', 'Review agent distribution — balanced triad proposals indicate healthy competition.']
          : ['Trigger agent proposal cycle from the mutation orchestrator.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 7. Signing Ceremony Status ───────────────────────────────────
    {
      id: 'signing_ceremony_status',
      label: 'signing ceremony',
      intents: ['signing', 'gpg', 'ceremony', 'tag', 'human-0', 'attestation'],
      triggers: [/\bsign(?:ing)?\b/i, /\bgpg\b/i, /\bceremony\b/i, /\btrack.?b\b/i, /\battesta(?:tion)?\b/i, /\bhuman.?0\b/i],
      dependencies: [
        { id: 'gov.last_signed_tag', path: 'gov.last_signed_tag', required: false, fallback: 'tag_unknown' },
        { id: 'gov.signing_pending', path: 'gov.signing_pending', required: false, fallback: 'pending_unknown' },
      ],
      execute(context) {
        const lastTag = readPath(context, 'gov.last_signed_tag') || null;
        const pending = readPath(context, 'gov.signing_pending');
        const pendingBool = pending === true || pending === 'true' || pending === 1;
        const fallbackUsed = lastTag === null && pending === undefined;
        const confidence = fallbackUsed ? 0.55 : pendingBool ? 0.88 : 0.91;
        const summary = fallbackUsed
          ? 'Signing ceremony data not in state bus. HUMAN-0 authority required for all GPG tag operations — this cannot be delegated via chat.'
          : pendingBool
          ? `Signing ceremony PENDING. Last signed tag: ${lastTag || 'none'}. HUMAN-0 action required on ADAADell.`
          : `Signing ceremony status: no pending ceremony. Last signed tag: ${lastTag || 'none'}.`;
        const details = [
          'GPG signing is a Track B action — must be performed by HUMAN-0 on ADAADell.',
          'Required steps: export GPG_TTY=$(tty) → git tag -s vX.Y.Z -m "message" → git push origin vX.Y.Z.',
          'Fingerprint: 4C95E2F99A775335B1CF3DAF247B015A1CCD95F6. Chat-based authorization cannot substitute for the physical key.',
        ];
        const nextActions = pendingBool
          ? ['HUMAN-0: perform GPG tag ceremony on ADAADell (Track B runbook).', 'After signing, verify tag appears on origin with git ls-remote --tags.']
          : ['No action required for signing at this time.', 'Verify signed tag list with git tag -v <tag> from ADAADell.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },

    // ── 8. Market Fitness Readiness ──────────────────────────────────
    {
      id: 'market_fitness_readiness',
      label: 'market fitness',
      intents: ['market', 'fitness', 'demand', 'adoption', 'innov-22'],
      triggers: [/\bmarket\b/i, /\bdemand\b/i, /\badoption\b/i, /\binnov.?22\b/i, /\bmarket fitness\b/i],
      dependencies: [
        { id: 'market.score', path: 'market.fitness_score', required: false, fallback: 'score_unavailable' },
        { id: 'market.signals', path: 'market.demand_signals', required: false, fallback: 'signals_unavailable' },
      ],
      execute(context) {
        const score = toFin(readPath(context, 'market.fitness_score'), null);
        const signals = Array.isArray(readPath(context, 'market.demand_signals')) ? readPath(context, 'market.demand_signals') : [];
        const phase107Ready = Boolean(readPath(context, 'market.phase107_active'));
        const fallbackUsed = score === null && signals.length === 0;
        const confidence = fallbackUsed ? 0.46 : phase107Ready ? 0.9 : 0.71;
        const summary = fallbackUsed
          ? 'Market fitness data unavailable. INNOV-22 (market_fitness.py) is the Phase 107 implementation. Check phase107 deployment status.'
          : `Market fitness score: ${score !== null ? score.toFixed(3) : 'N/A'} · ${signals.length} demand signals active · Phase 107 module: ${phase107Ready ? 'ACTIVE' : 'PENDING'}.`;
        const details = fallbackUsed
          ? ['Market-Conditioned Fitness (INNOV-22) extends the Oracle scoring pipeline with external demand signals.', 'Scaffold exists in market_fitness.py — full implementation in Phase 107.', 'Demand signals: feature request rate, adoption curve delta, operator-weighted priority.']
          : [
              `Fitness score: ${score !== null ? score.toFixed(3) : 'not computed'}.`,
              signals.length ? `Active signals: ${signals.slice(0, 4).map((s) => s.id || s.name || '?').join(', ')}.` : 'No demand signals in snapshot.',
              `Phase 107 market_fitness module: ${phase107Ready ? 'active and scoring' : 'not yet active'}.`,
            ];
        const nextActions = !phase107Ready
          ? ['Advance to Phase 107 to activate market_fitness.py full implementation.', 'Review INNOV-22 scaffold and constitutional requirements before promotion.']
          : score !== null && score < 0.5
          ? ['Low market fitness score — review demand signal weights with operator.', 'Consider proposal prioritisation adjustment.']
          : ['Monitor market fitness signal health over next epoch.', 'Compare market fitness vs. standard fitness for promotion ranking delta.'];
        return buildCard(this.id, summary, details, nextActions, confidence, [], fallbackUsed);
      },
    },
    // ── Phase 132 · INNOV-41 · DORK Living Fleet capabilities ────────────────
    {
      id: 'fleet_health_monitor',
      label: 'DORK fleet health',
      intents: ['fleet', 'provider', 'health', 'engine', 'ollama', 'blocked'],
      triggers: [/\bfleet\b/i, /\bprovider\b/i, /\bellama\b/i, /\bengine\s+health\b/i, /\bno\s+healthy\b/i],
      dependencies: [
        { id: 'fleet.healthy_count', path: 'fleet.healthy_provider_count', required: true, fallback: 'count_unavailable' },
        { id: 'fleet.blocked', path: 'fleet.blocked', required: true, fallback: 'status_unknown' },
        { id: 'fleet.providers', path: 'fleet.providers', required: false, fallback: 'providers_unavailable' },
      ],
      execute(context) {
        const healthy = context?.fleet?.healthy_provider_count ?? null;
        const blocked = context?.fleet?.blocked ?? null;
        const providers = context?.fleet?.providers ?? {};
        const fallbackUsed = healthy === null;
        const confidence = fallbackUsed ? 0.40 : blocked ? 0.20 : healthy > 0 ? 0.94 : 0.30;
        const summary = fallbackUsed
          ? 'Fleet health unavailable — runtime context not loaded.'
          : blocked
            ? `DORK-FLEET-0: Fleet BLOCKED — 0 healthy providers. Restore at least one provider.`
            : `Fleet healthy: ${healthy} provider(s) available and responding.`;
        const details = fallbackUsed
          ? ['Load runtime state to inspect provider fleet.']
          : Object.entries(providers).map(([name, s]) =>
              `${name}: ${s.healthy ? '✅' : '❌'} availability=${(s.availability * 100).toFixed(0)}%`);
        const nextActions = blocked
          ? ['Check Ollama is running: ollama serve', 'Probe provider: /dork:fleet', 'Review provider_config.json']
          : ['Monitor provider availability.', 'Run /dork:fleet for real-time status.'];
        return { id: this.id, summary, details, nextActions, confidence, fallbackUsed };
      },
    },
    {
      id: 'slash_command_dispatcher',
      label: 'DORK slash commands',
      intents: ['slash', 'command', 'resolver', 'dork:', '/dork', 'dispatch'],
      triggers: [/^\/dork:/i, /\bslash\s+command\b/i, /\bdork:help\b/i, /\bcmd\s+resolver\b/i],
      dependencies: [
        { id: 'fleet.cmd_resolver_loaded', path: 'fleet.cmd_resolver_loaded', required: true, fallback: 'resolver_unknown' },
        { id: 'fleet.cmd_resolver_commands', path: 'fleet.cmd_resolver_commands', required: false, fallback: 0 },
      ],
      execute(context) {
        const loaded = context?.fleet?.cmd_resolver_loaded ?? null;
        const count = context?.fleet?.cmd_resolver_commands ?? 0;
        const fallbackUsed = loaded === null;
        const confidence = fallbackUsed ? 0.45 : loaded ? 0.95 : 0.25;
        const summary = fallbackUsed
          ? 'Command resolver status unknown — check fleet context.'
          : loaded
            ? `DorkCommandResolver active: ${count} slash commands registered (DORK-CMD-0 enforced).`
            : 'DORK-CMD-0 VIOLATION: CommandResolver not loaded — manifest missing.';
        const details = loaded
          ? [
              'All commands validated against slash_commands.json before dispatch.',
              'Unknown commands rejected with structured CommandError.',
              'Every dispatch is hash-chained in the command ledger.',
              `Try: /dork:help, /dork:gate, /dork:fleet, /dork:brief`,
            ]
          : ['Verify data/dork/slash_commands.json exists.', 'Restart DORK fleet to reload manifest.'];
        const nextActions = loaded
          ? ['Run /dork:help to list all commands.', 'Use /dork:gate to check gate status.']
          : ['Restore slash_commands.json manifest.', 'Re-initialise DORKLivingFleet.'];
        return { id: this.id, summary, details, nextActions, confidence, fallbackUsed };
      },
    },
    {
      id: 'conversation_ledger_inspector',
      label: 'conversation ledger',
      intents: ['conversation', 'ledger', 'chat', 'history', 'chain', 'session'],
      triggers: [/\bconversation\s+ledger\b/i, /\bchat\s+history\b/i, /\bsession\s+chain\b/i, /\bledger.*conversation\b/i],
      dependencies: [
        { id: 'fleet.conversation_ledger_entries', path: 'fleet.conversation_ledger_entries', required: true, fallback: 0 },
      ],
      execute(context) {
        const entries = context?.fleet?.conversation_ledger_entries ?? null;
        const fallbackUsed = entries === null;
        const confidence = fallbackUsed ? 0.38 : 0.91;
        const summary = fallbackUsed
          ? 'Conversation ledger count unavailable — load fleet status context.'
          : `ConversationLedger: ${entries} entries, hash-chained (DORK-STATE-0 active).`;
        const details = [
          'Each turn is sealed with SHA-256 hash of role + content + timestamp + prev_hash.',
          'Append-only — mutation of any prior entry raises ConversationLedgerViolation.',
          'Chain is verifiable end-to-end with verify() at any point.',
        ];
        const nextActions = [
          'Query ledger tail via fleet.conversation_ledger_tail().',
          'Verify chain integrity before any audit export.',
        ];
        return { id: this.id, summary, details, nextActions, confidence, fallbackUsed };
      },
    },
    {
      id: 'intent_taxonomy_inspector',
      label: 'intent taxonomy',
      intents: ['intent', 'taxonomy', 'jaccard', 'classification', 'routing', 'category'],
      triggers: [/\bjaccard\b/i, /\btaxonomy\b/i, /\bintent\s+class/i, /\bquery\s+rout/i, /\bDORK-CTX/i],
      dependencies: [],
      execute(context) {
        const confidence = 0.92;
        const summary = 'DORK-CTX-0: CONTEXT_KEYWORD_TAXONOMY active — 8 categories, Jaccard-scored routing.';
        const details = [
          'Categories: governance, mutation, replay, ledger, agent, fleet, release, sandbox.',
          'Jaccard score = |intersection| / |union| of query tokens vs category keyword set.',
          'classify_query() returns (best_category, confidence) for every DORK query.',
          'Ad-hoc keyword routing outside the taxonomy is constitutionally prohibited.',
        ];
        const nextActions = [
          'Inspect CONTEXT_KEYWORD_TAXONOMY in dorkllm/context.py.',
          'Use get_taxonomy_hints(query, top_n=3) for multi-category scoring.',
        ];
        return { id: this.id, summary, details, nextActions, confidence, fallbackUsed: false };
      },
    },
    {
      id: 'provider_health_registry',
      label: 'provider health registry',
      intents: ['provider', 'registry', 'availability', 'probe', 'backend', 'DORK-PROV'],
      triggers: [/\bprovider\s+registry\b/i, /\bhealth\s+probe\b/i, /\bavailability.*provider\b/i, /\bDORK-PROV/i],
      dependencies: [
        { id: 'fleet.providers', path: 'fleet.providers', required: false, fallback: 'providers_unavailable' },
      ],
      execute(context) {
        const providers = context?.fleet?.providers ?? null;
        const fallbackUsed = providers === null;
        const count = providers ? Object.keys(providers).length : 0;
        const confidence = fallbackUsed ? 0.42 : count > 0 ? 0.93 : 0.50;
        const summary = fallbackUsed
          ? 'ProviderHealthRegistry: no data — load fleet status context.'
          : `ProviderHealthRegistry: ${count} provider(s) tracked (DORK-PROV-0 active).`;
        const details = fallbackUsed
          ? ['Initialise DORKLivingFleet and probe engines to populate registry.']
          : Object.entries(providers).map(([n, s]) =>
              `${n}: healthy=${s.healthy}, avail=${(s.availability * 100).toFixed(0)}%, probes=${s.probe_count}`);
        const nextActions = [
          'Probe individual engines: fleet.probe_engine(name).',
          'Review provider_config.json to add/remove backends.',
          'DORK-PROV-0: unhealthy providers are never silently skipped.',
        ];
        return { id: this.id, summary, details, nextActions, confidence, fallbackUsed };
      },
    },
  ];

  // Merge into the base registry exposed by the first module
  function mergeIntoRegistry() {
    const base = (global.DORK_CAPABILITY_REGISTRY && global.DORK_CAPABILITY_REGISTRY.registry) ? global.DORK_CAPABILITY_REGISTRY.registry : {};
    const merged = { ...base };
    EXTENDED_CAPABILITIES.forEach((cap) => { merged[cap.id] = Object.freeze(cap); });
    const frozenMerged = Object.freeze(merged);

    function listAll() { return Object.values(frozenMerged); }
    function match(query) {
      const text = String(query || '');
      return listAll().find((cap) => cap.triggers.some((p) => p.test(text))) || null;
    }
    function execute(id, ctx) { const c = frozenMerged[id]; return c ? c.execute(ctx || {}) : null; }
    function executeByQuery(query, ctx) { const m = match(query); return m ? execute(m.id, ctx) : null; }

    const api = { registry: frozenMerged, listCapabilities: listAll, matchCapability: match, executeCapability: execute, executeByQuery };
    global.DORK_CAPABILITY_REGISTRY = api;
    global.DORK_CAPABILITY_REGISTRY_V2 = api;
  }

  // Defer merge so base registry initialises first if both are in the same page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mergeIntoRegistry);
  } else {
    mergeIntoRegistry();
  }
})(window);
