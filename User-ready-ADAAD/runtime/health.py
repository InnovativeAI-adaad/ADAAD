class HealthChecks:
    @staticmethod
    def ledger_write(cryo):
        try:
            cryo.append_event({"event": "boot_test"})
            return True
        except Exception:
            return False

    @staticmethod
    def architect_scan(res):
        return bool(res and res.get("status") == "ok")

    @staticmethod
    def dream_discovery(dream):
        return bool(dream.discover_tasks())
