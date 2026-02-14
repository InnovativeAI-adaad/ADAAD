# SPDX-License-Identifier: Apache-2.0

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.test_sandbox import TestSandbox, TestSandboxStatus


class TestSandboxTest(unittest.TestCase):
    def test_run_tests_success_and_cleanup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=10)
        result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])
        self.assertTrue(result.ok)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(Path(result.sandbox_dir).exists())

    def test_run_tests_timeout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=1)

        timeout_exc = subprocess.TimeoutExpired(cmd=["pytest"], timeout=1, output="partial-out", stderr="partial-err")
        with patch("runtime.test_sandbox.subprocess.run", side_effect=timeout_exc):
            result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])

        self.assertFalse(result.ok)
        self.assertIn("timeout", result.output.lower())
        self.assertIsNone(result.returncode)
        self.assertFalse(Path(result.sandbox_dir).exists())
        self.assertEqual(result.stdout, "partial-out")
        self.assertEqual(result.stderr, "partial-err")
        self.assertEqual(result.status, TestSandboxStatus.TIMEOUT)

    def test_run_tests_uses_temp_env(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)

        seen = {}

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            seen["cmd"] = cmd
            seen["env"] = kwargs.get("env", {})
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with patch("runtime.test_sandbox.subprocess.run", side_effect=fake_run):
            result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])

        self.assertTrue(result.ok)
        self.assertIn("--basetemp=", " ".join(seen["cmd"]))
        self.assertTrue(seen["env"]["TMPDIR"].startswith(tempfile.gettempdir()))
        self.assertEqual(seen["env"]["PYTHONDONTWRITEBYTECODE"], "1")

    def test_run_tests_captures_stdout_stderr(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)

        with patch(
            "runtime.test_sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess(["pytest"], 1, stdout="out", stderr="err"),
        ):
            result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])

        self.assertFalse(result.ok)
        self.assertEqual(result.stdout, "out")
        self.assertEqual(result.stderr, "err")
        self.assertEqual(result.output, "err")

    def test_run_tests_with_retry_recovers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)

        calls = {"count": 0}

        def flaky_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if calls["count"] == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with patch("runtime.test_sandbox.subprocess.run", side_effect=flaky_run):
            result = sandbox.run_tests_with_retry(args=["tests/test_import_roots.py", "-q"], retries=2)

        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.retries, 1)
        self.assertEqual(result.status, TestSandboxStatus.OK)

    def test_run_tests_keep_sandbox(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)
        result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"], keep_sandbox=True)
        self.assertTrue(Path(result.sandbox_dir).exists())
        shutil.rmtree(result.sandbox_dir, ignore_errors=True)

    def test_post_hook_runs_before_cleanup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        observed = {"exists": False}

        def post_hook(result) -> None:  # type: ignore[no-untyped-def]
            observed["exists"] = Path(result.sandbox_dir).exists()

        sandbox = TestSandbox(root_dir=root, timeout_s=5, post_hook=post_hook)
        result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])
        self.assertTrue(result.ok)
        self.assertTrue(observed["exists"])

    def test_hook_failures_are_logged_not_raised(self) -> None:
        root = Path(__file__).resolve().parents[1]

        def bad_pre(_root: Path) -> None:
            raise RuntimeError("pre boom")

        def bad_post(_result) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("post boom")

        sandbox = TestSandbox(root_dir=root, timeout_s=5, pre_hook=bad_pre, post_hook=bad_post)
        result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])
        self.assertTrue(result.ok)

    def test_parallel_with_retry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)

        calls = {}

        def flaky_parallel(cmd, **kwargs):  # type: ignore[no-untyped-def]
            key = next((part for part in cmd if isinstance(part, str) and part.startswith("--maxfail=")), "default")
            calls[key] = calls.get(key, 0) + 1
            if calls[key] == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="flake")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with patch("runtime.test_sandbox.subprocess.run", side_effect=flaky_parallel):
            results = sandbox.run_tests_parallel_with_retry(
                [
                    ["tests/test_import_roots.py", "-q", "--maxfail=1"],
                    ["tests/test_import_roots.py", "-q", "--maxfail=2"],
                ],
                retries=1,
            )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.ok for result in results))


    def test_failed_artifacts_can_be_retained(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5, retain_failed_artifacts=True)

        with patch(
            "runtime.test_sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess(["pytest"], 1, stdout="", stderr="failed"),
        ):
            result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])

        archived = root / "failed_tests" / Path(result.sandbox_dir).name
        self.assertTrue(archived.exists())
        shutil.rmtree(archived, ignore_errors=True)


    def test_metrics_payload_uses_env_allowlist_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)

        with patch("runtime.test_sandbox.metrics.log") as log_mock:
            sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])

        metrics_calls = [kwargs for _, kwargs in log_mock.call_args_list if kwargs.get("event_type") == "test_sandbox_metrics"]
        self.assertTrue(metrics_calls)
        payload = metrics_calls[-1]["payload"]
        self.assertNotIn("env_keys", payload)
        self.assertEqual(payload["env_allowlist"], ["TMPDIR", "TEMP", "TMP", "PYTHONDONTWRITEBYTECODE"])

    def test_memory_logging_skipped_when_psutil_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sandbox = TestSandbox(root_dir=root, timeout_s=5)
        with patch("runtime.test_sandbox._PSUTIL", None), patch("runtime.test_sandbox.metrics.log") as log_mock:
            result = sandbox.run_tests(args=["tests/test_import_roots.py", "-q"])
        self.assertIsNone(result.memory_mb)
        events = [kwargs["event_type"] for _, kwargs in log_mock.call_args_list]
        self.assertIn("test_sandbox_memory_skipped", events)


if __name__ == "__main__":
    unittest.main()
