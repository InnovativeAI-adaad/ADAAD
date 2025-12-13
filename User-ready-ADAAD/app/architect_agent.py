from pathlib import Path


class ArchitectAgent:
    def __init__(self, base: Path):
        self.base = Path(base)

    def quick_scan(self) -> dict:
        return {
            "status": "ok",
            "agents_root": str(self.base / "app/agents"),
        }

    def engine_state_audit(self, engines: dict, *, cert_ok: bool, health_ok: bool) -> dict:
        """
        WOOD audit.
        Reports the active engine registry and hard-gate state before main loop.
        """
        engine_names = sorted(list(engines.keys()))
        missing = [name for name in ("architect", "dream", "beast") if name not in engines]
        audit_ok = (not missing) and bool(health_ok is True)

        # Contract hints only. Do not mutate. Do not write files here.
        compliance = {
            "has_required_engines": (len(missing) == 0),
            "missing_engines": missing,
            "cert_ok": bool(cert_ok),
            "health_ok": bool(health_ok),
        }

        return {
            "status": "ok" if audit_ok else "warn",
            "engine_registry": engine_names,
            "compliance": compliance,
        }
