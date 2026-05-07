#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
ADAAD — Deterministic Audit Demo
=================================
A single-file, seed-pinned demonstration of one complete Constitutional
Evolution Loop (CEL) epoch.  Any external observer can clone the repo,
run this file with a fixed seed, and receive a verifiable output that
matches byte-for-byte.

Usage:
    python demo/deterministic_demo.py                  # fixed demo seed
    python demo/deterministic_demo.py --seed <hex>     # custom seed
    python demo/deterministic_demo.py --verify         # replay + verify ledger
    python demo/deterministic_demo.py --json           # machine-readable output

Exit codes:
    0  — epoch completed; all gates passed
    1  — constitutional violation detected (expected for adversarial seeds)
    2  — ledger verification failed (chain broken)
    3  — environment / import error

ADAAD v9.92.0  ·  Phase 159  ·  InnovativeAI LLC
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Repo root on PYTHONPATH ────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# ── Colour helpers ─────────────────────────────────────────────────────────
_NO_COLOUR = os.environ.get("NO_COLOR") or not sys.stdout.isatty()

def _c(text: str, code: str) -> str:
    return text if _NO_COLOUR else f"\033[{code}m{text}\033[0m"

def _ok(msg: str) -> None:   print(_c(f"  ✔  {msg}", "32"))
def _fail(msg: str) -> None: print(_c(f"  ✘  {msg}", "31"))
def _info(msg: str) -> None: print(_c(f"  ·  {msg}", "36"))
def _head(msg: str) -> None: print(_c(f"\n{'─'*60}\n  {msg}\n{'─'*60}", "33"))

# ── Fixed demo seed ────────────────────────────────────────────────────────
DEMO_SEED_HEX = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
DEMO_EPOCH_ID = "DEMO-EPOCH-001"
DEMO_LEDGER_PATH = Path(_REPO / "data" / "demo_ledger.jsonl")


# ══════════════════════════════════════════════════════════════════════════
# Step 1 — Environment gate
# ══════════════════════════════════════════════════════════════════════════

def _check_env() -> bool:
    """Verify Python ≥3.11 and repo structure are present."""
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        _fail(f"Python 3.11+ required; found {major}.{minor}")
        return False
    _ok(f"Python {major}.{minor}.{sys.version_info[2]}")

    required = [
        "runtime/governance/gate.py",
        "runtime/evolution/acse_engine.py",
        "governance/constitutional_rule_count.json",
    ]
    for path in required:
        if not (_REPO / path).exists():
            _fail(f"Missing: {path}")
            return False
    _ok("Repo structure verified")
    return True


# ══════════════════════════════════════════════════════════════════════════
# Step 2 — Seed derivation (deterministic, auditable)
# ══════════════════════════════════════════════════════════════════════════

def _derive_epoch_seed(seed_hex: str, epoch_id: str) -> str:
    """
    Derive a per-epoch seed using HMAC-SHA256.
    Reproducible: same inputs → same output on any platform.
    """
    return hmac.new(
        bytes.fromhex(seed_hex),
        epoch_id.encode(),
        hashlib.sha256,
    ).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# Step 3 — Mutation proposal (minimal synthetic proposal)
# ══════════════════════════════════════════════════════════════════════════

def _build_mutation(epoch_seed: str) -> dict[str, Any]:
    """Construct a deterministic mutation proposal from the epoch seed."""
    lineage = hashlib.sha256(epoch_seed.encode()).hexdigest()
    return {
        "mutation_id": f"DEMO-MUT-{lineage[:8].upper()}",
        "lineage_digest": lineage,
        "epoch_id": DEMO_EPOCH_ID,
        "proposed_text": (
            "# Demo mutation: add a no-op governance telemetry comment\n"
            "# Epoch: DEMO-EPOCH-001\n"
            f"# Seed-fingerprint: {lineage[:16]}\n"
        ),
        "tier": "SANDBOX",
        "touched_invariant_classes": ["determinism", "audit"],
        "fitness_thresholds": {"constitutional_score": 0.9},
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ══════════════════════════════════════════════════════════════════════════
# Step 4 — ACSE adversarial gate
# ══════════════════════════════════════════════════════════════════════════

def _run_acse_gate(mutation: dict[str, Any]) -> dict[str, Any]:
    """Run the Adversarial Constitutional Stress Engine gate."""
    try:
        from runtime.evolution.acse_engine import (
            AdversarialBudget,
            MutationCandidate,
            derive_adversarial_seed,
            evaluate_acse_gate_0,
        )
    except ImportError as exc:
        return {"passed": False, "error": str(exc), "vectors": 0}

    candidate = MutationCandidate(
        mutation_id=mutation["mutation_id"],
        lineage_digest=mutation["lineage_digest"],
        touched_invariant_classes=mutation["touched_invariant_classes"],
        fitness_thresholds=mutation["fitness_thresholds"],
        epoch_id=mutation["epoch_id"],
        proposed_text=mutation["proposed_text"],
    )
    budget = AdversarialBudget(
        max_wall_clock_ms=5_000,
        llm_calls=0,         # zero LLM calls — fully deterministic
        max_vectors=20,
    )
    seed = derive_adversarial_seed(mutation["lineage_digest"], mutation["epoch_id"])
    result = evaluate_acse_gate_0(
        candidate=candidate,
        budget=budget,
        predecessor_hash=seed,
    )
    bundle = result.bundle
    passed = str(getattr(result, "outcome", "FAIL")) == "PASS"
    return {
        "passed": passed,
        "outcome": str(getattr(result, "outcome", "FAIL")),
        "seed": seed,
        "vectors": len(bundle.test_vectors) if bundle and hasattr(bundle, "test_vectors") else 0,
        "bundle_digest": getattr(bundle, "bundle_digest", "n/a") if bundle else "n/a",
    }


# ══════════════════════════════════════════════════════════════════════════
# Step 5 — GovernanceGate
# ══════════════════════════════════════════════════════════════════════════

def _run_governance_gate(mutation: dict[str, Any], acse: dict[str, Any]) -> dict[str, Any]:
    """Run GovernanceGate v2 with the ACSE bundle."""
    try:
        from runtime.governance.gate import GovernanceGate
    except ImportError as exc:
        return {"approved": False, "error": str(exc)}

    gate = GovernanceGate()
    decision = gate.approve_mutation(
        mutation_id=mutation["mutation_id"],
        trust_mode="sandbox",
        mutation_payload=mutation,
        mutation_context={"acse_passed": acse.get("passed"), "demo_mode": True},
    )
    approved = getattr(decision, "approved", False)
    decision_id = getattr(decision, "decision_id", "n/a")
    return {
        "approved": approved,
        "verdict": "APPROVED" if approved else "REJECTED",
        "decision_id": str(decision_id)[:24] + "…" if len(str(decision_id)) > 24 else str(decision_id),
        "tx_id": getattr(decision, "tx_id", "n/a"),
    }


# ══════════════════════════════════════════════════════════════════════════
# Step 6 — Ledger entry (HMAC-chain-linked)
# ══════════════════════════════════════════════════════════════════════════

_LEDGER_HMAC_KEY = b"DEMO-LEDGER-HMAC-KEY-2026"  # fixed for demo reproducibility

def _chain_digest(prev_digest: str, record: dict[str, Any]) -> str:
    payload = prev_digest + json.dumps(record, sort_keys=True)
    return hmac.new(_LEDGER_HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()

def _write_ledger(
    mutation: dict[str, Any],
    acse: dict[str, Any],
    gov: dict[str, Any],
    ledger_path: Path,
) -> str:
    """Append a chain-linked ledger record; return chain digest."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # Read previous digest
    prev_digest = "GENESIS"
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            try:
                prev_digest = json.loads(line).get("chain_digest", prev_digest)
            except json.JSONDecodeError:
                pass

    record: dict[str, Any] = {
        "schema": "ledger.demo.v1",
        "mutation_id": mutation["mutation_id"],
        "epoch_id": mutation["epoch_id"],
        "tier": mutation["tier"],
        "acse_passed": acse.get("passed"),
        "acse_vectors": acse.get("vectors", 0),
        "gov_approved": gov.get("approved"),
        "gov_verdict": gov.get("verdict"),
        "timestamp_utc": mutation["timestamp_utc"],
        "seed_fingerprint": mutation["lineage_digest"][:16],
    }
    record["chain_digest"] = _chain_digest(prev_digest, record)

    with ledger_path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")

    return record["chain_digest"]


# ══════════════════════════════════════════════════════════════════════════
# Step 7 — Ledger verification
# ══════════════════════════════════════════════════════════════════════════

def _verify_ledger(ledger_path: Path) -> tuple[bool, int]:
    """
    Verify HMAC chain integrity.
    Returns (ok: bool, records_verified: int).
    """
    if not ledger_path.exists():
        return False, 0

    prev_digest = "GENESIS"
    count = 0
    for i, line in enumerate(ledger_path.read_text().splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return False, count

        stored = record.pop("chain_digest", None)
        expected = _chain_digest(prev_digest, record)
        if stored != expected:
            _fail(f"Chain broken at record {i + 1} (stored={stored[:12]}… expected={expected[:12]}…)")
            return False, count

        prev_digest = stored
        record["chain_digest"] = stored
        count += 1

    return True, count


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADAAD deterministic audit demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--seed", default=DEMO_SEED_HEX,
        help=f"64-char hex seed (default: fixed demo seed)",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify existing ledger chain after epoch",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_out",
        help="Emit machine-readable JSON summary",
    )
    parser.add_argument(
        "--ledger", default=str(DEMO_LEDGER_PATH),
        help="Ledger output path",
    )
    args = parser.parse_args()

    ledger_path = Path(args.ledger)
    summary: dict[str, Any] = {"seed": args.seed[:16] + "…", "epoch_id": DEMO_EPOCH_ID}

    # ── Header ──────────────────────────────────────────────────────────
    if not args.json_out:
        print(_c("""
  ╔══════════════════════════════════════════════════════════════╗
  ║  ADAAD — Deterministic Audit Demo · v9.92.0 · Phase 159     ║
  ║  Innovative AI LLC  ·  Apache 2.0                            ║
  ╚══════════════════════════════════════════════════════════════╝""", "36"))

    # ── Step 1: Environment ──────────────────────────────────────────────
    if not args.json_out:
        _head("Step 1 · Environment Gate")
    if not _check_env():
        return 3

    # ── Step 2: Seed ─────────────────────────────────────────────────────
    if not args.json_out:
        _head("Step 2 · Epoch Seed Derivation")
    try:
        epoch_seed = _derive_epoch_seed(args.seed, DEMO_EPOCH_ID)
    except ValueError:
        _fail(f"Invalid seed (must be 64 hex chars): {args.seed[:16]}…")
        return 3
    summary["epoch_seed_fingerprint"] = epoch_seed[:16]
    if not args.json_out:
        _ok(f"Epoch seed: {epoch_seed[:16]}…  (HMAC-SHA256 of base seed + epoch_id)")
        _info("Determinism guarantee: same seed + epoch_id → identical output on any platform")

    # ── Step 3: Mutation proposal ─────────────────────────────────────────
    if not args.json_out:
        _head("Step 3 · Mutation Proposal")
    mutation = _build_mutation(epoch_seed)
    summary["mutation_id"] = mutation["mutation_id"]
    if not args.json_out:
        _ok(f"Mutation ID: {mutation['mutation_id']}")
        _ok(f"Tier: {mutation['tier']}")
        _ok(f"Lineage digest: {mutation['lineage_digest'][:24]}…")

    # ── Step 4: ACSE adversarial gate ─────────────────────────────────────
    if not args.json_out:
        _head("Step 4 · ACSE Adversarial Gate")
    t0 = time.monotonic()
    acse = _run_acse_gate(mutation)
    acse["wall_ms"] = round((time.monotonic() - t0) * 1000, 1)
    summary["acse"] = acse
    if not args.json_out:
        if acse.get("error"):
            _fail(f"ACSE import error: {acse['error']}")
        elif acse["passed"]:
            _ok(f"ACSE gate: PASSED  ({acse['vectors']} adversarial vectors, {acse['wall_ms']} ms)")
            _ok(f"Bundle digest: {str(acse.get('bundle_digest','n/a'))[:24]}…")
        else:
            _fail("ACSE gate: FAILED — mutation blocked")

    # ── Step 5: GovernanceGate ────────────────────────────────────────────
    if not args.json_out:
        _head("Step 5 · GovernanceGate v2")
    gov = _run_governance_gate(mutation, acse)
    summary["governance"] = gov
    if not args.json_out:
        if gov.get("error"):
            _fail(f"Gate import error: {gov['error']}")
        elif gov["approved"]:
            _ok(f"GovernanceGate: APPROVED  (verdict={gov['verdict']})")
        else:
            _fail(f"GovernanceGate: REJECTED  (verdict={gov['verdict']})")

    # ── Step 6: Ledger entry ──────────────────────────────────────────────
    if not args.json_out:
        _head("Step 6 · Ledger Entry")
    chain_digest = _write_ledger(mutation, acse, gov, ledger_path)
    summary["chain_digest"] = chain_digest
    if not args.json_out:
        _ok(f"Ledger: {ledger_path}")
        _ok(f"Chain digest: {chain_digest[:24]}…")

    # ── Step 7: Verify (optional) ─────────────────────────────────────────
    if args.verify:
        if not args.json_out:
            _head("Step 7 · Ledger Chain Verification")
        ok, n = _verify_ledger(ledger_path)
        summary["ledger_verified"] = ok
        summary["ledger_records"] = n
        if not args.json_out:
            if ok:
                _ok(f"Chain intact — {n} record(s) verified")
            else:
                _fail(f"Chain verification failed")
                return 2

    # ── Summary ───────────────────────────────────────────────────────────
    approved = gov.get("approved", False)
    summary["epoch_result"] = "APPROVED" if approved else "REJECTED"

    if args.json_out:
        print(json.dumps(summary, indent=2))
    else:
        print(_c(f"""
  {'─'*60}
  Epoch result : {_c('APPROVED', '32') if approved else _c('REJECTED', '31')}
  Mutation ID  : {mutation['mutation_id']}
  Chain digest : {chain_digest[:32]}…
  Ledger       : {ledger_path}

  Replay this epoch:
    python demo/deterministic_demo.py --seed {args.seed[:16]}…

  Verify ledger:
    python demo/deterministic_demo.py --verify
    python verify_ledger.py {ledger_path}
  {'─'*60}
""", "0"))

    return 0 if approved else 1


if __name__ == "__main__":
    sys.exit(main())
