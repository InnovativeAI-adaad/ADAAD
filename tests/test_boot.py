import unittest
from pathlib import Path

from runtime.boot import boot_sequence


class BootTests(unittest.TestCase):
    def test_boot_imports(self) -> None:
        import app.main as m  # noqa: WPS433

        self.assertTrue(hasattr(m, "main"))

    def test_safe_boot_when_no_active_agents(self) -> None:
        active_dir = Path("app/agents/active")
        # Ensure no agent directories are present for the safe-boot path.
        for child in active_dir.iterdir():
            if child.is_dir():
                raise AssertionError("Active agents present; test requires empty active directory")

        ledger_file = Path("security/ledger/events.jsonl")
        try:
            status = boot_sequence()
            self.assertIn("safe_boot", status)
            self.assertFalse(status["mutation_enabled"])
        finally:
            if ledger_file.exists():
                ledger_file.unlink()


if __name__ == "__main__":
    unittest.main()
