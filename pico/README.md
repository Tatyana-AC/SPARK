# Pico Quickstart

This folder contains the SPARK Pico Hub reference logic for the current CircuitPython firmware design.

Important: the deployed Pico firmware is a CircuitPython `boot.py` + `code.py` pair. [`main.py`](C:/SPARK/pico/main.py) is a readable behavioral reference for the same Pico role, not the literal runtime entrypoint.

## Current firmware files

The current Pico Hub firmware in this folder is split into:

- `boot.py`: configure USB identity (`VID 0xC4C4` / `PID 0x5350`), enable USB CDC data, and expose the HID interfaces used by the host.
- `code.py`: relay Host CDC bytes to Jetson UART, inject `BUTTON_PRESS` packets on local button events, handle custom Raw HID traffic, and type submitted text back over standard keyboard HID.
- `upload_protocol.py`: V2 upload state machine shared between tests and the device runtime.
- `serial_bridge.py`: CDC relay and `BUTTON_PRESS` packet builder.
- `typeback.py`: best-effort text filtering and queued keyboard output helper.
- `usb_config.py`: shared USB constants and the custom HID descriptor.

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

## Deploy to CIRCUITPY

Preferred path:

```bash
python pico/deploy_to_pico.py
```

That script will:

- detect the mounted `CIRCUITPY` volume on Windows or macOS
- copy the SPARK firmware files to the root of the board
- install `adafruit_hid` into `CIRCUITPY/lib`
- cache `adafruit_hid` under [`pico/vendor/adafruit_hid`](C:/SPARK/pico/vendor/adafruit_hid) if it is not available locally
- download the latest Adafruit CircuitPython source bundle automatically to populate that cache when needed

Useful flags:

```bash
python pico/deploy_to_pico.py --dry-run
python pico/deploy_to_pico.py --target /Volumes/CIRCUITPY
python pico/deploy_to_pico.py --library-source /path/to/lib
```

Manual path if needed:

1. Copy [`boot.py`](C:/SPARK/pico/boot.py) to the root of `CIRCUITPY` as `boot.py`.
2. Copy [`code.py`](C:/SPARK/pico/code.py) to the root of `CIRCUITPY` as `code.py`.
3. Copy these helper modules to the root of `CIRCUITPY`:
   - [`upload_protocol.py`](C:/SPARK/pico/upload_protocol.py)
   - [`serial_bridge.py`](C:/SPARK/pico/serial_bridge.py)
   - [`typeback.py`](C:/SPARK/pico/typeback.py)
   - [`usb_config.py`](C:/SPARK/pico/usb_config.py)
4. Install `adafruit_hid` into `CIRCUITPY/lib`.
5. Reboot the Pico so the USB configuration in `boot.py` is applied.

The active firmware contract is V2 upload-only:

- supported custom HID commands: `GET_INFO`, `BEGIN_UPLOAD`, `UPLOAD_CHUNK`, `COMMIT_UPLOAD`, `ABORT_UPLOAD`, `STATUS`
- supported app commands: `SUBMIT_TEXT`, `PING`
- unsupported characters are skipped during type-back with best-effort reporting

Legacy `0xA0` / `0xA1` / `0xB0` keyboard-trigger/status reports are not part of the current CircuitPython firmware.
