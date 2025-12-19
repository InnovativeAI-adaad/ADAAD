import unittest


class BootTests(unittest.TestCase):
    def test_boot_imports(self) -> None:
        import app.main as m  # noqa: WPS433

        self.assertTrue(hasattr(m, "main"))


if __name__ == "__main__":
    unittest.main()
