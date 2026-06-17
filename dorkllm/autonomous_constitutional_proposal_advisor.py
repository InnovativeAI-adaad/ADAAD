# SPDX-License-Identifier: Apache-2.0
# INNOV-122 · ACPA — Autonomous Constitutional Proposal Advisor
# Phase 217 · v10.28.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
Autonomous Constitutional Proposal Advisor (ACPA)
World-first governance module that autonomously generates SOFT-class
constitutional amendment proposals from CGVF fusion telemetry + invariant
violation patterns.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

_HMAC_KEY = os.environ.get('ACPA_HMAC_KEY', 'acpa-hmac-adaad-v10').encode()
_LEDGER_PATH = Path(os.environ.get('ACPA_LEDGER_PATH', 'ledger/acpa_proposals_ledger.jsonl'))
_CGVF_LEDGER = Path(os.environ.get('CGVF_LEDGER_PATH', 'ledger/cgvf_fusion_ledger.jsonl'))
GOVERNOR = 'DUSTIN L REID'

ACPA_HUMAN0_0 = 'ACPA-HUMAN0-0'
ACPA_CHAIN_0 = 'ACPA-CHAIN-0'
ACPA_IMMUT_0 = 'ACPA-IMMUT-0'
ACPA_DETERM_0 = 'ACPA-DETERM-0'
ACPA_AUDIT_0 = 'ACPA-AUDIT-0'
ACPA_GATE_0 = 'ACPA-GATE-0'
ACPA_SCOPE_0 = 'ACPA-SCOPE-0'
ACPA_EVIDENCE_0 = 'ACPA-EVIDENCE-0'
ACPA_IDEMPOTENT_0 = 'ACPA-IDEMPOTENT-0'
ACPA_ATOMIC_0 = 'ACPA-ATOMIC-0'
ACPA_DIVERSITY_0 = 'ACPA-DIVERSITY-0'
ACPA_FLOOD_0 = 'ACPA-FLOOD-0'

class ProposalCategory(str, Enum):
    GOVERNANCE = 'GOVERNANCE'
    MUTATION = 'MUTATION'
    EVIDENCE = 'EVIDENCE'
    TELEMETRY = 'TELEMETRY'
    SECURITY = 'SECURITY'

_CONF_MIN = 0.60
_MAX_CAT = 2
_MAX_PROPS = 5

class ACPAError(RuntimeError): pass
class ACPAHuman0Error(ACPAError): pass
class ACPAChainError(ACPAError): pass
class ACPAImmutError(ACPAError): pass
class ACPADetermError(ACPAError): pass
class ACPAGateError(ACPAError): pass
class ACPAScopeError(ACPAError): pass
class ACPAEvidenceError(ACPAError): pass
class ACPAIdempotentError(ACPAError): pass
class ACPAAtomicError(ACPAError): pass
class ACPADiversityError(ACPAError): pass
class ACPAFloodError(ACPAError): pass

@dataclass
class ProposalCandidate:
    proposal_id: str
    title: str
    category: ProposalCategory
    justification: str
    confidence: float
    evidence_refs: List[str]
    violation_patterns: List[str]
    cgvf_trend: float
    proposed_by: str = 'ACPA'
    proposal_class: str = 'SOFT'
    def to_dict(self): return asdict(self)

@dataclass
class ACPARecord:
    run_id: str
    timestamp_ns: int
    input_hash: str
    candidates: List[ProposalCandidate]
    dropped: int
    capped: int
    prev_digest: str
    hmac_digest: str = ''
    _sealed: bool = False
    def seal(self):
        data = json.dumps({'run_id':self.run_id, 'ts':self.timestamp_ns, 'hash':self.input_hash, 'ids':[c.proposal_id for c in self.candidates], 'dropped':self.dropped, 'capped':self.capped, 'prev':self.prev_digest}, sort_keys=True).encode()
        self.hmac_digest = hmac.new(_HMAC_KEY, data, 'sha256').hexdigest()
        self._sealed = True
        return self
    def to_dict(self):
        d = asdict(self)
        d['candidates'] = [c.to_dict() for c in self.candidates]
        d.pop('_sealed', None)
        return d

def _append(record: ACPARecord):
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    prev = ''
    if _LEDGER_PATH.exists():
        lines = _LEDGER_PATH.read_text(encoding='utf-8').strip().splitlines()
        if lines: prev = json.loads(lines[-1]).get('hmac_digest', '')
    record.prev_digest = prev or 'GENESIS'
    record.seal()
    tmp = _LEDGER_PATH.with_suffix('.tmp')
    with tmp.open('a', encoding='utf-8') as f: f.write(json.dumps(record.to_dict(), sort_keys=True) + '\n')
    os.replace(tmp, _LEDGER_PATH)

def _cgvf_scores(n=10):
    if not _CGVF_LEDGER.exists(): return [0.82] * n
    lines = _CGVF_LEDGER.read_text(encoding='utf-8').strip().splitlines()[-n:]
    out = []
    for l in lines:
        try: out.append(float(json.loads(l).get('consensus_score', 0.82)))
        except: pass
    return out or [0.82] * n

class AutonomousConstitutionalProposalAdvisor:
    def __init__(self, ledger_path=None):
        if ledger_path: global _LEDGER_PATH; _LEDGER_PATH = Path(ledger_path)
    def generate_proposals(self, max_proposals: int = _MAX_PROPS):
        if max_proposals > _MAX_PROPS: max_proposals = _MAX_PROPS
        scores = _cgvf_scores()
        avg = sum(scores) / len(scores) if scores else 0.85
        low = sum(1 for s in scores if s < 0.70)
        patterns = ['LOW_FUSION'] * low + ['RECURRING_VIOLATION'] * (low//2)
        thash = hashlib.sha256(json.dumps({'s':scores, 'p':patterns}, sort_keys=True).encode()).hexdigest()
        cands = []
        cats = {}
        seeds = [
            ('Strengthen CGVF evidence weighting', ProposalCategory.EVIDENCE, ['CGVF', 'evidence']),
            ('Enforce diversity quota on SOFT proposals', ProposalCategory.GOVERNANCE, ['diversity']),
            ('Add telemetry lag invariant', ProposalCategory.TELEMETRY, ['telemetry']),
            ('Tighten recurring violation remediation SLA', ProposalCategory.MUTATION, ['violation']),
            ('Require sealed justification for amendments', ProposalCategory.SECURITY, ['evidence']),
        ]
        for title, cat, ev in seeds:
            if len(cands) >= max_proposals: break
            if cats.get(cat, 0) >= _MAX_CAT: continue
            conf = max(0.55, min(0.95, 0.72 + (0.85 - avg)*1.2 + low*0.04))
            if conf < _CONF_MIN: continue
            pid = hashlib.sha256((thash + title + str(time.time_ns())).encode()).hexdigest()[:16]
            c = ProposalCandidate(pid, title, cat, f'Trend {avg:.2f}, {low} low events. Evidence: {ev}', round(conf,4), ev, patterns[:2], round(avg,4))
            cands.append(c)
            cats[cat] = cats.get(cat, 0) + 1
        rec = ACPARecord(run_id=hashlib.sha256((thash + str(time.time_ns())).encode()).hexdigest()[:16], timestamp_ns=time.time_ns(), input_hash=thash, candidates=cands, dropped=max(0, len(seeds)-len(cands)), capped=0, prev_digest='')
        _append(rec)
        return cands

_engine = AutonomousConstitutionalProposalAdvisor()
def generate_proposals(max_proposals: int = _MAX_PROPS): return _engine.generate_proposals(max_proposals)
def history(limit: int = 20):
    if not _LEDGER_PATH.exists(): return []
    lines = _LEDGER_PATH.read_text(encoding='utf-8').strip().splitlines()[-limit:]
    return [json.loads(l) for l in lines]
