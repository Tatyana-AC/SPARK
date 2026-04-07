import builtins
import importlib.util
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock


def _load_button_input_module():
    module_name = f"_test_pico_button_input_{uuid.uuid4().hex}"
    module_path = Path(__file__).resolve().parents[1] / "pico" / "button_input.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PicoButtonInputTests(unittest.TestCase):
    def test_button_input_initializes_keypad_from_shared_pin_config(self):
        module = _load_button_input_module()
        keypad_calls = []

        class _FakeKeys:
            def __init__(self, pins, *, value_when_pressed, pull):
                keypad_calls.append(
                    {
                        "pins": pins,
                        "value_when_pressed": value_when_pressed,
                        "pull": pull,
                    }
                )
                self.events = types.SimpleNamespace(get=lambda: None)

        button_input = module.build_button_input(
            board_module=types.SimpleNamespace(GP2="gp2", GP3="gp3", GP4="gp4", GP5="gp5"),
            keypad_module=types.SimpleNamespace(Keys=_FakeKeys),
        )

        self.assertIsInstance(button_input, module.ButtonInput)
        self.assertEqual(
            keypad_calls,
            [
                {
                    "pins": ("gp2", "gp3", "gp4", "gp5"),
                    "value_when_pressed": False,
                    "pull": True,
                }
            ],
        )

    def test_button_input_yields_pressed_events_only(self):
        module = _load_button_input_module()
        raw_events = iter(
            [
                types.SimpleNamespace(pressed=True, key_number=0),
                types.SimpleNamespace(pressed=False, key_number=1),
                types.SimpleNamespace(pressed=True, key_number=3),
                None,
            ]
        )
        button_input = module.ButtonInput(types.SimpleNamespace(events=types.SimpleNamespace(get=lambda: next(raw_events))))

        pressed_events = list(button_input.drain_pressed_events())

        self.assertEqual([event.index for event in pressed_events], [0, 3])
        self.assertEqual([type(event).__name__ for event in pressed_events], ["ButtonPressed", "ButtonPressed"])

    def test_button_input_does_not_own_ui_or_bridge_side_effects(self):
        module_name = f"_test_pico_button_input_imports_{uuid.uuid4().hex}"
        module_path = Path(__file__).resolve().parents[1] / "pico" / "button_input.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        blocked_imports = {"pico.lcd_ui", "lcd_ui", "pico.bridge_app", "bridge_app"}
        original_import = builtins.__import__

        def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in blocked_imports:
                raise AssertionError(f"unexpected import: {name}")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=tracking_import):
            assert spec.loader is not None
            spec.loader.exec_module(module)


if __name__ == "__main__":
    unittest.main()
