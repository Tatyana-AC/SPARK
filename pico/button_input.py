try:
    from pico.pin_config import (
        BUTTON_PIN_NUMBERS,
        ENCODER_PIN_NUMBERS,
        SLIDER_COMMON_PIN_NUMBER,
        SLIDER_POSITION_PIN_NUMBERS,
    )
except ImportError:
    from pin_config import (
        BUTTON_PIN_NUMBERS,
        ENCODER_PIN_NUMBERS,
        SLIDER_COMMON_PIN_NUMBER,
        SLIDER_POSITION_PIN_NUMBERS,
    )


DEBOUNCE_WINDOW_S = 0.20


class ButtonPressed:
    def __init__(self, *, index):
        self.index = index


class AuxiliaryInputChange:
    def __init__(self, *, slider_position=None, scroll_delta=0, slider_state=None):
        self.slider_position = slider_position
        self.scroll_delta = scroll_delta
        self.slider_state = slider_state


class ButtonInput:
    def __init__(self, keys, *, monotonic=None, debounce_window_s=DEBOUNCE_WINDOW_S):
        self._keys = keys
        if monotonic is None:
            import time
            monotonic = time.monotonic
        self._monotonic = monotonic
        self._debounce_window_s = debounce_window_s
        self._last_pressed_at = {}
        self._pressed_keys = set()

    def drain_pressed_events(self):
        while True:
            event = self._keys.events.get()
            if event is None:
                return
            key_number = event.key_number
            if getattr(event, "pressed", False):
                if key_number in self._pressed_keys:
                    continue
                now = self._monotonic()
                previous_pressed_at = self._last_pressed_at.get(key_number)
                if previous_pressed_at is not None and (now - previous_pressed_at) < self._debounce_window_s:
                    continue
                self._last_pressed_at[key_number] = now
                self._pressed_keys.add(key_number)
                yield ButtonPressed(index=key_number)
                continue
            self._pressed_keys.discard(key_number)


def build_button_input(*, board_module=None, keypad_module=None):
    if board_module is None:
        import board as board_module
    if keypad_module is None:
        import keypad as keypad_module

    pins = tuple(getattr(board_module, f"GP{pin_number}") for pin_number in BUTTON_PIN_NUMBERS)
    keys = keypad_module.Keys(pins, value_when_pressed=False, pull=True)
    return ButtonInput(keys)


class AuxiliaryInput:
    _FORWARD_STEPS = {
        (False, False, True, False),
        (True, False, True, True),
        (True, True, False, True),
        (False, True, False, False),
    }
    _REVERSE_STEPS = {
        (False, False, False, True),
        (False, True, True, True),
        (True, True, True, False),
        (True, False, False, False),
    }

    def __init__(self, *, slider_inputs, encoder_a, encoder_b, slider_common=None):
        self._slider_inputs = tuple(slider_inputs)
        self._slider_common = slider_common
        self._encoder_a = encoder_a
        self._encoder_b = encoder_b
        self._last_slider_position = None
        self._last_slider_state = None
        self._last_encoder_state = self._read_encoder_state()

    def poll_changes(self):
        slider_state = self._read_slider_state()
        position = self._slider_position_from_state(slider_state)
        changed_slider_state = None
        if slider_state != self._last_slider_state:
            changed_slider_state = slider_state
        self._last_slider_state = slider_state

        slider_position = None
        if position is not None and position != self._last_slider_position:
            slider_position = position
        self._last_slider_position = position

        next_encoder_state = self._read_encoder_state()
        transition = self._last_encoder_state + next_encoder_state
        self._last_encoder_state = next_encoder_state
        if transition in self._FORWARD_STEPS:
            scroll_delta = 1
        elif transition in self._REVERSE_STEPS:
            scroll_delta = -1
        else:
            scroll_delta = 0

        return AuxiliaryInputChange(
            slider_position=slider_position,
            scroll_delta=scroll_delta,
            slider_state=changed_slider_state,
        )

    def _read_slider_position(self):
        return self._slider_position_from_state(self._read_slider_state())

    def _read_slider_state(self):
        return tuple((position, bool(pin.value)) for position, pin in self._slider_inputs)

    def _slider_position_from_state(self, slider_state):
        active = [position for position, is_high in slider_state if not is_high]
        if not active:
            return 3
        if len(active) != 1:
            return None
        return active[0]

    def _read_encoder_state(self):
        return (bool(self._encoder_a.value), bool(self._encoder_b.value))


def _make_pullup_input(pin, digitalio_module):
    digital_input = digitalio_module.DigitalInOut(pin)
    digital_input.switch_to_input(pull=digitalio_module.Pull.UP)
    return digital_input


def _make_low_output(pin, digitalio_module):
    digital_output = digitalio_module.DigitalInOut(pin)
    digital_output.switch_to_output(value=False)
    return digital_output


def build_auxiliary_input(*, board_module=None, digitalio_module=None):
    if board_module is None:
        import board as board_module
    if digitalio_module is None:
        import digitalio as digitalio_module

    slider_inputs = tuple(
        (
            position,
            _make_pullup_input(getattr(board_module, f"GP{pin_number}"), digitalio_module),
        )
        for position, pin_number in sorted(SLIDER_POSITION_PIN_NUMBERS.items())
    )
    slider_common = _make_low_output(getattr(board_module, f"GP{SLIDER_COMMON_PIN_NUMBER}"), digitalio_module)
    encoder_a = _make_pullup_input(getattr(board_module, f"GP{ENCODER_PIN_NUMBERS['a']}"), digitalio_module)
    encoder_b = _make_pullup_input(getattr(board_module, f"GP{ENCODER_PIN_NUMBERS['b']}"), digitalio_module)
    return AuxiliaryInput(
        slider_inputs=slider_inputs,
        slider_common=slider_common,
        encoder_a=encoder_a,
        encoder_b=encoder_b,
    )
