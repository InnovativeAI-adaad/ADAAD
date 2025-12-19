import unittest


class MetaOrchestratorTests(unittest.TestCase):
    def test_policy_exists(self) -> None:
        from security import policy  # noqa: WPS433

        self.assertTrue(callable(policy.evaluate))


if __name__ == "__main__":
    unittest.main()
