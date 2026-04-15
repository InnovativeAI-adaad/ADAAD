# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import subprocess


def test_dork_html_uses_console_contract_endpoint() -> None:
    node_script = r'''
const fs = require('fs');
const html = fs.readFileSync('ui/dork.html', 'utf8');
if (!html.includes("const DORK_CONSOLE_ROUTE_ENDPOINT = '/api/dork/console/route';")) {
  throw new Error('missing contract endpoint constant');
}
if (!html.includes("fetch(DORK_CONSOLE_ROUTE_ENDPOINT")) {
  throw new Error('missing fetch call to contract endpoint');
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
  extractFunction('buildConsoleMarkdown'),
  extractFunction('buildConsoleErrorMarkdown'),
  `
const approved = buildConsoleMarkdown({
  outcome: 'approved',
  outcome_reason: 'advisory_clear',
  bundle: { intent: 'show_gate_status', summary: 'All good' },
});
if (!approved.includes('### APPROVED')) throw new Error('approved heading missing');
if (!approved.includes('show_gate_status')) throw new Error('approved intent missing');

const blocked = buildConsoleErrorMarkdown(409, {
  detail: {
    error_code: 'governance_blocked',
    detail: { reason: 'mutation_blocked_fail_closed', intent: 'prepare_mutation_review' },
  },
});
if (!blocked.includes('### BLOCKED')) throw new Error('blocked heading missing');
if (!blocked.includes('mutation_blocked_fail_closed')) throw new Error('blocked reason missing');

const validation = buildConsoleErrorMarkdown(422, {});
if (!validation.includes('### VALIDATION ERROR')) throw new Error('validation heading missing');
`
].join('\n\n');

new Function(src)();
'''
    subprocess.run(["node", "-e", node_script], check=True, text=True)
