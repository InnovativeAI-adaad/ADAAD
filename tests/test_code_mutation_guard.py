# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import tempfile
import unittest
from pathlib import Path

from runtime.tools import code_mutation_guard


class CodeMutationGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_root = Path(self.tmp.name)
        self._orig_allowed = code_mutation_guard.ALLOWED_ROOTS
        code_mutation_guard.ALLOWED_ROOTS = (self.tmp_root,)
        self.addCleanup(setattr, code_mutation_guard, "ALLOWED_ROOTS", self._orig_allowed)

    def test_apply_multi_file_mutation(self) -> None:
        file_a = self.tmp_root / "a.txt"
        file_b = self.tmp_root / "b.txt"
        file_a.write_text("alpha\n", encoding="utf-8")
        file_b.write_text("hello\nworld\n", encoding="utf-8")

        patch = "\n".join(
            [
                "--- a/b.txt",
                "+++ b/b.txt",
                "@@ -1,2 +1,2 @@",
                " hello",
                "-world",
                "+there",
                "",
            ]
        )

        result = code_mutation_guard.apply_code_mutation(
            [
                {"file": str(file_a), "content": "beta\n"},
                {"file": str(file_b), "patch": patch},
            ]
        )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(file_a.read_text(encoding="utf-8"), "beta\n")
        self.assertEqual(file_b.read_text(encoding="utf-8"), "hello\nthere\n")
        self.assertEqual(len(result["targets"]), 2)

    def test_rollback_on_patch_failure(self) -> None:
        file_a = self.tmp_root / "bad.txt"
        file_a.write_text("alpha\n", encoding="utf-8")

        bad_patch = "\n".join(
            [
                "--- a/bad.txt",
                "+++ b/bad.txt",
                "@@ -1,1 +1,1 @@",
                " beta",
                "-gamma",
                "+delta",
                "",
            ]
        )

        result = code_mutation_guard.apply_code_mutation([{"file": str(file_a), "patch": bad_patch}])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(file_a.read_text(encoding="utf-8"), "alpha\n")


if __name__ == "__main__":
    unittest.main()
