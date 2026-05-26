"""
INNOV-101 CMIM - Constitutional Mutation Intent Model
Phase 196 - v10.7.0 - InnovativeAI LLC - DUSTIN L REID (HUMAN-0)

World-first: requires every mutation to carry a formal machine-readable intent declaration
before CEL entry, then verifies post-CEL that actual behavior matched declared intent.
Intent-behavior divergence triggers automatic rollback independent of test passage.

Hard-class invariants:
  CMIM-INTENT-0, CMIM-COMPLETE-0, CMIM-TRACE-0, CMIM-BLAST-0, CMIM-SCOPE-0,
  CMIM-AUTHOR-0, CMIM-HUMAN0-0, CMIM-ROLLBACK-0, CMIM-CHAIN-0, CMIM-DETERM-0
"""
from __future__ import annotations
import hashlib, hmac as _hmac, json, os, time, uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CMIM"
INNOV_NUMBER = "INNOV-101"
VERSION = "10.7.0"
PHASE = 196
LEDGER_PATH = Path("data/cmim/intent_ledger.jsonl")
HMAC_SECRET = os.environ.get("ADAAD_HMAC_SECRET", "adaad-cmim-hmac-secret-v1").encode()
VALID_AGENTS = {"ArchitectAgent", "MutationAgent", "DreamAgent", "BeastAgent", "DEVADAAD"}
VALID_BLAST_TIERS = {0, 1, 2}
GOVERNANCE_OBJECTIVES = {
    "CEL_INTEGRITY", "INVARIANT_ENFORCEMENT", "LEDGER_IMMUTABILITY",
    "HUMAN0_GATE", "DETERMINISM", "REPLAY_VERIFIABILITY", "MUTATION_SAFETY",
    "CONSTITUTIONAL_COMPLIANCE", "AUDIT_COMPLETENESS", "PROVENANCE_TRACING",
    "AGENT_GOVERNANCE", "BLAST_RADIUS_CONTROL", "ROLLBACK_CAPABILITY",
    "INNOVATION_DELIVERY", "CONSTITUTIONAL_EVOLUTION",
}

class CMIMError(Exception): pass
class CMIMIntentIncomplete(CMIMError): pass
class CMIMBlastMismatch(CMIMError): pass
class CMIMScopeViolation(CMIMError): pass
class CMIMIntentTraceFail(CMIMError): pass
class CMIMAuthorInvalid(CMIMError): pass
class CMIMHuman0Required(CMIMError): pass
class CMIMRollbackTriggered(CMIMError): pass
class CMIMChainBroken(CMIMError): pass
class CMIMDeterminismViolation(CMIMError): pass

@dataclass
class MutationIntentDeclaration:
    mutation_id: str
    goal_statement: str
    expected_invariants_touched: list
    blast_radius_tier: int
    ratification_scope: str
    author_agent: str
    target_cel_stages: list
    governance_objectives: list
    declared_at: float = field(default_factory=time.time)
    declaration_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    REQUIRED_FIELDS = [
        "mutation_id","goal_statement","expected_invariants_touched",
        "blast_radius_tier","ratification_scope","author_agent",
        "target_cel_stages","governance_objectives",
    ]

    def validate_completeness(self):
        for f in self.REQUIRED_FIELDS:
            v = getattr(self, f, None)
            if v is None or v == "" or v == []:
                raise CMIMIntentIncomplete(
                    f"CMIM-COMPLETE-0: Required field '{f}' absent. Mutation {self.mutation_id} rejected.")

    def fingerprint(self) -> str:
        canonical = json.dumps({
            "mutation_id": self.mutation_id,
            "goal_statement": self.goal_statement,
            "expected_invariants_touched": sorted(self.expected_invariants_touched),
            "blast_radius_tier": self.blast_radius_tier,
            "ratification_scope": self.ratification_scope,
            "author_agent": self.author_agent,
            "target_cel_stages": sorted(self.target_cel_stages),
            "governance_objectives": sorted(self.governance_objectives),
        }, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

@dataclass
class IntentVerificationReport:
    declaration_id: str
    mutation_id: str
    declared_invariants: list
    actual_invariants_triggered: list
    declared_blast_tier: int
    actual_blast_tier: int
    declared_objectives: list
    undeclared_invariants: list
    skipped_declared_invariants: list
    blast_mismatch: bool
    intent_behavior_divergence: bool
    rollback_required: bool
    verdict: str
    verified_at: float = field(default_factory=time.time)
    verification_id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class IntentLedgerEntry:
    entry_id: str
    entry_type: str
    mutation_id: str
    declaration_id: str
    payload: dict
    phase: int
    version: str
    governor: str
    prev_hash: str
    entry_hash: str = ""
    recorded_at: float = field(default_factory=time.time)

    def compute_hash(self) -> str:
        canonical = json.dumps({
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "mutation_id": self.mutation_id,
            "declaration_id": self.declaration_id,
            "prev_hash": self.prev_hash,
            "recorded_at": self.recorded_at,
        }, sort_keys=True)
        return _hmac.new(HMAC_SECRET, canonical.encode(), hashlib.sha256).hexdigest()

class ConstitutionalMutationIntentModel:
    """CMIM Engine - Constitutional Mutation Intent Model (INNOV-101)."""

    def __init__(self, ledger_path=LEDGER_PATH):
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._declarations = {}
        self._prev_hash = self._load_chain_tip()

    def _load_chain_tip(self) -> str:
        if not self.ledger_path.exists():
            return "GENESIS"
        lines = self.ledger_path.read_text().strip().splitlines()
        if not lines:
            return "GENESIS"
        return json.loads(lines[-1]).get("entry_hash", "GENESIS")

    def _append_ledger(self, entry: IntentLedgerEntry):
        entry.entry_hash = entry.compute_hash()
        self._prev_hash = entry.entry_hash
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def verify_chain_integrity(self) -> dict:
        if not self.ledger_path.exists():
            return {"status": "EMPTY", "entries": 0, "broken_at": None}
        entries = [json.loads(l) for l in self.ledger_path.read_text().strip().splitlines() if l]
        prev = "GENESIS"
        for i, e in enumerate(entries):
            canonical = json.dumps({
                "entry_id": e["entry_id"], "entry_type": e["entry_type"],
                "mutation_id": e["mutation_id"], "declaration_id": e["declaration_id"],
                "prev_hash": e["prev_hash"], "recorded_at": e["recorded_at"],
            }, sort_keys=True)
            expected = _hmac.new(HMAC_SECRET, canonical.encode(), hashlib.sha256).hexdigest()
            if e.get("entry_hash") != expected:
                raise CMIMChainBroken(f"CMIM-CHAIN-0: Chain broken at entry {i}")
            if e["prev_hash"] != prev:
                raise CMIMChainBroken(f"CMIM-CHAIN-0: prev_hash mismatch at entry {i}")
            prev = e["entry_hash"]
        return {"status": "INTACT", "entries": len(entries), "tip": prev[:24] if prev != "GENESIS" else "GENESIS"}

    def declare_intent(self, declaration: MutationIntentDeclaration, human0_countersig=None) -> str:
        if declaration is None:
            raise CMIMIntentIncomplete("CMIM-INTENT-0: No intent declaration provided.")
        declaration.validate_completeness()
        if declaration.author_agent not in VALID_AGENTS:
            raise CMIMAuthorInvalid(f"CMIM-AUTHOR-0: '{declaration.author_agent}' not in ratified agent set.")
        if declaration.blast_radius_tier not in VALID_BLAST_TIERS:
            raise CMIMBlastMismatch(f"CMIM-BLAST-0: blast_radius_tier={declaration.blast_radius_tier} invalid.")
        if not declaration.governance_objectives:
            raise CMIMIntentTraceFail("CMIM-TRACE-0: governance_objectives empty.")
        unrecognized = set(declaration.governance_objectives) - GOVERNANCE_OBJECTIVES
        if unrecognized:
            raise CMIMIntentTraceFail(f"CMIM-TRACE-0: Unrecognized objectives: {unrecognized}")
        if declaration.blast_radius_tier == 0 and not human0_countersig:
            raise CMIMHuman0Required("CMIM-HUMAN0-0: Tier 0 requires HUMAN-0 countersignature.")
        fingerprint = declaration.fingerprint()
        self._declarations[declaration.declaration_id] = declaration
        entry = IntentLedgerEntry(
            entry_id=str(uuid.uuid4()), entry_type="DECLARATION",
            mutation_id=declaration.mutation_id, declaration_id=declaration.declaration_id,
            payload={"fingerprint": fingerprint, "blast_radius_tier": declaration.blast_radius_tier,
                     "author_agent": declaration.author_agent,
                     "governance_objectives": declaration.governance_objectives,
                     "expected_invariants_touched": declaration.expected_invariants_touched,
                     "human0_countersig_present": human0_countersig is not None},
            phase=PHASE, version=VERSION, governor=GOVERNOR, prev_hash=self._prev_hash)
        self._append_ledger(entry)
        return declaration.declaration_id

    def verify_intent(self, declaration_id: str, actual_invariants_triggered: list, actual_blast_tier: int) -> IntentVerificationReport:
        if declaration_id not in self._declarations:
            raise CMIMIntentIncomplete(f"CMIM-INTENT-0: No declaration found for id={declaration_id}")
        decl = self._declarations[declaration_id]
        declared_set = set(decl.expected_invariants_touched)
        actual_set = set(actual_invariants_triggered)
        undeclared = list(actual_set - declared_set)
        skipped = list(declared_set - actual_set)
        blast_mismatch = (actual_blast_tier != decl.blast_radius_tier)
        divergence = bool(undeclared or skipped or blast_mismatch)
        verdict = "ROLLBACK" if divergence else "PASS"
        report = IntentVerificationReport(
            declaration_id=declaration_id, mutation_id=decl.mutation_id,
            declared_invariants=decl.expected_invariants_touched,
            actual_invariants_triggered=actual_invariants_triggered,
            declared_blast_tier=decl.blast_radius_tier, actual_blast_tier=actual_blast_tier,
            declared_objectives=decl.governance_objectives,
            undeclared_invariants=undeclared, skipped_declared_invariants=skipped,
            blast_mismatch=blast_mismatch, intent_behavior_divergence=divergence,
            rollback_required=divergence, verdict=verdict)
        entry = IntentLedgerEntry(
            entry_id=str(uuid.uuid4()), entry_type="VERIFICATION" if not divergence else "ROLLBACK",
            mutation_id=decl.mutation_id, declaration_id=declaration_id,
            payload={"verdict": verdict, "undeclared_invariants": undeclared,
                     "skipped_declared_invariants": skipped, "blast_mismatch": blast_mismatch,
                     "rollback_required": divergence},
            phase=PHASE, version=VERSION, governor=GOVERNOR, prev_hash=self._prev_hash)
        self._append_ledger(entry)
        if divergence:
            reasons = []
            if undeclared: reasons.append(f"undeclared invariants: {undeclared}")
            if skipped: reasons.append(f"skipped declared: {skipped}")
            if blast_mismatch: reasons.append(f"blast mismatch declared={decl.blast_radius_tier} actual={actual_blast_tier}")
            raise CMIMRollbackTriggered(
                f"CMIM-ROLLBACK-0: Intent-behavior divergence for {decl.mutation_id}. "
                f"Rollback mandatory. Reasons: {'; '.join(reasons)}")
        return report

    def get_declaration(self, declaration_id: str):
        d = self._declarations.get(declaration_id)
        return asdict(d) if d else None

    def get_ledger_summary(self) -> dict:
        if not self.ledger_path.exists():
            return {"entries": 0, "declarations": 0, "verifications": 0, "rollbacks": 0}
        entries = [json.loads(l) for l in self.ledger_path.read_text().strip().splitlines() if l]
        return {
            "entries": len(entries),
            "declarations": sum(1 for e in entries if e["entry_type"] == "DECLARATION"),
            "verifications": sum(1 for e in entries if e["entry_type"] == "VERIFICATION"),
            "rollbacks": sum(1 for e in entries if e["entry_type"] == "ROLLBACK"),
            "chain_tip": self._prev_hash[:24],
        }

    def export_ledger(self) -> list:
        if not self.ledger_path.exists():
            return []
        return [json.loads(l) for l in self.ledger_path.read_text().strip().splitlines() if l]

_engine = None
def get_cmim_engine() -> ConstitutionalMutationIntentModel:
    global _engine
    if _engine is None:
        _engine = ConstitutionalMutationIntentModel()
    return _engine
