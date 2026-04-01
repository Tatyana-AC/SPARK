import importlib.util
import sys
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
    def __init__(self):
        self.presses = []

    def handle_press(self, index, *, now):
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

    def test_drain_button_events_drains_press_and_release_without_touching_lcd(self):
        module = self._load_code_module()
        lcd_ui = _FakeLcdUi()
        buttons = _FakeButtons([_FakeEvent(2), _FakeEvent(1, pressed=False)])

        module._drain_button_events(
            buttons,
            lcd_ui,
            now=123.0,
        )

        self.assertEqual(lcd_ui.presses, [])
        self.assertIsNone(buttons.events.get())


if __name__ == "__main__":
    unittest.main()
