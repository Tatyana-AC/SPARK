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

    def test_auxiliary_input_initializes_slider_inputs_driven_common_and_encoder_from_shared_pin_config(self):
        module = _load_button_input_module()
        board = types.SimpleNamespace(
            GP6="gp6",
            GP7="gp7",
            GP8="gp8",
            GP10="gp10",
            GP11="gp11",
        )
        created = []

        class _FakeDigitalInOut:
            def __init__(self, pin):
                self.pin = pin
                self.value = True
                self.pull = None
                self.output_value = None
                created.append(self)

            def switch_to_input(self, *, pull):
                self.pull = pull

            def switch_to_output(self, *, value):
                self.output_value = value

        digitalio = types.SimpleNamespace(DigitalInOut=_FakeDigitalInOut, Pull=types.SimpleNamespace(UP="up"))

        aux_input = module.build_auxiliary_input(board_module=board, digitalio_module=digitalio)

        self.assertIsInstance(aux_input, module.AuxiliaryInput)
        self.assertEqual([pin.pin for pin in created], ["gp6", "gp7", "gp8", "gp10", "gp11"])
        self.assertEqual([pin.pull for pin in created], ["up", "up", None, "up", "up"])
        self.assertEqual([pin.output_value for pin in created], [None, None, False, None, None])

    def test_auxiliary_input_reports_slider_position_and_encoder_scroll_delta(self):
        module = _load_button_input_module()
        slider_values = {"1": True, "2": True}
        encoder_values = {"a": False, "b": False}

        class _Pin:
            def __init__(self, name, source):
                self.name = name
                self.source = source

            @property
            def value(self):
                return self.source[self.name]

        aux_input = module.AuxiliaryInput(
            slider_inputs=(
                (1, _Pin("1", slider_values)),
                (2, _Pin("2", slider_values)),
            ),
            encoder_a=_Pin("a", encoder_values),
            encoder_b=_Pin("b", encoder_values),
        )

        first = aux_input.poll_changes()
        self.assertEqual(first.slider_position, 3)
        self.assertEqual(first.scroll_delta, 0)
        self.assertEqual(first.slider_state, ((1, True), (2, True)))

        slider_values.update({"1": True, "2": False})
        encoder_values["a"] = True
        second = aux_input.poll_changes()
        self.assertEqual(second.slider_position, 2)
        self.assertEqual(second.scroll_delta, 1)
        self.assertEqual(second.slider_state, ((1, True), (2, False)))

        slider_values.update({"1": False, "2": True})
        encoder_values["b"] = True
        third = aux_input.poll_changes()
        self.assertEqual(third.slider_position, 1)
        self.assertEqual(third.scroll_delta, 1)
        self.assertEqual(third.slider_state, ((1, False), (2, True)))

    def test_auxiliary_input_treats_no_readable_position_as_position_three(self):
        module = _load_button_input_module()
        slider_values = {"1": True, "2": True}
        encoder_values = {"a": False, "b": False}

        class _Pin:
            def __init__(self, name, source):
                self.name = name
                self.source = source

            @property
            def value(self):
                return self.source[self.name]

        aux_input = module.AuxiliaryInput(
            slider_inputs=(
                (1, _Pin("1", slider_values)),
                (2, _Pin("2", slider_values)),
            ),
            encoder_a=_Pin("a", encoder_values),
            encoder_b=_Pin("b", encoder_values),
        )

        first = aux_input.poll_changes()

        self.assertEqual(first.slider_position, 3)
        self.assertEqual(first.slider_state, ((1, True), (2, True)))

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

    def test_button_input_debounces_repeated_same_button_presses_within_window(self):
        module = _load_button_input_module()
        raw_events = iter(
            [
                types.SimpleNamespace(pressed=True, key_number=0),
                types.SimpleNamespace(pressed=True, key_number=0),
                None,
            ]
        )
        monotonic_values = iter([1.0, 1.05])
        button_input = module.ButtonInput(
            types.SimpleNamespace(events=types.SimpleNamespace(get=lambda: next(raw_events))),
            monotonic=lambda: next(monotonic_values),
        )

        pressed_events = list(button_input.drain_pressed_events())

        self.assertEqual([event.index for event in pressed_events], [0])

    def test_button_input_allows_same_button_after_debounce_window(self):
        module = _load_button_input_module()
        raw_events = iter(
            [
                types.SimpleNamespace(pressed=True, key_number=0),
                types.SimpleNamespace(pressed=False, key_number=0),
                types.SimpleNamespace(pressed=True, key_number=0),
                None,
            ]
        )
        monotonic_values = iter([1.0, 1.30])
        button_input = module.ButtonInput(
            types.SimpleNamespace(events=types.SimpleNamespace(get=lambda: next(raw_events))),
            monotonic=lambda: next(monotonic_values),
        )

        pressed_events = list(button_input.drain_pressed_events())

        self.assertEqual([event.index for event in pressed_events], [0, 0])

    def test_button_input_requires_release_before_same_button_repeats(self):
        module = _load_button_input_module()
        raw_events = iter(
            [
                types.SimpleNamespace(pressed=True, key_number=0),
                types.SimpleNamespace(pressed=True, key_number=0),
                types.SimpleNamespace(pressed=True, key_number=0),
                None,
            ]
        )
        monotonic_values = iter([1.0, 1.30, 1.60])
        button_input = module.ButtonInput(
            types.SimpleNamespace(events=types.SimpleNamespace(get=lambda: next(raw_events))),
            monotonic=lambda: next(monotonic_values),
        )

        pressed_events = list(button_input.drain_pressed_events())

        self.assertEqual([event.index for event in pressed_events], [0])

    def test_button_input_does_not_debounce_different_buttons(self):
        module = _load_button_input_module()
        raw_events = iter(
            [
                types.SimpleNamespace(pressed=True, key_number=0),
                types.SimpleNamespace(pressed=True, key_number=1),
                None,
            ]
        )
        monotonic_values = iter([1.0, 1.05])
        button_input = module.ButtonInput(
            types.SimpleNamespace(events=types.SimpleNamespace(get=lambda: next(raw_events))),
            monotonic=lambda: next(monotonic_values),
        )

        pressed_events = list(button_input.drain_pressed_events())

        self.assertEqual([event.index for event in pressed_events], [0, 1])

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
