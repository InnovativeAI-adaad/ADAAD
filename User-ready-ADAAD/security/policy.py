def evaluate(action, subject, resource, context):
    """
    Policy contract.

    Defaults:
      - deny write/commit when uncertified

    Narrow exceptions:
      - allow Cryovant to write its own ledger (otherwise the gatekeeper can deadlock)
      - allow writes to reports/ for observability even when uncertified
    """
    action_type = action.get("type")
    resource = str(resource or "")

    # Hard deny: security keys are never writable through generic policy.
    if action_type in {"write", "commit"} and resource.replace("\\", "/").startswith("security/keys/"):
        return {"allow": False, "reason": "keys_write_forbidden", "requires": ["human_approval"]}

    # Exception: Cryovant may write to its ledger regardless of cert_ok.
    if action_type in {"write", "commit"}:
        norm = resource.replace("\\", "/")
        if subject == "cryovant" and norm.startswith("security/ledger/"):
            return {"allow": True, "reason": "cryo_ledger_write_allowed", "requires": []}

        # Exception: reports are allowed for observability.
        if norm.startswith("reports/"):
            return {"allow": True, "reason": "reports_write_allowed", "requires": []}

    # Default hard guard: deny writes unless Cryovant cert passes.
    if action_type in {"write", "commit"} and not context.get("cert_ok", False):
        return {"allow": False, "reason": "uncertified", "requires": ["human_approval"]}

    return {"allow": True, "reason": "ok", "requires": []}
