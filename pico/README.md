# Pico Quickstart

This folder contains the SPARK Pico Hub reference logic for the current CircuitPython firmware design.

Important: the deployed Pico firmware is a CircuitPython `boot.py` + `code.py` pair. [`main.py`](C:/SPARK/pico/main.py) is a readable behavioral reference for the same Pico role, not the literal file you copy onto `CIRCUITPY`.

## Current firmware shape

The current Pico Hub firmware is documented as a CircuitPython device with these responsibilities:

- `boot.py`: configure USB identity (`VID 0xC4C4` / `PID 0x5350`), enable USB CDC data, and expose the HID interfaces used by the host.
- `code.py`: relay Host CDC bytes to Jetson UART, inject `BUTTON_PRESS` packets on local button events, handle custom Raw HID traffic, and type submitted text back over standard keyboard HID.

## Install CircuitPython on a Raspberry Pi Pico

1. Download the official Raspberry Pi Pico firmware from [circuitpython.org/board/raspberry_pi_pico](https://circuitpython.org/board/raspberry_pi_pico/).
2. Unplug the Pico.
3. Hold the `BOOTSEL` button while plugging the Pico into USB.
4. Wait for the board to appear as a drive named `RPI-RP2`.
5. Drag the downloaded `.uf2` file onto the `RPI-RP2` drive.
6. Let the board reboot. It should remount as `CIRCUITPY`.

If `RPI-RP2` does not appear, the most common cause is a charge-only USB cable. Use a data-capable cable.

## Verify the install

Create `code.py` on the `CIRCUITPY` drive with:

```python
import time
import board
import digitalio

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

while True:
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.5)
```

If the onboard LED blinks, CircuitPython is installed correctly.

## Repo-specific note

Installing CircuitPython is the current bring-up path for the SPARK Pico Hub. This folder does not yet contain the exact deployed `boot.py` / `code.py` pair, so treat [`main.py`](C:/SPARK/pico/main.py) as the feature and protocol reference when implementing or validating the Pico behavior.
