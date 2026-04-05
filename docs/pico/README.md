# Pico Quickstart

This document covers the SPARK Pico Hub runtime and bring-up flow for the current CircuitPython firmware design.

Important: the deployed Pico firmware is a CircuitPython `boot.py` + `code.py` pair. [`pico_reference/main.py`](C:/SPARK/pico_reference/main.py) is a readable behavioral reference for the same relay-oriented role, not the literal runtime entrypoint.

## Current firmware files

The current Pico Hub firmware in `pico/` is split into:

- `boot.py`: configure USB identity (`VID 0xC4C4` / `PID 0x5350`), enable USB CDC data, and expose the custom HID interface used by the host.
- `code.py`: relay Host CDC bytes to Jetson UART, forward `FEATURE_1` summarize requests to Jetson, buffer streamed Jetson responses, and handle custom Raw HID traffic.
- `jetson_transport.py`: transport-only UART helper for framed summarize requests and streamed Jetson responses.
- `upload_protocol.py`: V2 upload state machine shared between tests and the device runtime.
- `serial_bridge.py`: CDC relay helper for the Host-to-Jetson runtime path.
- `usb_config.py`: shared USB constants and the custom HID descriptor.
- `protocol.py`: CircuitPython-local copy of the shared framed SPARK packet contract.

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
python tools/pico/deploy_to_pico.py
```

That script will:

- detect the mounted `CIRCUITPY` volume on Windows or macOS
- copy the SPARK firmware files to the root of the board
- install the runtime libraries needed by the current Pico runtime, currently `adafruit_hid`
- remove stale non-preserved files from `CIRCUITPY` so the default deployed runtime exactly matches the repo-owned runtime set

Useful flags:

```bash
python tools/pico/deploy_to_pico.py --dry-run
python tools/pico/deploy_to_pico.py --target /Volumes/CIRCUITPY
python tools/pico/deploy_to_pico.py --library-source /path/to/lib
```

Use `--dry-run` before deploying if you want to review planned deletions and copies without mutating the board.

Manual path if needed:

1. Copy [`boot.py`](C:/SPARK/pico/boot.py) to the root of `CIRCUITPY` as `boot.py`.
2. Copy [`code.py`](C:/SPARK/pico/code.py) to the root of `CIRCUITPY` as `code.py`.
3. Copy these helper modules to the root of `CIRCUITPY`:
   - [`jetson_transport.py`](C:/SPARK/pico/jetson_transport.py)
   - [`protocol.py`](C:/SPARK/pico/protocol.py)
   - [`upload_protocol.py`](C:/SPARK/pico/upload_protocol.py)
   - [`serial_bridge.py`](C:/SPARK/pico/serial_bridge.py)
   - [`usb_config.py`](C:/SPARK/pico/usb_config.py)
4. Copy these runtime libraries into `CIRCUITPY/lib/`:
   - `adafruit_hid/`
5. Reboot the Pico so the USB configuration in `boot.py` is applied.

Runtime reload behavior:

- Changes to `code.py` and the helper modules copied alongside it can auto-reload under CircuitPython after the files are written.
- The deploy helper copies `code.py` last so the runtime restarts after the updated support files are already in place.
- On Windows, give CircuitPython a few seconds after deployment before probing the new runtime. The board can briefly continue serving the previous code during file-write completion.
- Changes to `boot.py` still require a full board reboot / reconnect because USB configuration is established during boot.

The active firmware contract is V2 upload-only:

- supported custom HID commands: `GET_INFO`, `GET_RESPONSE_INFO`, `GET_RESPONSE_CHUNK`, `BEGIN_UPLOAD`, `UPLOAD_CHUNK`, `COMMIT_UPLOAD`, `ABORT_UPLOAD`, `STATUS`
- supported app commands: `SUBMIT_TEXT`, `PING`, `FEATURE_1`
- `SUBMIT_TEXT` validates and acknowledges UTF-8 text uploads; it does not inject keyboard events
- successful uploads can leave a device-side response buffer that the host reads back over Raw HID
- the host app shows released text locally after the Pico acknowledges the upload
- `FEATURE_1` forwards a structured summarize request to Jetson over UART and buffers the streamed Jetson response for host polling
- `Summarize Window` is now verified as a Jetson-backed streamed path
- large Jetson summarize responses must be split across multiple framed UART packets; the Jetson bridge in `jetson/pico_llm_bridge.py` now does that explicitly for the real board
- the current hardware-verified deployment flow is: copy the repo `jetson/` folder into the Jetson `demo/pico_bridge` directory, then run `python tools/pico/deploy_to_pico.py` to exact-sync the default `pico/` runtime onto `CIRCUITPY`

Legacy `0xA0` / `0xA1` / `0xB0` keyboard-trigger/status reports are not part of the current CircuitPython firmware.
