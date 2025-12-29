from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

DEFAULT_PATH = os.path.join("security", "ledger", "_nonce_kv.json")


def _load(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"nonces": {}, "challenges": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _gc(db: Dict[str, Any]) -> None:
    now = int(time.time())
    nonces = db.get("nonces", {})
    db["nonces"] = {k: v for k, v in nonces.items() if int(v) >= now}
    challenges = db.get("challenges", {})
    db["challenges"] = {k: v for k, v in challenges.items() if int(v.get("exp", 0)) >= now}


def _atomic_write_json(path: str, obj: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def seen_nonce(nonce: str, path: str = DEFAULT_PATH) -> bool:
    db = _load(path)
    return hash_nonce(nonce) in db.get("nonces", {})


def mark_nonce(nonce: str, ttl_seconds: int = 3600, path: str = DEFAULT_PATH) -> None:
    db = _load(path)
    now = int(time.time())
    h = hash_nonce(nonce)
    db.setdefault("nonces", {})[h] = now + int(ttl_seconds)
    _gc(db)
    _atomic_write_json(path, db)


def put_challenge(challenge_id: str, challenge: str, ttl_seconds: int = 300, path: str = DEFAULT_PATH) -> None:
    db = _load(path)
    now = int(time.time())
    db.setdefault("challenges", {})[challenge_id] = {"challenge": challenge, "exp": now + int(ttl_seconds)}
    _gc(db)
    _atomic_write_json(path, db)


def get_challenge(challenge_id: str, path: str = DEFAULT_PATH) -> Optional[str]:
    db = _load(path)
    item = db.get("challenges", {}).get(challenge_id)
    if not item:
        return None
    now = int(time.time())
    if int(item.get("exp", 0)) < now:
        return None
    return item.get("challenge")


def consume_challenge(challenge_id: str, path: str = DEFAULT_PATH) -> None:
    db = _load(path)
    if "challenges" in db and challenge_id in db["challenges"]:
        del db["challenges"][challenge_id]
    _gc(db)
    _atomic_write_json(path, db)


__all__ = [
    "DEFAULT_PATH",
    "hash_nonce",
    "seen_nonce",
    "mark_nonce",
    "put_challenge",
    "get_challenge",
    "consume_challenge",
]
