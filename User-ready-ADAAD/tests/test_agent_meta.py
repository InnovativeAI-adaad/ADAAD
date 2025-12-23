import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.append(str(ROOT))

from app.agents import AGENTS_ROOT  # noqa: E402
from app.agents.base_agent import validate_agents  # noqa: E402


class AgentMetadataTest(unittest.TestCase):
    def test_agents_have_required_metadata(self):
        valid, errors = validate_agents(AGENTS_ROOT)
        self.assertTrue(valid, f"Agent metadata missing: {errors}")


if __name__ == "__main__":
    unittest.main()
