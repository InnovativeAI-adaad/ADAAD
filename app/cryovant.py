# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Lightweight Cryovant registry and signature helpers.

This module provides a small, dependency-free implementation of the
registry/signature flow referenced in the project brief. It favors
clarity and testability over cryptographic strength so that the
orchestrator can exercise the new pathways without adding heavy
requirements.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


QUARANTINE = Path("security/quarantine")
QUARANTINE.mkdir(parents=True, exist_ok=True)
LINEAGE_LOG = Path("reports/lineage.jsonl")
LINEAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
POLICY_EVOLUTION = Path("reports/policy_evolution.jsonl")
POLICY_EVOLUTION.parent.mkdir(parents=True, exist_ok=True)


DEFAULT_HMAC_KEY = b"adaad-dev-secret"


@dataclass
class AgentRecord:
    agent_id: str
    name: str
    payload: Dict[str, Any]
    signature: str
    created_at: float
    classification: str | None = None
    ancestor_id: str | None = None
    generation: int | None = None
    fitness_score: float | None = None
    policy_hash: str | None = None
    kernel_hash: str | None = None
    ancestor_policy_id: str | None = None


class CryovantRegistry:
    """A minimal registry with dual-signing metadata.

    The registry tracks agents inside an SQLite ledger while mirroring a
    JSONL file for quick inspection. It uses HMAC-SHA256 for authenticity
    checks and a lightweight RS256-inspired digest to mimic dual signing
    without external crypto dependencies.
    """

    def __init__(
        self,
        ledger_path: Path | str = Path("reports") / "cryovant.db",
        mirror_path: Path | str = Path("reports") / "cryovant.jsonl",
        hmac_key: bytes | None = None,
        rs256_public_key: Optional[str] = None,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.mirror_path = Path(mirror_path)
        self.hmac_key = hmac_key or DEFAULT_HMAC_KEY
        self.rs256_public_key = rs256_public_key
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.ledger_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _hmac_digest(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True).encode()
        digest = hmac.new(self.hmac_key, serialized, hashlib.sha256).hexdigest()
        return digest

    def _rs256_digest(self, payload: Dict[str, Any]) -> str:
        if not self.rs256_public_key:
            return "rs256:n/a"
        serialized = json.dumps(payload, sort_keys=True).encode()
        derived = hashlib.sha256(self.rs256_public_key.encode() + serialized).hexdigest()
        return f"rs256:{derived}"

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        """Return a combined signature string containing HMAC and RS256 digests."""
        hmac_part = self._hmac_digest(payload)
        rsa_part = self._rs256_digest(payload)
        return f"hmac:{hmac_part}|{rsa_part}"

    def verify_ctc(self, payload: Dict[str, Any], signature: str) -> bool:
        expected = self.sign_payload(payload)
        return hmac.compare_digest(expected, signature)

    def _append_mirror_line(self, record_dict: Dict[str, Any]) -> None:
        line = json.dumps(record_dict, separators=(",", ":")) + "\n"
        before = self.mirror_path.stat().st_size if self.mirror_path.exists() else 0
        self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
        with self.mirror_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        after = self.mirror_path.stat().st_size
        if after <= before:
            raise RuntimeError("Cryovant mirror append failed")

    def register_agent(
        self,
        agent_id: str,
        name: str,
        payload: Dict[str, Any],
        *,
        classification: str | None = None,
        ancestor_id: str | None = None,
        generation: int | None = None,
        fitness_score: float | None = None,
        policy_hash: str | None = None,
        kernel_hash: str | None = None,
        ancestor_policy_id: str | None = None,
    ) -> AgentRecord:
        enriched_payload = payload | {
            "classification": classification,
            "ancestor_id": ancestor_id,
            "generation": generation,
            "fitness_score": fitness_score,
            "policy_hash": policy_hash,
            "kernel_hash": kernel_hash,
            "ancestor_policy_id": ancestor_policy_id,
        }
        signature = self.sign_payload(enriched_payload)
        created_at = time.time()
        record = AgentRecord(
            agent_id=agent_id,
            name=name,
            payload=enriched_payload,
            signature=signature,
            created_at=created_at,
            classification=classification,
            ancestor_id=ancestor_id,
            generation=generation,
            fitness_score=fitness_score,
            policy_hash=policy_hash,
            kernel_hash=kernel_hash,
            ancestor_policy_id=ancestor_policy_id,
        )
        with sqlite3.connect(self.ledger_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agents (agent_id, name, payload, signature, created_at) VALUES (?, ?, ?, ?, ?)",
                (record.agent_id, record.name, json.dumps(record.payload), record.signature, record.created_at),
            )
            conn.commit()
        self._append_mirror_line(
            {
                "agent_id": record.agent_id,
                "name": record.name,
                "payload": record.payload,
                "signature": record.signature,
                "created_at": record.created_at,
            }
        )
        self._append_lineage(
            {
                "agent_id": record.agent_id,
                "classification": classification,
                "ancestor_id": ancestor_id,
                "generation": generation,
                "fitness_score": fitness_score,
                "timestamp": created_at,
            }
        )
        if policy_hash or kernel_hash:
            self._append_policy(
                {
                    "agent_id": record.agent_id,
                    "policy_hash": policy_hash,
                    "kernel_hash": kernel_hash,
                    "ancestor_policy_id": ancestor_policy_id,
                    "timestamp": created_at,
                }
            )
        return record

    def _append_lineage(self, record_dict: Dict[str, Any]) -> None:
        with LINEAGE_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record_dict) + "\n")

    def _append_policy(self, record_dict: Dict[str, Any]) -> None:
        with POLICY_EVOLUTION.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record_dict) + "\n")

    def classify_agent(
        self,
        agent_id: str,
        *,
        classification: str,
        ancestor_id: str | None = None,
        generation: int | None = None,
        fitness_score: float | None = None,
    ) -> AgentRecord | None:
        record = self.load_agent(agent_id)
        if not record:
            return None
        updated_payload = record.payload | {
            "classification": classification,
            "ancestor_id": ancestor_id,
            "generation": generation,
            "fitness_score": fitness_score,
        }
        return self.register_agent(
            agent_id=record.agent_id,
            name=record.name,
            payload=updated_payload,
            classification=classification,
            ancestor_id=ancestor_id or record.ancestor_id,
            generation=generation or record.generation,
            fitness_score=fitness_score if fitness_score is not None else record.fitness_score,
        )

    def certify_or_quarantine(self, payload: Dict[str, Any], signature: str, artifact_path: str | None = None) -> bool:
        ok = self.verify_ctc(payload, signature)
        if not ok and artifact_path:
            path = Path(artifact_path)
            if path.exists():
                path.rename(QUARANTINE / path.name)
        return ok

    def certify_policy_change(self, payload: Dict[str, Any], signature: str) -> bool:
        def _valid_digest(value: Any) -> bool:
            if not isinstance(value, str):
                return False
            cleaned = value.strip()
            if cleaned != value:
                return False
            return len(cleaned) == 64 and all(ch in "0123456789abcdef" for ch in cleaned)

        if not isinstance(signature, str) or not signature.strip():
            return False

        policy_hash = payload.get("policy_hash")
        kernel_hash = payload.get("kernel_hash")
        has_policy = _valid_digest(policy_hash)
        has_kernel = _valid_digest(kernel_hash)
        if not (has_policy or has_kernel):
            return False
        return self.verify_ctc(payload, signature)

    def load_agent(self, agent_id: str) -> Optional[AgentRecord]:
        with sqlite3.connect(self.ledger_path) as conn:
            cursor = conn.execute("SELECT agent_id, name, payload, signature, created_at FROM agents WHERE agent_id=?", (agent_id,))
            row = cursor.fetchone()
            if not row:
                return None
            payload = json.loads(row[2])
            return AgentRecord(
                agent_id=row[0],
                name=row[1],
                payload=payload,
                signature=row[3],
                created_at=row[4],
                classification=payload.get("classification"),
                ancestor_id=payload.get("ancestor_id"),
                generation=payload.get("generation"),
                fitness_score=payload.get("fitness_score"),
                policy_hash=payload.get("policy_hash"),
                kernel_hash=payload.get("kernel_hash"),
                ancestor_policy_id=payload.get("ancestor_policy_id"),
            )

