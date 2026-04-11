import pytest
pytestmark = pytest.mark.regression_standard
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

    def test_is_functional_change_false_for_docstring_only_delta(self) -> None:
        import ast

        old_ast = ast.parse("def run():\n    return 1\n")
        new_ast = ast.parse('def run():\n    """updated docs"""\n    return 1\n')
        self.assertFalse(is_functional_change(old_ast, new_ast))

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


    def test_classify_markdown_path_change_non_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            request = {"ops": [{"file": "README.md", "path": "/content", "value": "updated"}]}
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "NON_FUNCTIONAL_CHANGE")
            self.assertFalse(decision.run_mutation)

    def test_classify_python_body_path_change_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            request = {
                "ops": [
                    {
                        "file": "agent.py",
                        "path": "/body/0",
                        "value": "def run(input=None):\n    return {'ok': True}\n",
                    }
                ]
            }
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "FUNCTIONAL_CHANGE")
            self.assertTrue(decision.run_mutation)

    def test_classify_rejects_parent_traversal_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            request = {"ops": [{"file": "../../outside.py", "content": "x = 1\n"}]}
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.reason, "path_outside_agent_root")
            self.assertEqual(decision.classification, "FUNCTIONAL_CHANGE")

    def test_classify_rejects_absolute_path_injection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            request = {"ops": [{"file": "/etc/passwd", "content": "x = 1\n"}]}
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.reason, "path_outside_agent_root")
            self.assertEqual(decision.classification, "FUNCTIONAL_CHANGE")

    def test_classify_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            outside = agent_path.parent / "outside.py"
            outside.write_text("x = 1\n", encoding="utf-8")
            (agent_path / "escape.py").symlink_to(outside)
            request = {"ops": [{"file": "escape.py", "content": "x = 2\n"}]}
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.reason, "path_outside_agent_root")
            self.assertEqual(decision.classification, "FUNCTIONAL_CHANGE")

    def test_classify_accepts_valid_nested_file_in_agent_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            nested = agent_path / "pkg" / "agent.py"
            nested.parent.mkdir(parents=True)
            nested.write_text("x = 1\n", encoding="utf-8")
            request = {"ops": [{"file": "pkg/agent.py", "content": "x = 2\n"}]}
            decision = classify_mutation_change(agent_path, request)
            self.assertNotEqual(decision.reason, "path_outside_agent_root")

    def test_classify_targets_comment_only_change_non_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            source_file = agent_path / "agent.py"
            source_file.write_text("x = 1\n", encoding="utf-8")
            request = {
                "targets": [
                    {
                        "path": "agent.py",
                        "ops": [
                            {
                                "op": "replace",
                                "source": "# comment only\nx = 1\n",
                            }
                        ],
                    }
                ]
            }
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "NON_FUNCTIONAL_CHANGE")
            self.assertFalse(decision.run_mutation)
            self.assertFalse(decision.run_fitness)
            self.assertFalse(decision.run_resign)

    def test_classify_targets_docstring_only_change_non_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            source_file = agent_path / "agent.py"
            source_file.write_text('def run(input=None):\n    """old docs"""\n    return {"ok": True}\n', encoding="utf-8")
            request = {
                "targets": [
                    {
                        "path": "agent.py",
                        "ops": [
                            {
                                "op": "replace",
                                "content": 'def run(input=None):\n    """new docs"""\n    return {"ok": True}\n',
                            }
                        ],
                    }
                ]
            }
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "NON_FUNCTIONAL_CHANGE")
            self.assertFalse(decision.run_mutation)
            self.assertFalse(decision.run_fitness)
            self.assertFalse(decision.run_resign)

    def test_classify_targets_logic_change_functional(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            source_file = agent_path / "agent.py"
            source_file.write_text("def run(input=None):\n    return 1\n", encoding="utf-8")
            request = {
                "targets": [
                    {
                        "path": "agent.py",
                        "ops": [
                            {
                                "op": "replace",
                                "content": "def run(input=None):\n    return 2\n",
                            }
                        ],
                    }
                ]
            }
            decision = classify_mutation_change(agent_path, request)
            self.assertEqual(decision.classification, "FUNCTIONAL_CHANGE")
            self.assertTrue(decision.run_mutation)
            self.assertTrue(decision.run_fitness)
            self.assertTrue(decision.run_resign)


if __name__ == "__main__":
    unittest.main()
