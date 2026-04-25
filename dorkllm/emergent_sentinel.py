# SPDX-License-Identifier: Apache-2.0
"""Phase 160 — INNOV-66 · EBS — Emergent Baseline Sentinel.

EBS invariants
==============
EBS-DETERM-0: alert_id is deterministic from canonical detection payload only.
EBS-CHAIN-0: baseline and alert ledgers are independently HMAC-chained.
EBS-HUMAN0-0: CRITICAL alerts emit HUMAN0_AUTHORISATION to CGTH before alert write.
EBS-MUTATE-0: detect() is the sole mutating public behavior.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dorkllm.telemetry_hub import CGTHEventType, ConstitutionalGovernanceTelemetryHub, get_hub

_CHAIN_ROOT = "0" * 64
_EBS_KEY = b"ADAAD-EBS-HMAC-2026"


class EBSChainError(RuntimeError):
    """EBS-CHAIN-0 violation."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hmac_digest(event_id: str) -> str:
    return hmac.new(_EBS_KEY, event_id.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class EBSEvent:
    event_type: str
    payload: Dict[str, Any]
    event_id: str
    prev_hmac: str
    this_hmac: str
    seq: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "payload": self.payload,
            "event_id": self.event_id,
            "prev_hmac": self.prev_hmac,
            "this_hmac": self.this_hmac,
            "seq": self.seq,
        }


class _ChainLedger:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def read_all(self) -> List[EBSEvent]:
        if not self._path.exists():
            return []
        out: List[EBSEvent] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                out.append(
                    EBSEvent(
                        event_type=raw["event_type"],
                        payload=raw["payload"],
                        event_id=raw["event_id"],
                        prev_hmac=raw["prev_hmac"],
                        this_hmac=raw["this_hmac"],
                        seq=int(raw["seq"]),
                    )
                )
        return out

    def verify(self) -> bool:
        expected_prev = _CHAIN_ROOT
        for rec in self.read_all():
            if rec.prev_hmac != expected_prev:
                raise EBSChainError(
                    f"EBS-CHAIN-0: prev_hmac mismatch at seq={rec.seq}; "
                    f"expected={expected_prev} got={rec.prev_hmac}"
                )
            expected_this = _hmac_digest(rec.event_id)
            if rec.this_hmac != expected_this:
                raise EBSChainError(
                    f"EBS-CHAIN-0: this_hmac mismatch at seq={rec.seq}; "
                    f"expected={expected_this} got={rec.this_hmac}"
                )
            expected_prev = rec.this_hmac
        return True

    def append(self, *, event_type: str, payload: Dict[str, Any], event_id: str) -> EBSEvent:
        self.verify()
        current = self.read_all()
        prev_hmac = current[-1].this_hmac if current else _CHAIN_ROOT
        seq = len(current)
        rec = EBSEvent(
            event_type=event_type,
            payload=payload,
            event_id=event_id,
            prev_hmac=prev_hmac,
            this_hmac=_hmac_digest(event_id),
            seq=seq,
        )
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec.to_dict(), sort_keys=True) + "\n")
        return rec


@dataclass(frozen=True)
class DetectionResult:
    alert_id: str
    severity: str
    baseline_digest: str
    alert_written: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity,
            "baseline_digest": self.baseline_digest,
            "alert_written": self.alert_written,
        }


class EmergentSentinel:
    def __init__(self, *, root: Optional[Path] = None, hub: Optional[ConstitutionalGovernanceTelemetryHub] = None) -> None:
        base = root or Path(os.getenv("ADAAD_EBS_ROOT", "data/dork"))
        self._baseline = _ChainLedger(base / "ebs_baseline.jsonl")
        self._alerts = _ChainLedger(base / "ebs_alerts.jsonl")
        self._hub = hub or get_hub()

    def detect(self, payload: Dict[str, Any]) -> DetectionResult:
        """EBS-MUTATE-0: sole mutating public behavior."""
        canonical_payload = _canonical(payload)
        alert_id = _sha256(canonical_payload)
        severity = str(payload.get("severity", "INFO")).upper()
        baseline_digest = _sha256(_canonical({"alert_id": alert_id, "signal": payload.get("signal", "unknown")}))

        baseline_payload = {
            "alert_id": alert_id,
            "baseline_digest": baseline_digest,
            "signal": payload.get("signal", "unknown"),
            "severity": severity,
        }
        self._baseline.append(event_type="BASELINE", payload=baseline_payload, event_id=baseline_digest)

        alert_written = False
        if severity in {"HIGH", "CRITICAL"}:
            alert_payload = {
                "alert_id": alert_id,
                "severity": severity,
                "canonical_payload": json.loads(canonical_payload),
                "baseline_digest": baseline_digest,
            }
            if severity == "CRITICAL":
                self._hub.emit_event(
                    component_id="ebs",
                    event_type=CGTHEventType.HUMAN0_AUTHORISATION,
                    payload={
                        "alert_id": alert_id,
                        "reason": "CRITICAL emergent sentinel alert",
                        "severity": severity,
                        "gate": "EBS-HUMAN0-0",
                    },
                )
            self._alerts.append(event_type="ALERT", payload=alert_payload, event_id=alert_id)
            self._hub.snapshot_ebs(
                alert_id=alert_id,
                severity=severity,
                baseline_digest=baseline_digest,
            )
            alert_written = True

        return DetectionResult(
            alert_id=alert_id,
            severity=severity,
            baseline_digest=baseline_digest,
            alert_written=alert_written,
        )

    def status(self) -> Dict[str, Any]:
        return {
            "component": "ebs",
            "baseline_events": len(self._baseline.read_all()),
            "alert_events": len(self._alerts.read_all()),
            "baseline_chain_intact": self._baseline.verify(),
            "alert_chain_intact": self._alerts.verify(),
        }

    def baseline_chain(self, limit: int = 20) -> Dict[str, Any]:
        records = self._baseline.read_all()
        self._baseline.verify()
        return {
            "chain": [r.to_dict() for r in records[-limit:]],
            "count": len(records),
            "chain_intact": True,
        }

    def alerts_chain(self, limit: int = 20) -> Dict[str, Any]:
        records = self._alerts.read_all()
        self._alerts.verify()
        return {
            "chain": [r.to_dict() for r in records[-limit:]],
            "count": len(records),
            "chain_intact": True,
        }


_DEFAULT: Optional[EmergentSentinel] = None


def get_sentinel() -> EmergentSentinel:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = EmergentSentinel()
    return _DEFAULT
