import importlib.util
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path


class _FakeRuntimeRunnerModule:
    @staticmethod
    def run_with_diagnostics(callback, *, error_log_path, trace_log_path):
        return None


class _FakeEvent:
    def __init__(self, key_number, pressed=True):
        self.key_number = key_number
        self.pressed = pressed


class _FakeEvents:
    def __init__(self, events):
        self._events = list(events)

    def get(self):
        if self._events:
            return self._events.pop(0)
        return None


class _FakeButtons:
    def __init__(self, events):
        self.events = _FakeEvents(events)


class _FakeLcdUi:
    def __init__(self, call_log=None):
        self.presses = []
        self.call_log = call_log

    def handle_press(self, index, *, now):
        if self.call_log is not None:
            self.call_log.append(("lcd", index, now))
        self.presses.append((index, now))


class PicoCodeTests(unittest.TestCase):
    def _load_code_module(self):
        module_name = f"_test_pico_code_{uuid.uuid4().hex}"
        module_path = Path(__file__).resolve().parents[1] / "pico" / "code.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)

        prior_runtime_runner = sys.modules.get("runtime_runner")
        sys.modules["runtime_runner"] = _FakeRuntimeRunnerModule()
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        finally:
            if prior_runtime_runner is None:
                sys.modules.pop("runtime_runner", None)
            else:
                sys.modules["runtime_runner"] = prior_runtime_runner
        return module

    def test_drain_button_events_updates_lcd_for_press_only_and_emits_debug_first(self):
        module = self._load_code_module()
        call_log = []
        lcd_ui = _FakeLcdUi(call_log=call_log)
        buttons = _FakeButtons([_FakeEvent(2), _FakeEvent(1, pressed=False)])
        module._send_button_debug = lambda message: call_log.append(("debug", message))

        module._drain_button_events(
            buttons,
            lcd_ui,
            now=123.0,
        )

        self.assertEqual(lcd_ui.presses, [(2, 123.0)])
        self.assertEqual(
            call_log,
            [
                ("debug", "PB3 pressed"),
                ("lcd", 2, 123.0),
                ("debug", "PB3 done"),
            ],
        )
        self.assertIsNone(buttons.events.get())

    def test_record_uart_diag_appends_line_to_log_file(self):
        module = self._load_code_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "uart_diag.txt"
            module.UART_DIAG_LOG_PATH = str(log_path)

            module._record_uart_diag("event-1")
            module._record_uart_diag("event-2")

            self.assertEqual(log_path.read_text(encoding="utf-8"), "event-1\nevent-2\n")

    def test_configure_runtime_disables_autoreload(self):
        module = self._load_code_module()
        steps = []
        supervisor = types.SimpleNamespace(runtime=types.SimpleNamespace(autoreload=True))

        module._configure_runtime(supervisor, steps.append)

        self.assertFalse(supervisor.runtime.autoreload)
        self.assertEqual(steps, ["autoreload disabled"])

    def test_lcd_debug_checkpoint_targets_after_press_time(self):
        module = self._load_code_module()

        self.assertEqual(module.LCD_DEBUG_CHECKPOINT, "after_press_time")


if __name__ == "__main__":
    unittest.main()
