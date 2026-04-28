"""Shared pin-number assignments for the standalone Pico LCD wiring."""

BUTTON_PIN_NUMBERS = (2, 3, 4, 5)

SLIDER_POSITION_PIN_NUMBERS = {
    1: 6,
    2: 7,
}

SLIDER_COMMON_PIN_NUMBER = 8

ENCODER_PIN_NUMBERS = {
    "button": 9,
    "a": 10,
    "b": 11,
}

LCD_PIN_NUMBERS = {
    "clk": 18,
    "mosi": 19,
    "cs": 17,
    "dc": 16,
    "rst": 20,
}
