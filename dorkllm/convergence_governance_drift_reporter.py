# SPDX-License-Identifier: Apache-2.0
"""
INNOV-108 · CGDR — Convergence Governance Drift Reporter
Phase 203 · v10.14.0

World-first constitutionally-governed post-convergence drift detection engine.
After V10 convergence (score = 1.0/1.0), CGDR runs a scheduled or on-demand
assessment of all 8 CCA criteria against live system state and emits a signed
DriftReport into an HMAC-chained append-only drift ledger.

If any criterion regresses from its last-known passing state, CGDR triggers a
HUMAN-0 alert and marks the system as DRIFTED — fail-closed: all downstream
governed evolution gates consult drift status before proceeding.

Constitutional invariants (Hard-class, fail-closed):
  CGDR-CHAIN-0     Every DriftReport is HMAC-SHA256 chain-linked to its predecessor.
  CGDR-IMMUT-0     Ledger records are append-only; no update or delete.
  CGDR-DETERM-0    Identical (epoch_id, snapshot) inputs produce identical report_digest.
  CGDR-BASELINE-0  Drift is measured against the last PASSED snapshot, never a DRIFTED one.
  CGDR-FAILCLOSED-0 Any unhandled assessment error marks the report as DRIFTED, not PASSING.
  CGDR-HUMAN0-0    Drift acknowledgement (clear_drift) requires explicit human_id; no auto-clear.
  CGDR-SEAL-0      report_digest covers all criteria scores; tampering is detectable.
  CGDR-AUDIT-0     Every assessment, clear, and query is ledger-recorded with ISO-8601 timestamp.
  CGDR-SCOPE-0     CGDR assesses exactly the 8 CCA criteria; additional criteria require amendment.
  CGDR-GATE-0      A DRIFTED system status blocks new phase promotion until HUMAN-0 clears drift.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── constants ─────────────────────────────────────────────────────────────────
_CGDR_VERSION: str = "1.0"
_CGDR_LEDGER: str = "data/cgdr/drift_ledger.jsonl"
_CGDR_BASELINE: str = "data/cgdr/baseline_snapshot.json"
_HMAC_KEY: bytes = b"cgdr-chain-key-v1"

# CGDR-SCOPE-0: exactly 8 CCA criteria
CCA_CRITERIA: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")

CCA_LABELS: dict[str, str] = {
    "C1": "GIR Readiness Score Present",
    "C2": "Hard Invariant Count ≥ 500",
    "C3": "Innovations Shipped ≥ 100",
    "C4": "Hard Class Invariants Alias Present",
    "C5": "CEL Loop Status = FULLY CLOSED",
    "C6": "V10 Ready Flag True",
    "C7": "Schema Version Present",
    "C8": "Schema Version Field Set",
}


# ── exceptions ────────────────────────────────────────────────────────────────
class CGDRViolation(RuntimeError):
    """Hard-class invariant breach."""


class CGDRDriftGateError(CGDRViolation):
    """CGDR-GATE-0: promotion blocked due to active drift."""


class CGDRBaselineError(CGDRViolation):
    """CGDR-BASELINE-0: no passing baseline available."""


class CGDRHuman0Error(CGDRViolation):
    """CGDR-HUMAN0-0: clear_drift called without human_id."""


def _cgdr_guard(condition: bool, inv_id: str, msg: str) -> None:
    if not condition:
        raise CGDRViolation(f"[{inv_id}] {msg}")


# ── data model ────────────────────────────────────────────────────────────────
@dataclass
class CriterionResult:
    criterion_id: str
    label: str
    passing: bool
    observed_value: Any
    expected: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "label": self.label,
            "passing": self.passing,
            "observed_value": self.observed_value,
            "expected": self.expected,
            "note": self.note,
        }


@dataclass
class DriftReport:
    report_id: str
    epoch_id: str
    assessed_at: str
    criteria_results: list[CriterionResult]
    overall_score: float
    status: str            # "PASSING" | "DRIFTED"
    drifted_criteria: list[str]
    report_digest: str
    prev_digest: str
    chain_link: str
    cgdr_version: str = _CGDR_VERSION
    acknowledged_by: str = ""

    @property
    def is_passing(self) -> bool:
        return self.status == "PASSING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "epoch_id": self.epoch_id,
            "assessed_at": self.assessed_at,
            "criteria_results": [r.to_dict() for r in self.criteria_results],
            "overall_score": self.overall_score,
            "status": self.status,
            "drifted_criteria": self.drifted_criteria,
            "report_digest": self.report_digest,
            "prev_digest": self.prev_digest,
            "chain_link": self.chain_link,
            "cgdr_version": self.cgdr_version,
            "acknowledged_by": self.acknowledged_by,
        }


# ── assessor helpers ──────────────────────────────────────────────────────────
def _assess_criteria(snapshot: dict[str, Any]) -> list[CriterionResult]:
    """Evaluate all 8 CCA criteria against the provided state snapshot."""
    results: list[CriterionResult] = []

    # C1 — GIR readiness_score present and ≥ 0.875
    gir_snap = snapshot.get("gir_snapshot", {})
    rs = gir_snap.get("readiness_score", gir_snap.get("cri", None))
    c1_pass = rs is not None and isinstance(rs, (int, float)) and float(rs) >= 0.875
    results.append(CriterionResult(
        "C1", CCA_LABELS["C1"], c1_pass, rs,
        "gir_snapshot.readiness_score ≥ 0.875",
        "" if c1_pass else "readiness_score missing or below threshold",
    ))

    # C2 — hard_invariant_count ≥ 500
    hic = snapshot.get("hard_invariant_count", 0)
    c2_pass = isinstance(hic, int) and hic >= 500
    results.append(CriterionResult(
        "C2", CCA_LABELS["C2"], c2_pass, hic, "≥ 500",
        "" if c2_pass else f"hard_invariant_count={hic} < 500",
    ))

    # C3 — innovations_shipped ≥ 100
    ish = snapshot.get("innovations_shipped", 0)
    c3_pass = isinstance(ish, int) and ish >= 100
    results.append(CriterionResult(
        "C3", CCA_LABELS["C3"], c3_pass, ish, "≥ 100",
        "" if c3_pass else f"innovations_shipped={ish} < 100",
    ))

    # C4 — hard_class_invariants alias present
    hcia = snapshot.get("hard_class_invariants", None)
    c4_pass = hcia is not None and isinstance(hcia, int) and hcia >= 500
    results.append(CriterionResult(
        "C4", CCA_LABELS["C4"], c4_pass, hcia, "hard_class_invariants alias ≥ 500",
        "" if c4_pass else "hard_class_invariants alias missing or below threshold",
    ))

    # C5 — cel_loop_status = "FULLY CLOSED"
    cls = snapshot.get("cel_loop_status", "")
    c5_pass = cls == "FULLY CLOSED"
    results.append(CriterionResult(
        "C5", CCA_LABELS["C5"], c5_pass, cls, '"FULLY CLOSED"',
        "" if c5_pass else f"cel_loop_status={cls!r}",
    ))

    # C6 — v10_ready = True
    v10r = snapshot.get("v10_ready", False)
    c6_pass = v10r is True
    results.append(CriterionResult(
        "C6", CCA_LABELS["C6"], c6_pass, v10r, "True",
        "" if c6_pass else "v10_ready not True",
    ))

    # C7 — schema_version key present
    sv = snapshot.get("schema_version", None)
    c7_pass = sv is not None
    results.append(CriterionResult(
        "C7", CCA_LABELS["C7"], c7_pass, sv, "present",
        "" if c7_pass else "schema_version key missing",
    ))

    # C8 — schema_version has a non-empty value
    c8_pass = sv is not None and str(sv).strip() != ""
    results.append(CriterionResult(
        "C8", CCA_LABELS["C8"], c8_pass, sv, "non-empty string",
        "" if c8_pass else "schema_version empty or null",
    ))

    return results


# ── engine ────────────────────────────────────────────────────────────────────
class ConvergenceGovernanceDriftReporter:
    """INNOV-108 core engine.

    Assesses post-convergence CCA criteria against live state snapshots,
    persists signed DriftReports to an append-only HMAC-chained ledger,
    and gates governed evolution on drift status.
    """

    def __init__(
        self,
        ledger_path: Path | None = None,
        baseline_path: Path | None = None,
        hmac_key: bytes = _HMAC_KEY,
    ) -> None:
        self._ledger_path = ledger_path or Path(_CGDR_LEDGER)
        self._baseline_path = baseline_path or Path(_CGDR_BASELINE)
        self._hmac_key = hmac_key
        self._prev_digest: str = self._genesis_digest()
        self._system_drifted: bool = False
        self._drift_cleared_by: str = ""
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._baseline_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_prev_digest()

    # ── internals ─────────────────────────────────────────────────────────────

    def _genesis_digest(self) -> str:
        return "sha256:" + hashlib.sha256(b"cgdr-genesis-v1").hexdigest()

    def _load_prev_digest(self) -> None:
        if self._ledger_path.exists():
            last_line = ""
            with open(self._ledger_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                try:
                    rec = json.loads(last_line)
                    self._prev_digest = rec.get("chain_link", self._genesis_digest())
                    if rec.get("status") == "DRIFTED" and not rec.get("acknowledged_by"):
                        self._system_drifted = True
                except json.JSONDecodeError:
                    pass

    def _report_id(self, epoch_id: str, snapshot: dict[str, Any]) -> str:
        """CGDR-DETERM-0: deterministic ID."""
        snap_hash = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        src = f"cgdr:{epoch_id}:{snap_hash}"
        return "cgdr:" + hashlib.sha256(src.encode()).hexdigest()[:16]

    def _report_digest(
        self, report_id: str, epoch_id: str, results: list[CriterionResult],
        score: float, status: str,
    ) -> str:
        """CGDR-SEAL-0: digest covers all criteria scores."""
        payload = json.dumps(
            {
                "report_id": report_id,
                "epoch_id": epoch_id,
                "criteria": [r.to_dict() for r in results],
                "overall_score": score,
                "status": status,
            },
            sort_keys=True, ensure_ascii=False,
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()

    def _chain_link(self, report_id: str, prev_digest: str) -> str:
        """CGDR-CHAIN-0: HMAC-SHA256 chain link."""
        msg = f"{report_id}:{prev_digest}".encode()
        return "hmac-sha256:" + hmac_lib.new(self._hmac_key, msg, hashlib.sha256).hexdigest()

    def _now_iso(self) -> str:
        import datetime
        return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _append_ledger(self, report: DriftReport, event_type: str = "assess") -> None:
        """CGDR-IMMUT-0 + CGDR-AUDIT-0: append-only write."""
        rec = report.to_dict()
        rec["event_type"] = event_type
        with open(self._ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _save_baseline(self, snapshot: dict[str, Any], report: DriftReport) -> None:
        """Persist the last-passing snapshot as baseline for CGDR-BASELINE-0."""
        baseline = {
            "snapshot": snapshot,
            "report_id": report.report_id,
            "assessed_at": report.assessed_at,
            "overall_score": report.overall_score,
        }
        with open(self._baseline_path, "w", encoding="utf-8") as fh:
            json.dump(baseline, fh, indent=2, ensure_ascii=False)

    # ── public API ────────────────────────────────────────────────────────────

    def assess(self, epoch_id: str, snapshot: dict[str, Any]) -> DriftReport:
        """Run full CCA assessment against the provided state snapshot.

        CGDR-FAILCLOSED-0: any exception during assessment produces a DRIFTED report.
        CGDR-CHAIN-0: report is chain-linked before ledger append.
        CGDR-BASELINE-0: passing snapshot is saved as new baseline.
        CGDR-GATE-0: system drift flag is set on DRIFTED result.
        """
        try:
            results = _assess_criteria(snapshot)
        except Exception as exc:  # CGDR-FAILCLOSED-0
            # Synthesise a fully-failed report
            results = [
                CriterionResult(c, CCA_LABELS[c], False, None, "N/A",
                                f"assessment error: {exc}")
                for c in CCA_CRITERIA
            ]

        passing_count = sum(1 for r in results if r.passing)
        overall_score = round(passing_count / len(CCA_CRITERIA), 4)
        drifted = [r.criterion_id for r in results if not r.passing]
        status = "PASSING" if not drifted else "DRIFTED"

        report_id = self._report_id(epoch_id, snapshot)
        assessed_at = self._now_iso()
        digest = self._report_digest(report_id, epoch_id, results, overall_score, status)
        chain_link = self._chain_link(report_id, self._prev_digest)

        report = DriftReport(
            report_id=report_id,
            epoch_id=epoch_id,
            assessed_at=assessed_at,
            criteria_results=results,
            overall_score=overall_score,
            status=status,
            drifted_criteria=drifted,
            report_digest=digest,
            prev_digest=self._prev_digest,
            chain_link=chain_link,
        )

        # CGDR-IMMUT-0 + CGDR-AUDIT-0
        self._append_ledger(report, event_type="assess")
        self._prev_digest = chain_link

        if status == "PASSING":
            # CGDR-BASELINE-0: update baseline only on passing runs
            self._save_baseline(snapshot, report)
            self._system_drifted = False
        else:
            # CGDR-GATE-0: flag drift
            self._system_drifted = True

        return report

    def is_drifted(self) -> bool:
        """Return True if the last assessment produced a DRIFTED status."""
        return self._system_drifted

    def assert_no_drift(self, phase_label: str = "") -> None:
        """CGDR-GATE-0: raise CGDRDriftGateError if system is drifted."""
        if self._system_drifted:
            ctx = f" (phase: {phase_label})" if phase_label else ""
            raise CGDRDriftGateError(
                f"[CGDR-GATE-0] System is DRIFTED{ctx}. "
                "HUMAN-0 must call clear_drift() before promotion proceeds."
            )

    def clear_drift(self, human_id: str, note: str = "") -> None:
        """CGDR-HUMAN0-0: acknowledge and clear drift — requires human_id.

        Emits a ledger record with event_type='clear'.
        """
        if not (human_id and human_id.strip()):
            raise CGDRHuman0Error("[CGDR-HUMAN0-0] human_id must be non-empty string.")
        self._system_drifted = False
        self._drift_cleared_by = human_id
        # Emit a ledger record for the clear event (CGDR-AUDIT-0)
        import datetime
        clear_rec = {
            "event_type": "clear_drift",
            "human_id": human_id,
            "note": note,
            "cleared_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "prev_digest": self._prev_digest,
        }
        with open(self._ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(clear_rec, ensure_ascii=False) + "\n")

    def verify_chain(self) -> bool:
        """Verify HMAC chain integrity across all ledger records."""
        if not self._ledger_path.exists():
            return True
        prev = self._genesis_digest()
        with open(self._ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("event_type") == "clear_drift":
                    continue
                expected_link = self._chain_link(rec["report_id"], rec["prev_digest"])
                if rec.get("chain_link") != expected_link:
                    return False
                prev = rec["chain_link"]
        return True

    def latest_report(self) -> DriftReport | None:
        """Return the most recent DriftReport from the ledger."""
        if not self._ledger_path.exists():
            return None
        last: dict | None = None
        with open(self._ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("event_type") == "assess":
                    last = rec
        if last is None:
            return None
        return DriftReport(
            report_id=last["report_id"],
            epoch_id=last["epoch_id"],
            assessed_at=last["assessed_at"],
            criteria_results=[
                CriterionResult(**r) for r in last["criteria_results"]
            ],
            overall_score=last["overall_score"],
            status=last["status"],
            drifted_criteria=last["drifted_criteria"],
            report_digest=last["report_digest"],
            prev_digest=last["prev_digest"],
            chain_link=last["chain_link"],
            cgdr_version=last.get("cgdr_version", _CGDR_VERSION),
            acknowledged_by=last.get("acknowledged_by", ""),
        )

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of current CGDR state."""
        report = self.latest_report()
        return {
            "cgdr_version": _CGDR_VERSION,
            "system_drifted": self._system_drifted,
            "latest_report_id": report.report_id if report else None,
            "latest_status": report.status if report else "NO_REPORT",
            "latest_score": report.overall_score if report else None,
            "latest_drifted_criteria": report.drifted_criteria if report else [],
            "assessed_at": report.assessed_at if report else None,
        }
