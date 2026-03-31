"""
SPARK LCD + Button Smoke Test - CircuitPython
=============================================
Draws the idle screen on the ILI9341 and lights up a cell when a button is pressed.

Wiring
------
  DIN  (MOSI)  -> GP19  (SPI0 TX)
  CLK  (SCK)   -> GP18  (SPI0 SCK)
  CS           -> GP17
  DC           -> GP16
  RST          -> GP20
  BL           -> 3V3   (backlight always on - no code needed)
  PB1          -> GP2
  PB2          -> GP4
  PB3          -> GP3
  PB4          -> GP5

Required libraries (copy to CIRCUITPY/lib/ before running)
-----------------------------------------------------------
  adafruit_ili9341.py
  adafruit_display_text/  (folder)
  adafruit_bus_device/    (folder)

Get them from: https://circuitpython.org/libraries
"""

import time

import board
import keypad

try:
    from pico.lcd_ui import ACTIONS, initialize_lcd_ui
    from pico.pin_config import BUTTON_PIN_NUMBERS
except ImportError:
    from lcd_ui import ACTIONS, initialize_lcd_ui
    from pin_config import BUTTON_PIN_NUMBERS


BUTTON_PINS = tuple(getattr(board, f"GP{pin}") for pin in BUTTON_PIN_NUMBERS)

buttons = keypad.Keys(BUTTON_PINS, value_when_pressed=False, pull=True)
lcd_ui = initialize_lcd_ui()

print("SPARK smoke test running - press PB1-PB4")

while True:
    event = buttons.events.get()
    now = time.monotonic()

    if event and event.pressed:
        index = event.key_number
        print(f"PB{index + 1} -> {ACTIONS[index]}")
        lcd_ui.handle_press(index, now=now)

    lcd_ui.tick(now=now)
    time.sleep(0.01)
