try:
    from pico.pin_config import BUTTON_PIN_NUMBERS
except ImportError:
    from pin_config import BUTTON_PIN_NUMBERS


DEBOUNCE_WINDOW_S = 0.20


class ButtonPressed:
    def __init__(self, *, index):
        self.index = index


class ButtonInput:
    def __init__(self, keys, *, monotonic=None, debounce_window_s=DEBOUNCE_WINDOW_S):
        self._keys = keys
        if monotonic is None:
            import time
            monotonic = time.monotonic
        self._monotonic = monotonic
        self._debounce_window_s = debounce_window_s
        self._last_pressed_at = {}

    def drain_pressed_events(self):
        while True:
            event = self._keys.events.get()
            if event is None:
                return
            if getattr(event, "pressed", False):
                now = self._monotonic()
                key_number = event.key_number
                previous_pressed_at = self._last_pressed_at.get(key_number)
                if previous_pressed_at is not None and (now - previous_pressed_at) < self._debounce_window_s:
                    continue
                self._last_pressed_at[key_number] = now
                yield ButtonPressed(index=event.key_number)


def build_button_input(*, board_module=None, keypad_module=None):
    if board_module is None:
        import board as board_module
    if keypad_module is None:
        import keypad as keypad_module

    pins = tuple(getattr(board_module, f"GP{pin_number}") for pin_number in BUTTON_PIN_NUMBERS)
    keys = keypad_module.Keys(pins, value_when_pressed=False, pull=True)
    return ButtonInput(keys)
