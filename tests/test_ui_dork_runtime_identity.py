# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import subprocess


def test_dork_prompt_and_welcome_follow_runtime_snapshot() -> None:
    node_script = r'''
const fs = require('fs');
const html = fs.readFileSync('ui/dork.html', 'utf8');

function extractConst(name) {
  const re = new RegExp(`const\\s+${name}\\s*=\\s*[^;]+;`);
  const m = html.match(re);
  if (!m) throw new Error(`Missing const ${name}`);
  return m[0];
}

function extractFunction(name) {
  const sig = `function ${name}(`;
  const start = html.indexOf(sig);
  if (start < 0) throw new Error(`Missing function ${name}`);
  const open = html.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < html.length; i++) {
    const ch = html[i];
    if (ch === '{') depth++;
    if (ch === '}') depth--;
    if (depth === 0) return html.slice(start, i + 1);
  }
  throw new Error(`Unclosed function ${name}`);
}

const src = [
  'let _cachedPrompt = null;',
  'let _cachedGovHash = null;',
  extractConst('CANONICAL_INNOVATION_COVERAGE'),
  extractFunction('formatRuntimeIdentity'),
  extractFunction('buildWelcomeMessage'),
  extractFunction('buildSystemPrompt'),
  'globalThis.S = { gov: null };',
  'globalThis.assert = (cond, msg) => { if (!cond) throw new Error(msg); };',
  `
const runtimeA = {
  epoch: { version: 'v1.0.0', phase: 1, epoch: 'ep-1' },
  gov: { invariant_count: 11, innovation_coverage: 'INNOV-01 through INNOV-11', ok: true, tier: 'T1' },
  rep: { score: 0.8 },
  ready: { readiness_score: 0.7 },
};
const runtimeB = {
  epoch: { version: 'v2.0.0', phase: 2, epoch: 'ep-2' },
  gov: { invariant_count: 22, innovation_coverage: 'INNOV-01 through INNOV-22', ok: true, tier: 'T2' },
  rep: { score: 0.9 },
  ready: { readiness_score: 0.8 },
};

S.gov = { runtime: runtimeA };
const welcomeA = buildWelcomeMessage();
const promptA = buildSystemPrompt();
assert(welcomeA.includes('v1.0.0'), 'welcome should reflect runtimeA version');
assert(welcomeA.includes('Phase 1'), 'welcome should reflect runtimeA phase');
assert(promptA.includes('v1.0.0 · Phase 1'), 'prompt should reflect runtimeA values');
assert(promptA.includes('INNOV-01 through INNOV-11'), 'prompt should reflect runtimeA innovation coverage');

S.gov = { runtime: runtimeB };
const welcomeB = buildWelcomeMessage();
const promptB = buildSystemPrompt();
assert(welcomeB.includes('v2.0.0'), 'welcome should reflect runtimeB version');
assert(welcomeB.includes('Phase 2'), 'welcome should reflect runtimeB phase');
assert(promptB.includes('v2.0.0 · Phase 2'), 'prompt should reflect runtimeB values');
assert(promptB.includes('INNOV-01 through INNOV-22'), 'prompt should reflect runtimeB innovation coverage');
assert(promptA !== promptB, 'prompt should change when runtime snapshot changes');

S.gov = null;
const welcomeFallback = buildWelcomeMessage();
const promptFallback = buildSystemPrompt();
assert(welcomeFallback.includes('snapshot unavailable'), 'welcome fallback should say snapshot unavailable');
assert(promptFallback.includes('snapshot unavailable'), 'prompt fallback should say snapshot unavailable');
`
].join('\n\n');

new Function(src)();
'''

    subprocess.run(['node', '-e', node_script], check=True, text=True)
