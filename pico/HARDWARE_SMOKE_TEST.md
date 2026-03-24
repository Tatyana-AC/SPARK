# Pico Hardware Smoke Test

Use this checklist after deploying the CircuitPython firmware to the Pico.

Recommended deploy command:

```bash
python pico/deploy_to_pico.py
```

If `adafruit_hid` is not already available locally, the deploy script will cache it under `pico/vendor/adafruit_hid` before copying it to the board.

## USB enumeration

1. Plug in the Pico.
2. Confirm the board enumerates as VID `0xC4C4` / PID `0x5350`.
3. Confirm the host sees:
   - one USB CDC data interface
   - one custom Raw HID interface on usage page `0xFF60`, usage `0x61`
   - one standard keyboard HID interface

## Raw HID upload path

1. Start the host app or a Python shell in the repo virtualenv.
2. Run:

```python
from host_pc.raw_hid import AppCommand, SparkHIDClient

client = SparkHIDClient()
print(client.is_connected())
print(client.get_info())
print(client.ping())
print(client.upload(AppCommand.SUBMIT_TEXT, "hello"))
print(client.upload(AppCommand.SUBMIT_TEXT, "hello ✓ 世界"))
```

3. Verify:
   - `is_connected()` is `True`
   - `get_info()` returns protocol version `0x0002`
   - `ping()` returns `STATUS.OK` with a detail string including `spark ready`
   - `"hello"` types back as `hello`
   - `"hello ✓ 世界"` returns `STATUS.OK`, types the supported characters, and reports a non-zero skipped count

## CDC to UART relay

1. Start the Jetson serial receiver.
2. Start `spark_app_v2.py`.
3. Change focus between two windows on the host.
4. Verify the Jetson sees valid `WINDOW_NEW` and `WINDOW_UPDATE` packets and continues parsing them without framing errors.

## Button injection

1. With the Jetson receiver still running, press each button on `GP14` through `GP17`.
2. Verify one `BUTTON_PRESS (0x05)` packet arrives per physical press.
3. Verify the button id matches the button index.

## Concurrency check

1. Trigger a longer text upload from the host.
2. While the Pico is typing, keep changing windows and press at least one button.
3. Verify:
   - keyboard type-back continues
   - CDC relay still reaches the Jetson
   - button events are still injected with bounded latency
