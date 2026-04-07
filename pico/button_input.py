try:
    from pico.pin_config import BUTTON_PIN_NUMBERS
except ImportError:
    from pin_config import BUTTON_PIN_NUMBERS


class ButtonPressed:
    def __init__(self, *, index):
        self.index = index


class ButtonInput:
    def __init__(self, keys):
        self._keys = keys

    def drain_pressed_events(self):
        while True:
            event = self._keys.events.get()
            if event is None:
                return
            if getattr(event, "pressed", False):
                yield ButtonPressed(index=event.key_number)


def build_button_input(*, board_module=None, keypad_module=None):
    if board_module is None:
        import board as board_module
    if keypad_module is None:
        import keypad as keypad_module

    pins = tuple(getattr(board_module, f"GP{pin_number}") for pin_number in BUTTON_PIN_NUMBERS)
    keys = keypad_module.Keys(pins, value_when_pressed=False, pull=True)
    return ButtonInput(keys)
