import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock


class PicoRuntimeRunnerTests(unittest.TestCase):
    def _workspace_tempdir(self, name: str) -> Path:
        root = Path(__file__).resolve().parents[1] / ".tmp" / f"{name}-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_run_with_diagnostics_clears_error_log_and_records_steps(self):
        from pico.runtime_runner import run_with_diagnostics

        root = self._workspace_tempdir("runtime-runner-steps")
        error_log = root / "runtime_error.txt"
        trace_log = root / "startup_trace.txt"
        error_log.write_text("old error", encoding="utf-8")

        def callback(record_step):
            record_step("imports ready")
            record_step("display ready")
            return "ok"

        result = run_with_diagnostics(
            callback,
            error_log_path=error_log,
            trace_log_path=trace_log,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(error_log.read_text(encoding="utf-8"), "")
        self.assertEqual(
            trace_log.read_text(encoding="utf-8").splitlines(),
            ["imports ready", "display ready"],
        )

    def test_run_with_diagnostics_logs_traceback_before_reraising(self):
        from pico.runtime_runner import run_with_diagnostics

        root = self._workspace_tempdir("runtime-runner-error")
        error_log = root / "runtime_error.txt"
        trace_log = root / "startup_trace.txt"

        def callback(record_step):
            record_step("imports ready")
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            run_with_diagnostics(
                callback,
                error_log_path=error_log,
                trace_log_path=trace_log,
            )

        error_text = error_log.read_text(encoding="utf-8")
        self.assertIn("Unhandled exception in code.py", error_text)
        self.assertIn("RuntimeError: boom", error_text)
        self.assertEqual(trace_log.read_text(encoding="utf-8").splitlines(), ["imports ready"])

    def test_run_with_diagnostics_ignores_oserror_from_file_logging(self):
        from pico.runtime_runner import run_with_diagnostics

        steps = []

        def callback(record_step):
            record_step("imports ready")
            return "ok"

        with mock.patch("pico.runtime_runner._write_text", side_effect=OSError("readonly")), mock.patch(
            "pico.runtime_runner._append_line", side_effect=OSError("readonly")
        ):
            result = run_with_diagnostics(
                callback,
                error_log_path="runtime_error.txt",
                trace_log_path="startup_trace.txt",
            )

        self.assertEqual(result, "ok")
        self.assertEqual(steps, [])


if __name__ == "__main__":
    unittest.main()
