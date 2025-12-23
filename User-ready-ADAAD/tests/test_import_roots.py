import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.append(str(ROOT))


BANNED_ROOTS = {"core", "engines", "adad_core", "ADAAD22"}


class ImportRootTest(unittest.TestCase):
    def test_no_legacy_import_roots(self):
        failures = []
        for path in ROOT.rglob("*.py"):
            if "archives" in path.parts:
                continue
            content = path.read_text(encoding="utf-8").splitlines()
            for lineno, line in enumerate(content, start=1):
                if line.startswith(("from ", "import ")):
                    match = re.match(r"^(from|import) ([\\w\\.\\/]+)", line)
                    if not match:
                        continue
                    root = match.group(2).split(".")[0]
                    if root in BANNED_ROOTS or root.startswith("/"):
                        failures.append(f"{path}:{lineno}:{line.strip()}")
        self.assertFalse(failures, f"Banned import roots found: {failures}")


if __name__ == "__main__":
    unittest.main()
