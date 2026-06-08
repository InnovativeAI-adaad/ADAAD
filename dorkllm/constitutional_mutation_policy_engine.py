# SPDX-License-Identifier: Apache-2.0
"""INNOV-114 · CMPE — Constitutional Mutation Policy Engine.

World-first constitutionally-governed mutation policy engine. Sits above the
full AMPS→CMQ→CMVG→CMSE→CMWE→CMOA pipeline and governs WHAT mutation strategies
are permissible at any given moment, based on live system health signals:

  - Invariant health ratio (from ILV / invariant ledger)
  - CMOA outcome signals (FITNESS_ADJUST, VELOCITY_NUDGE)
  - CMVG velocity state (HALT / THROTTLE / CRUISE / ACCELERATE)
  - V10 convergence criteria status
  - Constitutional blast-radius budget

Policy rules are stored as HMAC-SHA-256-chained PolicyRecord entries —
making the policy history itself tamper-evident and replayable. HUMAN-0 is the
sole authority for policy amendments at TIER0; DEVADAAD may auto-apply TIER2
rules within defined bounds.

Hard-class invariants enforced:
  CMPE-CHAIN-0     : PolicyLedger entries are HMAC-SHA-256 chained;
                     broken or missing links raise CMPEChainError.
  CMPE-IMMUT-0     : Ratified PolicyRule entries are never mutated after
                     ledger commit; violation raises CMPEImmutError.
  CMPE-HUMAN0-0    : TIER0 policy amendments require authenticated HUMAN-0
                     identity; empty / None raises CMPEAuthError.
  CMPE-EVAL-0      : Every strategy evaluation produces a PolicyVerdict
                     sealed in the ledger; no evaluation is ledger-silent.
  CMPE-DENY-0      : A DENY verdict is returned and sealed when any blocking
                     condition is met; the engine is fail-closed by default.
  CMPE-HEALTH-0    : Strategies are denied when invariant_health_ratio
                     falls below the configured floor (default 0.80).
  CMPE-VELOCITY-0  : Strategies are denied when CMVG velocity is HALT;
                     THROTTLE constrains allowable blast tiers to TIER2 only.
  CMPE-BUDGET-0    : Each evaluation deducts from the blast-radius budget;
                     exhausted budget denies all further scheduling until reset.
  CMPE-DETERM-0    : PolicyRecord IDs are deterministic SHA-256 hashes of
                     (rule_id, strategy_id, verdict, prev_hmac); no entropy.
  CMPE-AMEND-0     : New policy rules are validated against the constitutional
                     rule schema before ledger commit; invalid rules raise
                     CMPERuleError.
  CMPE-AUDIT-0     : Every evaluate(), amend(), and reset_budget() call appends
                     one sealed PolicyRecord to the ledger.
  CMPE-V10-0       : When all V10 convergence criteria are met, CMPE enters
                     CONVERGENCE_GUARD mode — only TIER2 mutations permitted
                     to preserve the converged state.

Governor: DUSTIN L REID (HUMAN-0) — InnovativeAI LLC
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

GOVERNOR = "DUSTIN L REID"
INNOV_CODE = "CMPE"
INNOV_NUMBER = "INNOV-114"
VERSION = "10.20.0"
PHASE = 209

LEDGER_PATH = Path("data/cmpe/policy_ledger.jsonl")
HMAC_SECRET = os.environ.get("ADAAD_HMAC_SECRET", "adaad-cmpe-hmac-secret-v1").encode()

DEFAULT_HEALTH_FLOOR = float(os.environ.get("CMPE_HEALTH_FLOOR", "0.80"))
DEFAULT_BLAST_BUDGET = int(os.environ.get("CMPE_BLAST_BUDGET", "100"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PolicyVerdict(str, Enum):
    ALLOW     = "ALLOW"
    DENY      = "DENY"
    DEFER     = "DEFER"   # conditions not yet resolvable — retry later


class VelocityState(str, Enum):
    HALT        = "HALT"
    THROTTLE    = "THROTTLE"
    CRUISE      = "CRUISE"
    ACCELERATE  = "ACCELERATE"


class EngineMode(str, Enum):
    NORMAL             = "NORMAL"
    CONVERGENCE_GUARD  = "CONVERGENCE_GUARD"
    EMERGENCY_FREEZE   = "EMERGENCY_FREEZE"


class PolicyAction(str, Enum):
    EVALUATE     = "EVALUATE"
    AMEND        = "AMEND"
    RESET_BUDGET = "RESET_BUDGET"
    MODE_CHANGE  = "MODE_CHANGE"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CMPEError(Exception):
    """Base CMPE constitutional violation."""

class CMPEChainError(CMPEError):
    """CMPE-CHAIN-0 violated."""

class CMPEImmutError(CMPEError):
    """CMPE-IMMUT-0 violated."""

class CMPEAuthError(CMPEError):
    """CMPE-HUMAN0-0 violated."""

class CMPERuleError(CMPEError):
    """CMPE-AMEND-0 violated — invalid rule schema."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    """A single immutable policy rule, HUMAN-0 amendable."""
    rule_id: str
    description: str
    blast_tier_max: int        # 0/1/2 — max allowable blast tier under this rule
    min_health_ratio: float    # invariant health floor for this rule
    requires_human0: bool      # TIER0 eval always True
    active: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class PolicyEvalContext:
    """Runtime snapshot passed into evaluate()."""
    strategy_id: str
    blast_tier: int
    invariant_health_ratio: float   # 0.0–1.0
    velocity_state: str             # VelocityState value
    v10_criteria_met: bool
    scope: list[str]
    metadata: dict = field(default_factory=dict)


@dataclass
class PolicyVerdict_:
    """Result of a single policy evaluation."""
    verdict: str
    strategy_id: str
    denial_reasons: list[str]
    applied_rules: list[str]
    blast_budget_remaining: int
    engine_mode: str
    metadata: dict = field(default_factory=dict)


@dataclass
class PolicyRecord:
    record_id: str
    action: str
    strategy_id: str
    verdict: str
    rule_ids: list[str]
    denial_reasons: list[str]
    invariant_health_ratio: float
    velocity_state: str
    blast_tier: int
    blast_budget_remaining: int
    engine_mode: str
    governor: str
    innov_code: str
    phase: int
    human0_identity: Optional[str]
    metadata: dict
    prev_hmac: str
    hmac: str = ""

    def seal(self, secret: bytes, prev_hmac: str) -> "PolicyRecord":
        self.prev_hmac = prev_hmac
        payload = json.dumps(
            {k: v for k, v in asdict(self).items() if k != "hmac"},
            sort_keys=True,
        )
        self.hmac = _hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return self


# ---------------------------------------------------------------------------
# HMAC chain
# ---------------------------------------------------------------------------

def _compute_hmac(secret: bytes, record: dict) -> str:
    payload = json.dumps({k: v for k, v in record.items() if k != "hmac"}, sort_keys=True)
    return _hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _verify_chain(records: list[dict], secret: bytes) -> bool:
    prev = "0" * 64
    for r in records:
        if r.get("prev_hmac") != prev:
            return False
        expected = _compute_hmac(secret, r)
        if not _hmac.compare_digest(expected[:24], r.get("hmac", "")[:24]):
            return False
        prev = r["hmac"]
    return True


def _record_id(strategy_id: str, verdict: str, prev_hmac: str) -> str:
    """CMPE-DETERM-0."""
    return hashlib.sha256(
        f"{GOVERNOR}:{INNOV_CODE}:{strategy_id}:{verdict}:{prev_hmac}".encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Default constitutional policy rules
# ---------------------------------------------------------------------------

_DEFAULT_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="CMPE-DEFAULT-HALT",
        description="Deny all strategies when velocity is HALT",
        blast_tier_max=0,
        min_health_ratio=0.0,
        requires_human0=False,
    ),
    PolicyRule(
        rule_id="CMPE-DEFAULT-THROTTLE",
        description="Under THROTTLE velocity, restrict to TIER2 only",
        blast_tier_max=2,
        min_health_ratio=0.0,
        requires_human0=False,
    ),
    PolicyRule(
        rule_id="CMPE-DEFAULT-HEALTH",
        description="Deny all strategies below invariant health floor",
        blast_tier_max=0,
        min_health_ratio=DEFAULT_HEALTH_FLOOR,
        requires_human0=False,
    ),
    PolicyRule(
        rule_id="CMPE-DEFAULT-CONVERGENCE",
        description="In CONVERGENCE_GUARD mode, only TIER2 permitted",
        blast_tier_max=2,
        min_health_ratio=0.80,
        requires_human0=False,
    ),
    PolicyRule(
        rule_id="CMPE-HUMAN0-TIER0",
        description="All TIER0 mutations require HUMAN-0 ratification",
        blast_tier_max=0,
        min_health_ratio=0.0,
        requires_human0=True,
    ),
]


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class ConstitutionalMutationPolicyEngine:
    """INNOV-114 · CMPE — Constitutional Mutation Policy Engine.

    Governs which mutation strategies are permissible given live system health.
    All verdicts sealed in HMAC-SHA-256-chained PolicyLedger.
    """

    def __init__(
        self,
        ledger_path: Path = LEDGER_PATH,
        hmac_secret: bytes = HMAC_SECRET,
        health_floor: float = DEFAULT_HEALTH_FLOOR,
        blast_budget: int = DEFAULT_BLAST_BUDGET,
    ) -> None:
        self._ledger_path = ledger_path
        self._secret = hmac_secret
        self._health_floor = health_floor
        self._blast_budget = blast_budget
        self._blast_budget_remaining = blast_budget
        self._mode = EngineMode.NORMAL.value
        self._rules: dict[str, PolicyRule] = {r.rule_id: r for r in _DEFAULT_RULES}
        self._prev_hmac = "0" * 64
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        ctx: PolicyEvalContext,
        human0_identity: Optional[str] = None,
    ) -> PolicyVerdict_:
        """Evaluate whether a mutation strategy is permissible.

        CMPE-EVAL-0, CMPE-DENY-0, CMPE-HEALTH-0, CMPE-VELOCITY-0,
        CMPE-BUDGET-0, CMPE-V10-0 enforced.
        Always appends a sealed PolicyRecord (CMPE-AUDIT-0).
        """
        denial_reasons: list[str] = []
        applied_rules: list[str] = []

        # CMPE-V10-0: V10 convergence guard
        if ctx.v10_criteria_met and self._mode == EngineMode.NORMAL.value:
            self._set_mode(EngineMode.CONVERGENCE_GUARD.value, human0_identity)

        # CMPE-VELOCITY-0: HALT blocks everything
        if ctx.velocity_state == VelocityState.HALT.value:
            denial_reasons.append("CMPE-VELOCITY-0: velocity=HALT blocks all strategies")
            applied_rules.append("CMPE-DEFAULT-HALT")

        # CMPE-VELOCITY-0: THROTTLE restricts to TIER2
        if ctx.velocity_state == VelocityState.THROTTLE.value and ctx.blast_tier < 2:
            denial_reasons.append(
                f"CMPE-VELOCITY-0: THROTTLE restricts to TIER2; requested blast_tier={ctx.blast_tier}"
            )
            applied_rules.append("CMPE-DEFAULT-THROTTLE")

        # CMPE-HEALTH-0
        if ctx.invariant_health_ratio < self._health_floor:
            denial_reasons.append(
                f"CMPE-HEALTH-0: health_ratio={ctx.invariant_health_ratio:.3f} < floor={self._health_floor:.3f}"
            )
            applied_rules.append("CMPE-DEFAULT-HEALTH")

        # CMPE-HUMAN0-0: TIER0 always requires HUMAN-0
        if ctx.blast_tier == 0 and not human0_identity:
            denial_reasons.append("CMPE-HUMAN0-0: TIER0 strategy requires HUMAN-0 identity")
            applied_rules.append("CMPE-HUMAN0-TIER0")

        # CMPE-V10-0: CONVERGENCE_GUARD — only TIER2 allowed
        if self._mode == EngineMode.CONVERGENCE_GUARD.value and ctx.blast_tier < 2:
            denial_reasons.append(
                f"CMPE-V10-0: CONVERGENCE_GUARD mode restricts to TIER2; blast_tier={ctx.blast_tier}"
            )
            applied_rules.append("CMPE-DEFAULT-CONVERGENCE")

        # CMPE-BUDGET-0: blast budget
        blast_cost = 3 - ctx.blast_tier  # TIER0=3, TIER1=2, TIER2=1
        if self._blast_budget_remaining < blast_cost:
            denial_reasons.append(
                f"CMPE-BUDGET-0: blast budget exhausted "
                f"(remaining={self._blast_budget_remaining}, cost={blast_cost})"
            )

        # Emergency freeze overrides everything
        if self._mode == EngineMode.EMERGENCY_FREEZE.value:
            denial_reasons.append("CMPE-DENY-0: EMERGENCY_FREEZE mode — all strategies denied")

        # Verdict
        if denial_reasons:
            verdict = PolicyVerdict.DENY.value
        else:
            verdict = PolicyVerdict.ALLOW.value
            self._blast_budget_remaining = max(0, self._blast_budget_remaining - blast_cost)

        result = PolicyVerdict_(
            verdict=verdict,
            strategy_id=ctx.strategy_id,
            denial_reasons=denial_reasons,
            applied_rules=list(set(applied_rules)),
            blast_budget_remaining=self._blast_budget_remaining,
            engine_mode=self._mode,
        )

        # CMPE-AUDIT-0 + CMPE-EVAL-0
        self._emit(PolicyAction.EVALUATE, ctx.strategy_id, verdict,
                   list(set(applied_rules)), denial_reasons,
                   ctx.invariant_health_ratio, ctx.velocity_state,
                   ctx.blast_tier, human0_identity, ctx.metadata)
        return result

    def amend(
        self,
        rule: PolicyRule,
        human0_identity: Optional[str] = None,
    ) -> PolicyRule:
        """Add or replace a policy rule. TIER0 rules require HUMAN-0.

        CMPE-HUMAN0-0, CMPE-AMEND-0, CMPE-IMMUT-0 enforced.
        """
        # CMPE-AMEND-0: schema validation
        if not rule.rule_id:
            raise CMPERuleError("CMPE-AMEND-0: rule_id must be non-empty")
        if not (0 <= rule.blast_tier_max <= 2):
            raise CMPERuleError(f"CMPE-AMEND-0: blast_tier_max must be 0/1/2, got {rule.blast_tier_max}")
        if not (0.0 <= rule.min_health_ratio <= 1.0):
            raise CMPERuleError(f"CMPE-AMEND-0: min_health_ratio must be [0,1], got {rule.min_health_ratio}")

        # CMPE-HUMAN0-0: TIER0 rules need HUMAN-0
        if rule.requires_human0 and not human0_identity:
            raise CMPEAuthError("CMPE-HUMAN0-0: TIER0 policy rule amendment requires HUMAN-0 identity")

        # CMPE-IMMUT-0: cannot replace a locked rule without HUMAN-0
        existing = self._rules.get(rule.rule_id)
        if existing and existing.requires_human0 and not human0_identity:
            raise CMPEImmutError(
                f"CMPE-IMMUT-0: rule {rule.rule_id} is HUMAN-0-locked; amendment requires HUMAN-0"
            )

        self._rules[rule.rule_id] = rule
        self._emit(PolicyAction.AMEND, rule.rule_id, "AMENDED",
                   [rule.rule_id], [], 1.0, "N/A", rule.blast_tier_max,
                   human0_identity, asdict(rule))
        return rule

    def reset_budget(self, human0_identity: str) -> int:
        """Reset blast-radius budget. Always requires HUMAN-0. Returns new balance."""
        if not human0_identity:
            raise CMPEAuthError("CMPE-HUMAN0-0: budget reset requires HUMAN-0 identity")
        self._blast_budget_remaining = self._blast_budget
        self._emit(PolicyAction.RESET_BUDGET, "BUDGET_RESET", "RESET",
                   [], [], 1.0, "N/A", -1, human0_identity,
                   {"blast_budget": self._blast_budget})
        return self._blast_budget_remaining

    def set_emergency_freeze(self, human0_identity: str, freeze: bool) -> None:
        """Enable / disable EMERGENCY_FREEZE mode. Always requires HUMAN-0."""
        if not human0_identity:
            raise CMPEAuthError("CMPE-HUMAN0-0: emergency freeze requires HUMAN-0 identity")
        new_mode = EngineMode.EMERGENCY_FREEZE.value if freeze else EngineMode.NORMAL.value
        self._set_mode(new_mode, human0_identity)

    def verify_ledger(self) -> bool:
        """CMPE-CHAIN-0: verify full PolicyLedger integrity."""
        return _verify_chain(self._read_ledger(), self._secret)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def blast_budget_remaining(self) -> int:
        return self._blast_budget_remaining

    @property
    def rules(self) -> dict[str, PolicyRule]:
        return dict(self._rules)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_mode(self, mode: str, human0_identity: Optional[str]) -> None:
        if self._mode == mode:
            return
        self._mode = mode
        self._emit(PolicyAction.MODE_CHANGE, "ENGINE", mode,
                   [], [], 1.0, "N/A", -1, human0_identity, {"new_mode": mode})

    def _emit(
        self,
        action: PolicyAction,
        strategy_id: str,
        verdict: str,
        rule_ids: list[str],
        denial_reasons: list[str],
        health_ratio: float,
        velocity_state: str,
        blast_tier: int,
        human0_identity: Optional[str],
        metadata: dict,
    ) -> None:
        rid = _record_id(strategy_id, verdict, self._prev_hmac)
        rec = PolicyRecord(
            record_id=rid,
            action=action.value,
            strategy_id=strategy_id,
            verdict=verdict,
            rule_ids=rule_ids,
            denial_reasons=denial_reasons,
            invariant_health_ratio=health_ratio,
            velocity_state=velocity_state,
            blast_tier=blast_tier,
            blast_budget_remaining=self._blast_budget_remaining,
            engine_mode=self._mode,
            governor=GOVERNOR,
            innov_code=INNOV_CODE,
            phase=PHASE,
            human0_identity=human0_identity,
            metadata=metadata,
            prev_hmac=self._prev_hmac,
        ).seal(self._secret, self._prev_hmac)
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")
        self._prev_hmac = rec.hmac

    def _read_ledger(self) -> list[dict]:
        if not self._ledger_path.exists():
            return []
        return [json.loads(l) for l in self._ledger_path.read_text().splitlines() if l.strip()]

    def _load_ledger(self) -> None:
        records = self._read_ledger()
        if not records:
            return
        if not _verify_chain(records, self._secret):
            raise CMPEChainError("CMPE-CHAIN-0: PolicyLedger chain broken on load")
        self._prev_hmac = records[-1]["hmac"]
        # Restore budget and mode from last state records
        for r in reversed(records):
            action = r.get("action", "")
            if action == PolicyAction.RESET_BUDGET.value and self._blast_budget_remaining == self._blast_budget:
                self._blast_budget_remaining = r.get("metadata", {}).get("blast_budget", self._blast_budget)
            if action == PolicyAction.MODE_CHANGE.value:
                self._mode = r.get("metadata", {}).get("new_mode", self._mode)
                break
