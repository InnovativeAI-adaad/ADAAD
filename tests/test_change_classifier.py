# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path

from runtime.evolution.change_classifier import classify_mutation_change, is_doc_change, is_functional_change


class ChangeClassifierTest(unittest.TestCase):
    def test_is_doc_change_true_for_comment_only(self) -> None:
        old = "x = 1\n"
        new = "# comment\nx = 1\n"
        self.assertTrue(is_doc_change(old, new))

    def test_is_functional_change_true_for_constant_change(self) -> None:
        import ast

        old_ast = ast.parse("x = 1\n")
        new_ast = ast.parse("x = 2\n")
        self.assertTrue(is_functional_change(old_ast, new_ast))

    def test_classify_metadata_only_non_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            request = {"ops": [{"op": "set", "path": "/last_mutation", "value": "x"}]}
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "NON_FUNCTIONAL_CHANGE")
            self.assertFalse(decision.run_mutation)

    def test_classify_code_change_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            request = {
                "ops": [
                    {
                        "op": "replace",
                        "file": "agent.py",
                        "content": "def run(input=None):\n    return {'ok': True}\n",
                    }
                ]
            }
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "FUNCTIONAL_CHANGE")
            self.assertTrue(decision.run_mutation)


if __name__ == "__main__":
    unittest.main()
