from __future__ import annotations

from typing import Any, Dict


def evaluate(action: Dict[str, Any], *, subject: str, resource: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ctx = context or {}
    act_type = action.get("type")
    allow = False
    reason = "default_deny"

    if act_type == "write" and resource.startswith("security/ledger"):
        if subject == "cryovant":
            allow = True
            reason = "cryovant_ledger_write"
        else:
            allow = bool(ctx.get("cert_ok"))
            reason = "cert_required"
    elif act_type == "write" and resource.startswith("security/keys"):
        allow = False
        reason = "keys_write_blocked"
    else:
        allow = True
        reason = "permit"

    return {"allow": allow, "reason": reason}
