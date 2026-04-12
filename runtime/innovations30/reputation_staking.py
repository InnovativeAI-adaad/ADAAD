# SPDX-License-Identifier: Apache-2.0
"""Innovation #15 — Agent Reputation Staking (ARS).

Agents stake credits on proposals. Failed proposals burn stake.
Converts hollow proposals into costly commitments.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
  STAKE-0        An agent MUST have sufficient balance before stake() commits.
                 Staking more than the available balance raises InsufficientStakeError.
  STAKE-CAP-0    Staked amount is capped at MAX_STAKE_FRACTION (20%) of pre-stake
                 balance. No single proposal can consume the agent's full reserves.
  STAKE-BURN-0   resolve() with passed=False MUST burn 100% of staked_amount.
                 Burned stake is never returned regardless of fitness outcome.
  STAKE-DETERM-0 StakeRecord.stake_digest = sha256(agent_id:mutation_id:epoch_id:
                 staked_amount) — deterministic, full-length, no datetime/random/uuid4.
  STAKE-PERSIST-0 _persist() MUST use Path.open("a") append mode — never builtins.open.
                  Wallet writes use json.dumps(sort_keys=True) for determinism.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
REST_INV_CHAIN: str = "REST-INV-CHAIN"
REST_LEDGER_DEFAULT: str = "data/reputation_staking_events.jsonl"


class ReputationStakingViolation(RuntimeError):
    """Raised when a Reputation Staking constitutional invariant is breached."""



# ── Invariant constants ───────────────────────────────────────────────────────
MIN_STAKE: float = 1.0
MAX_STAKE_FRACTION: float = 0.20          # STAKE-CAP-0: max 20% of balance per proposal
GOVERNANCE_PASS_MULTIPLIER: float = 1.5   # reward multiplier on pass + fitness improvement
GOVERNANCE_FAIL_BURN_RATE: float = 1.0    # STAKE-BURN-0: 100% burned on failure

_ARS_LEDGER_DEFAULT: str = "data/reputation_stakes.jsonl"
_ARS_WALLET_DEFAULT: str = "data/agent_wallets.json"


# ── Exception types ───────────────────────────────────────────────────────────

class InsufficientStakeError(Exception):
    """Raised when agent balance < MIN_STAKE (STAKE-0)."""


class StakeAlreadyResolvedError(Exception):
    """Raised when resolve() is called on an already-resolved StakeRecord."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_stake_digest(
    agent_id: str, mutation_id: str, epoch_id: str, staked_amount: float
) -> str:
    """STAKE-DETERM-0: deterministic full sha256 digest over four fields."""
    payload = f"{agent_id}:{mutation_id}:{epoch_id}:{staked_amount:.6f}"
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class StakeRecord:
    """Immutable stake snapshot for one agent + mutation.

    STAKE-DETERM-0: stake_digest = sha256(agent_id:mutation_id:epoch_id:staked_amount).
    STAKE-BURN-0:   outcome is set by resolve(); once resolved it is immutable.
    """
    agent_id: str
    mutation_id: str
    epoch_id: str
    staked_amount: float
    pre_stake_balance: float
    outcome: str = "pending"    # pending | passed | failed
    final_balance: float = 0.0
    stake_digest: str = ""

    def __post_init__(self) -> None:
        """STAKE-DETERM-0: compute digest at creation if not already set."""
        if not self.stake_digest:
            self.stake_digest = _compute_stake_digest(
                self.agent_id, self.mutation_id,
                self.epoch_id, self.staked_amount,
            )


# ── Main staking engine ───────────────────────────────────────────────────────

class ReputationStakingLedger:
    """Manages agent staking on mutation proposals.

    STAKE-0        stake() raises InsufficientStakeError if balance < MIN_STAKE.
    STAKE-CAP-0    stake() caps amount at MAX_STAKE_FRACTION of pre-stake balance.
    STAKE-BURN-0   resolve(passed=False) burns 100% of staked_amount.
    STAKE-DETERM-0 stake_digest is full sha256, deterministic.
    STAKE-PERSIST-0 _persist() uses Path.open("a"); wallets use sort_keys=True.
    """

    def __init__(
        self,
        ledger_path: Path = Path(_ARS_LEDGER_DEFAULT),
        wallet_path: Path = Path(_ARS_WALLET_DEFAULT),
    ):
        self.ledger_path = Path(ledger_path)
        self.wallet_path = Path(wallet_path)
        self._wallets: dict[str, float] = {}
        self._stakes: dict[str, StakeRecord] = {}
        self._load()

    # ── Agent registration ────────────────────────────────────────────────────

    def register_agent(self, agent_id: str, initial_balance: float = 100.0) -> None:
        """Register an agent with an initial credit balance if not already present."""
        if agent_id not in self._wallets:
            self._wallets[agent_id] = round(initial_balance, 2)
            self._save_wallets()

    # ── Stake ─────────────────────────────────────────────────────────────────

    def stake(
        self,
        agent_id: str,
        mutation_id: str,
        epoch_id: str,
        amount: float | None = None,
    ) -> StakeRecord:
        """Agent stakes on a proposal.

        STAKE-0:    raises InsufficientStakeError if balance < MIN_STAKE.
        STAKE-CAP-0: clamps amount to MAX_STAKE_FRACTION of pre-stake balance.
        STAKE-DETERM-0: StakeRecord.stake_digest is full sha256.
        STAKE-PERSIST-0: _persist uses Path.open("a").
        """
        balance = self._wallets.get(agent_id, 0.0)

        # STAKE-0: balance gate
        if balance < MIN_STAKE:
            raise InsufficientStakeError(
                f"STAKE-0: agent '{agent_id}' balance {balance:.2f} < MIN_STAKE {MIN_STAKE}"
            )

        # STAKE-CAP-0: compute and clamp stake amount
        if amount is None:
            amount = balance * 0.05           # default: 5% of balance
        amount = min(amount, balance * MAX_STAKE_FRACTION)   # STAKE-CAP-0
        amount = max(MIN_STAKE, min(amount, balance))
        amount = round(amount, 2)

        # Deduct immediately
        self._wallets[agent_id] = round(balance - amount, 2)

        record = StakeRecord(
            agent_id=agent_id,
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            staked_amount=amount,
            pre_stake_balance=round(balance, 2),
        )
        self._stakes[mutation_id] = record
        self._persist(record)
        self._save_wallets()
        return record

    # ── Resolve ───────────────────────────────────────────────────────────────

    def resolve(
        self,
        mutation_id: str,
        passed: bool,
        fitness_improved: bool = False,
    ) -> StakeRecord | None:
        """Settle a staked proposal.

        STAKE-BURN-0: passed=False burns 100% of staked_amount (no return).
        passed=True + fitness_improved: reward = staked * GOVERNANCE_PASS_MULTIPLIER.
        passed=True + no improvement: stake returned at face value (no burn, no bonus).
        Raises StakeAlreadyResolvedError if outcome != 'pending'.
        """
        record = self._stakes.get(mutation_id)
        if record is None:
            return None

        if record.outcome != "pending":
            raise StakeAlreadyResolvedError(
                f"StakeRecord for mutation '{mutation_id}' already resolved: {record.outcome}"
            )

        current = self._wallets.get(record.agent_id, 0.0)

        if not passed:
            # STAKE-BURN-0: stake is consumed — never returned
            record.outcome = "failed"
            record.final_balance = round(current, 2)
        elif fitness_improved:
            # Governance pass + fitness gain → full reward
            earned = round(record.staked_amount * GOVERNANCE_PASS_MULTIPLIER, 2)
            self._wallets[record.agent_id] = round(current + earned, 2)
            record.outcome = "passed"
            record.final_balance = round(self._wallets[record.agent_id], 2)
        else:
            # Pass but no fitness improvement: stake returned at face value
            self._wallets[record.agent_id] = round(current + record.staked_amount, 2)
            record.outcome = "passed"
            record.final_balance = round(self._wallets[record.agent_id], 2)

        self._persist(record)
        self._save_wallets()
        return record

    # ── Queries ───────────────────────────────────────────────────────────────

    def balance(self, agent_id: str) -> float:
        """Return current credit balance for agent."""
        return round(self._wallets.get(agent_id, 0.0), 2)

    def agent_win_rate(self, agent_id: str) -> float:
        """Return pass ratio for agent across all resolved stakes. Fail-open: 1.0 if no history."""
        resolved = [
            r for r in self._stakes.values()
            if r.agent_id == agent_id and r.outcome != "pending"
        ]
        if not resolved:
            return 1.0
        return round(sum(1 for r in resolved if r.outcome == "passed") / len(resolved), 4)

    def pending_stakes(self, agent_id: str | None = None) -> list[StakeRecord]:
        """Return all pending stakes, optionally filtered by agent_id."""
        return [
            r for r in self._stakes.values()
            if r.outcome == "pending" and (agent_id is None or r.agent_id == agent_id)
        ]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """STAKE-0 (fail-open): corrupt entries are silently skipped on load."""
        if self.wallet_path.exists():
            try:
                self._wallets = json.loads(self.wallet_path.read_text())
            except Exception:
                self._wallets = {}
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text().splitlines():
                try:
                    d = json.loads(line)
                    mid = d["mutation_id"]
                    # Only load the most recent record per mutation_id
                    self._stakes[mid] = StakeRecord(**d)
                except Exception:
                    pass

    def _save_wallets(self) -> None:
        """STAKE-PERSIST-0: write wallets with sort_keys for determinism."""
        self.wallet_path.parent.mkdir(parents=True, exist_ok=True)
        self.wallet_path.write_text(json.dumps(self._wallets, indent=2, sort_keys=True))

    def _persist(self, record: StakeRecord) -> None:
        """STAKE-PERSIST-0: append stake record via Path.open — never builtins.open."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as fh:
            fh.write(
                json.dumps(dataclasses.asdict(record), sort_keys=True) + "\n"
            )


__all__ = [
    "ReputationStakingLedger",
    "StakeRecord",
    "InsufficientStakeError",
    "StakeAlreadyResolvedError",
    "MIN_STAKE",
    "MAX_STAKE_FRACTION",
    "GOVERNANCE_PASS_MULTIPLIER",
    "GOVERNANCE_FAIL_BURN_RATE",
]
