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
   - `"hello"` returns `STATUS.OK`
   - `"hello ✓ 世界"` returns `STATUS.OK`
   - `SUBMIT_TEXT` does not inject keyboard input back into the host

## CDC to UART relay

1. Start the Jetson serial receiver.
2. Start `spark_app_v2.py`.
3. Change focus between two windows on the host.
4. Verify the Jetson sees valid `WINDOW_NEW` and `WINDOW_UPDATE` packets and continues parsing them without framing errors.

## Button injection

1. With the Jetson receiver still running, press each button on `GP14` through `GP17`.
2. Verify one `BUTTON_PRESS (0x05)` packet arrives per physical press.
3. Verify the button id matches the button index.

## App output check

1. Run `spark_app_v2.py`.
2. Capture text, then use `Release Text`.
3. Verify:
   - the host app status changes to indicate the device accepted the upload
   - the new release-output panel in the SPARK UI shows the released text
   - no keyboard text is injected into the currently focused external app
