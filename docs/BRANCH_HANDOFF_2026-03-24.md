# SPARK Branch Handoff Summary

This document summarizes what changed on the `sida` branch after Tatyana's
last commit and captures the current expected behavior of the branch.

## Handoff Point

Tatyana's last commit on this branch is:

- `3df08e7` on `2026-03-22`
- author: `Tatyana Cruz`
- subject: `arch: consolidate to single Pico Hub (QMK); remove two-device split`

At that point, the branch had already moved to a single-Pico architecture, but
the Pico-side docs still described a QMK-centered firmware target and the
current CircuitPython runtime did not yet exist.

## What Changed Since Then

### 1. Host app cleanup and Windows support

Branch work after Tatyana's handoff added and tightened the active host path:

- `spark_app_v2.py` remains the active UI entrypoint.
- Windows hotkey handling and provider coverage were improved.
- `host_pc/live_capture.py` was added to dedupe repeated live-capture poll lines
  while still preserving explicit event lines.
- The repo docs were expanded so the current architecture and Windows startup
  path are easier to understand.

Related files:

- [`spark_app_v2.py`](C:/SPARK/spark_app_v2.py)
- [`host_pc/hotkeys.py`](C:/SPARK/host_pc/hotkeys.py)
- [`host_pc/accessibility/windows_provider.py`](C:/SPARK/host_pc/accessibility/windows_provider.py)
- [`host_pc/live_capture.py`](C:/SPARK/host_pc/live_capture.py)

### 2. Pico firmware migrated from QMK plan to CircuitPython implementation

The largest change on this branch is the move from a documented QMK target to
an implemented CircuitPython firmware layout:

- [`pico/boot.py`](C:/SPARK/pico/boot.py) now owns USB identity/configuration.
- [`pico/code.py`](C:/SPARK/pico/code.py) now owns the active runtime loop.
- [`pico/upload_protocol.py`](C:/SPARK/pico/upload_protocol.py) implements the
  V2 Raw HID upload state machine.
- [`pico/serial_bridge.py`](C:/SPARK/pico/serial_bridge.py) handles CDC relay
  and framed `BUTTON_PRESS` injection.
- [`pico/usb_config.py`](C:/SPARK/pico/usb_config.py) defines the custom HID
  descriptor and USB constants.

The Pico is now documented and implemented as a CircuitPython composite USB
device exposing:

- one CDC data port
- one custom Raw HID interface

The previous keyboard-HID type-back behavior is no longer part of the active
firmware contract.

### 3. Raw HID protocol was debugged and hardened on real hardware

The host/Pico HID path was brought up and validated on a real connected Pico.
Important fixes landed during that work:

- custom HID report-ID support was added on both Pico and host sides
- the Pico upload handler was made CircuitPython-compatible by removing the
  unsupported `enum` dependency
- incomplete uploads now reset Pico-side state correctly instead of leaving the
  device stuck in `BUSY`
- the host Raw HID client now inserts a small inter-report gap between chunk
  writes so multi-chunk uploads do not overrun the Pico receive path

Related files:

- [`host_pc/raw_hid.py`](C:/SPARK/host_pc/raw_hid.py)
- [`pico/upload_protocol.py`](C:/SPARK/pico/upload_protocol.py)
- [`pico/usb_config.py`](C:/SPARK/pico/usb_config.py)

### 4. Deploy tooling was added for the Pico

This branch now includes a cross-platform deploy helper:

- [`tools/pico/deploy_to_pico.py`](C:/SPARK/tools/pico/deploy_to_pico.py)

It does the following:

- auto-detects a mounted `CIRCUITPY` volume on Windows/macOS
- copies the SPARK firmware files flat to the board root
- caches `adafruit_hid` under [`tools/pico/vendor`](C:/SPARK/tools/pico/vendor)
- installs that cached library bundle onto the board when needed

### 5. Release flow changed from keyboard injection to app-side output

Originally on this branch, `Release Text` uploaded text to the Pico and the
Pico typed it back into the focused application as keyboard HID.

That is no longer the current behavior.

Current release behavior:

- the host app uploads `processed_text` to the Pico over custom Raw HID
- the Pico validates and acknowledges the upload
- the SPARK app displays the released text locally in a new `RELEASE OUTPUT`
  panel under `LIVE CAPTURE`
- the displayed message is wrapped as:
  - `(echo) <text> (echo)`

Related files:

- [`spark_app_v2.py`](C:/SPARK/spark_app_v2.py)
- [`host_pc/release_output.py`](C:/SPARK/host_pc/release_output.py)
- [`pico/code.py`](C:/SPARK/pico/code.py)
- [`pico/upload_protocol.py`](C:/SPARK/pico/upload_protocol.py)

### 6. UI connection/status behavior was clarified

The app header and release status path were cleaned up:

- the header now shows `DEVICE CONNECTED` / `DEVICE DISCONNECTED`
- the HID connection poll remains a 2-second timer
- release completion now reports back to the main Qt thread via signals instead
  of relying on `QTimer.singleShot(...)` from a Python worker thread

This fixed the case where the UI could stay stuck on `Sending to device…`
despite the Pico already acknowledging the upload.

## Current Expected Behavior

On the branch head, the intended behavior is:

1. `spark_app_v2.py` captures host text/context.
2. Host window/context updates are still sent over CDC toward the Pico/Jetson
   relay path.
3. `Release Text` sends the processed text to the Pico over custom Raw HID.
4. The Pico acknowledges the upload but does not inject keyboard input back
   into the focused external app.
5. The SPARK app shows the acknowledged text locally in the `RELEASE OUTPUT`
   panel as `(echo) ... (echo)`.

## Documentation Added or Rewritten

The following docs were added or substantially rewritten after the handoff:

- [`README.md`](C:/SPARK/README.md)
- [`REPO_STRUCTURE.md`](C:/SPARK/REPO_STRUCTURE.md)
- [`ENGINEERING_SPEC.md`](C:/SPARK/ENGINEERING_SPEC.md)
- [`docs/pico/README.md`](C:/SPARK/docs/pico/README.md)
- [`docs/pico/HARDWARE_SMOKE_TEST.md`](C:/SPARK/docs/pico/HARDWARE_SMOKE_TEST.md)
- this file

## Test and Verification Coverage Added

This branch now includes focused tests for:

- host Raw HID behavior
- Pico upload protocol
- Pico USB descriptor shape
- Pico deploy tooling
- Pico serial bridge framing
- live-capture dedupe behavior
- Windows provider logic
- release-output formatting

Relevant files:

- [`tests/test_host_raw_hid_client.py`](C:/SPARK/tests/test_host_raw_hid_client.py)
- [`tests/test_pico_upload_protocol.py`](C:/SPARK/tests/test_pico_upload_protocol.py)
- [`tests/test_pico_usb_config.py`](C:/SPARK/tests/test_pico_usb_config.py)
- [`tests/test_pico_deploy_to_pico.py`](C:/SPARK/tests/test_pico_deploy_to_pico.py)
- [`tests/test_pico_serial_bridge.py`](C:/SPARK/tests/test_pico_serial_bridge.py)
- [`tests/test_live_capture.py`](C:/SPARK/tests/test_live_capture.py)
- [`tests/test_windows_provider.py`](C:/SPARK/tests/test_windows_provider.py)
- [`tests/test_release_output.py`](C:/SPARK/tests/test_release_output.py)

## Verified Hardware State

During this branch work, the following host/Pico behaviors were verified
against a real CircuitPython Pico:

- custom Raw HID enumeration
- `GET_INFO`
- `PING`
- multi-chunk uploads
- oversized upload rejection
- recovery after incomplete upload
- immediate back-to-back uploads after host pacing fix

The button path and Jetson UART path were intentionally not revalidated in the
final no-keyboard phase.

## Known Notes

- On Windows, launching `spark_app_v2.py` currently appears as a parent/child
  `pythonw.exe` pair. This looks like the app's normal launch shape in this
  environment, not necessarily a duplicate visible UI.
- The deploy script still copies [`pico/typeback.py`](C:/SPARK/pico/typeback.py)
  because it remains in the firmware file list, but the active runtime no
  longer imports or uses it.
