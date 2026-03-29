# SPARK Repo Structure Notes

## What This Repo Is

SPARK is no longer just a desktop capture panel. On the current `sida` branch, it is a distributed three-node system:

- Host PC app: PyQt desktop app that captures desktop context, tracks window state, talks to hardware, and maintains a local history DB.
- Pico Hub: RP2040/CircuitPython device that exposes custom Raw HID and USB CDC serial, bridging context packets toward Jetson and accepting HID uploads from the host.
- Jetson Brain: serial receiver plus SQLite store for session-oriented context and button events.

The current codebase is best understood as a host application plus protocol and hardware integration layers.

## Top-Level Layout

```text
SPARK/
|- spark_app_v2.py                 # Active host UI and hardware-integrated desktop panel
|- spark_app.py                    # Older desktop UI path; still wired to keyboard HID manager
|- host_pc/                        # Host-side runtime package
|  |- accessibility/               # Cross-platform text capture
|  |  `- base.py                   # TextSource enum (incl. WEB_CONTENT), shared dataclasses
|  |- hid/                         # Keyboard Raw HID manager abstraction
|  |- browser.py                   # Browser tab metadata
|  |- context.py                   # LLM-friendly host context object
|  |- db.py                        # Host-side local SQLite store
|  |- hotkeys.py                   # Global hotkeys
|  |- live_capture.py              # Live-capture feed dedupe helper
|  |- raw_hid.py                   # Raw HID upload + response-fetch client for SPARK device
|  |- serial_sender.py             # Bidirectional CDC serial bridge to Pico Hub / Jetson
|  `- web_content.py               # AppleScript browser text extractor (Docs, Sheets, general)
|- core/                           # Shared wire protocol builder/parser
|- jetson/                         # Jetson serial receiver and DB layer
|- pico/                           # Pico firmware and tooling
|  |- boot.py                      # USB identity + CDC/HID composite setup
|  |- code.py                      # Active CircuitPython runtime loop (incl. JetsonTransport)
|  |- lcd_smoke_test.py            # Standalone ILI9341 + button smoke test (copy to CIRCUITPY)
|  |- deploy_to_pico.py            # Cross-platform deploy helper
|  `- HARDWARE_SMOKE_TEST.md       # Wiring reference and test checklist
|- lcd_screen_ui/                  # React UI kit for the 320×240 ILI9341 LCD
|  |- src/app/                     # Screen components + state machine
|  `- README.md                    # Hardware specs, layout rules, dev server instructions
|- tests/                          # Focused unit tests
|- docs/                           # Handoff and decision records
|- ENGINEERING_SPEC.md             # Best architecture source of truth
|- documentation_reference.md      # Older host-app-focused notes; partially outdated
|- diagram.md                      # Earlier system diagram; partially outdated
|- pin_layout.png                  # Pico ↔ ILI9341 and button wiring diagram
|- requirements.txt                # Current Python dependencies
|- spark.db                        # Host-local runtime state, ignored in git
`- setup_accessibility_macos.py    # macOS accessibility setup helper
```

## Architecture Summary

### 1. Host Node

The host node is the user-facing desktop application.

- `spark_app_v2.py`
  - Main active entrypoint.
  - Runs a 125 ms polling loop.
  - Captures active-window context through `AccessibilityManager`.
  - Updates local history via `WindowContextTracker` and `SparkDB`.
  - Maintains a deduped live-capture feed via `LiveCaptureFeed`.
  - Sends window context over serial to the Pico Hub using `SerialSender`.
  - Uploads release text to the SPARK device over Raw HID using `SparkHIDClient`.
  - Shows accepted release output locally in the UI after device acknowledgment.
  - Shows device connection state in the panel header.
- `spark_app.py`
  - Legacy/alternate desktop UI.
  - Still uses `KeyboardHIDManager` from `host_pc.hid`.
  - Useful for reference, but `spark_app_v2.py` is the active app path and the only firmware-compatibility target.

### 2. Shared Protocol Layer

- `core/protocol.py`
  - Defines the SPARK wire protocol.
  - Builds:
    - `WINDOW_NEW` (`0x01`)
    - `WINDOW_UPDATE` (`0x02`)
    - `BUTTON_PRESS` (`0x05`)
  - Implements packet framing:
    - magic bytes `SP`
    - packet type
    - little-endian payload length
    - payload
    - CRC-8/MAXIM
  - Also contains `PacketParser`, which the Jetson receiver uses to decode the serial stream.

### 3. Pico Hub Layer

- `pico/boot.py`
  - CircuitPython USB bootstrap.
  - Sets the SPARK USB identity and enables:
    - one USB CDC data interface
    - one custom Raw HID interface
- `pico/code.py`
  - Active CircuitPython runtime loop.
  - Bridges CDC data to Jetson UART, injects `BUTTON_PRESS`, and handles Raw HID uploads.
- `pico/upload_protocol.py`
  - Pure-Python implementation of the V2 upload protocol state machine.
- `pico/serial_bridge.py`
  - CDC-to-UART relay helper and `BUTTON_PRESS` packet builder.
- `pico/main.py`
  - Reference implementation and readable spec for the Pico relay behavior.
  - Treat this as documentation/reference code, not the literal deployed `boot.py` / `code.py` pair.
  - Describes the Pico’s job:
    - relay host CDC serial bytes to Jetson UART
    - inject button-press packets
    - coexist with custom Raw HID control traffic on the same physical device
- `ENGINEERING_SPEC.md`
  - The real source of truth for the distributed architecture and the CircuitPython-based single-Pico design.

### 4. Jetson Layer

- `jetson/receiver.py`
  - Serial receiver for the Jetson.
  - Reads bytes from UART, feeds them into `PacketParser`, and dispatches decoded packets into the Jetson DB layer.
- `jetson/db_manager.py`
  - Session-aware SQLite store for the Jetson side.
  - Maintains:
    - `sessions`
    - `button_events`
  - Uses one session row per contiguous window visit, with updates rewriting the active session’s text instead of inserting new rows on every poll.

## Host Package Map

### Accessibility and Context Capture

Files under `host_pc/accessibility/` are still the base of the host app:

- `base.py`
  - Shared dataclasses and protocol:
    - `WindowInfo`
    - `TextContext`
    - `WindowContextSnapshot`
    - `TextSource`
    - `AccessibilityProvider`
- `manager.py`
  - Cross-platform facade over macOS and Windows providers.
- `macos_provider.py`
  - Real macOS accessibility implementation via PyObjC / AX APIs.
- `windows_provider.py`
  - Windows accessibility implementation path.
- `tracker.py`
  - Tracks current and previous windows.
  - Persists host snapshots into `spark.db`.
  - Provides the `context_key` logic used to detect window changes.

### Host-Side Supporting Modules

- `browser.py`
  - Browser tab enrichment for supported desktop browsers.
- `context.py`
  - LLM-ready host context object.
- `db.py`
  - Host-side local SQLite store for snapshots and preferences.
- `hotkeys.py`
  - Global hotkey listener.
  - Current Windows defaults: `Win+Alt+C` for capture, `Win+Alt+V` for release, and `Win+Alt+Space` for window toggle.
  - Avoid `Alt+Space`-based bindings on Windows because `Alt+Space` opens the active window system menu.
  - If a local Windows setup must suppress that effect, the current documented workaround is an AutoHotkey rule: `#!Space::return`.
- `live_capture.py`
  - Small helper extracted from V2 to manage live-capture display lines.
  - Important behavior: dedupes repeated poll entries, but still allows explicit event entries like `[CAPTURED] ...`.

### Web Content Extraction

- `web_content.py`
  - `WebContentExtractor` — uses AppleScript to inject JavaScript into the active browser tab.
  - Supported targets: Google Docs (`.kix-lineview-text-block`), Google Sheets (`.waffle td`), general websites (`document.body.innerText`).
  - Bypasses the AX accessibility tree, which returns almost nothing for browser-rendered content.
  - `TextSource.WEB_CONTENT` was added to `accessibility/base.py` to tag text sourced this way.

### Hardware / Device Communication

- `raw_hid.py`
  - Synchronous Raw HID client used by `spark_app_v2.py`.
  - Upload path: `BEGIN_UPLOAD` → chunks → `COMMIT_UPLOAD` (unchanged).
  - **New in this branch:** response-fetch path:
    - `GET_RESPONSE_INFO` (0x20) — query whether the Pico/Jetson has a response ready.
    - `GET_RESPONSE_CHUNK` (0x21) — download a response chunk by index.
    - `ResponseInfo` dataclass, `get_response_info()`, `fetch_response()`.
    - `round_trip_text()` — upload + fetch in one call.
    - `stream_round_trip_text()` — upload then poll for a streaming response with callback.
  - `_ensure_idle()` aborts a stale upload session on the device before each new upload.
  - `_read_until(predicate)` replaces raw `_read()` calls for all status waits.
- `serial_sender.py`
  - **Expanded** from a one-way packet writer to a bidirectional CDC serial bridge.
  - Now uses `list_ports` with VID/PID (`0xC4C4 / 0x5350`) for reliable Pico detection.
  - `send_raw()` — send arbitrary bytes (used by the summarize streaming flow).
  - Background reader thread with `set_stream_callback()` — notifies caller of incoming bytes.
  - `ACK` (`0x06`) and `EOT` (`0x04`) byte constants.
  - Existing `send_window_new()` / `send_window_update()` framed helpers are unchanged.
- `hid/keyboard_hid.py`
  - Higher-level keyboard HID manager abstraction.
  - Legacy path used by `spark_app.py`.
  - Not part of the active `spark_app_v2.py` to CircuitPython firmware contract.

## Current Runtime Flow

The main V2 app flow is now:

1. `spark_app_v2.py` starts the Qt panel.
2. It creates:
   - `AccessibilityManager`
   - `GlobalHotkeyManager`
   - `SparkDB`
   - `WindowContextTracker`
   - `SparkHIDClient`
   - `SerialSender`
   - `LiveCaptureFeed`
3. Every 125 ms:
   - read active window info
   - apply privacy guard
   - optionally enrich browser metadata
   - extract focused-element or full-window text
   - update host tracker/history
   - append deduped live-capture output
   - send `WINDOW_NEW` or `WINDOW_UPDATE` over serial toward the Pico/Jetson path
4. On `Capture Text`:
   - selected text is copied from the active app
   - stored as `captured_text`
   - mirrored into `processed_text`
   - release becomes enabled
   - `[CAPTURED] ...` is appended to live capture
5. On `Release Text`:
   - the host uploads `processed_text` to the SPARK device through Raw HID
   - the host updates the release-output panel after the device acknowledges the upload

## Important File Ownership

- Main current app: `spark_app_v2.py`
- Legacy app path: `spark_app.py`
- Host context capture and persistence:
  - `host_pc/accessibility/`
  - `host_pc/db.py`
  - `host_pc/context.py`
- Host hardware communication:
  - `host_pc/raw_hid.py`
  - `host_pc/serial_sender.py`
  - `host_pc/hid/keyboard_hid.py`
- Shared protocol contract: `core/protocol.py`
- Jetson receiver/storage:
  - `jetson/receiver.py`
  - `jetson/db_manager.py`
- Pico relay reference: `pico/main.py`
- Architecture spec: `ENGINEERING_SPEC.md`

## Tests and Verification

The repo now has at least one tracked test target:

- `tests/test_live_capture.py`
  - Verifies deduped poll-line behavior and explicit capture-event visibility in `host_pc/live_capture.py`.

There is still no broad test suite, CI config, or packaging source manifest checked in.

## Current Understanding of What Is Active vs. Stale

### Active / trustworthy

- `ENGINEERING_SPEC.md`
- `spark_app_v2.py`
- `core/protocol.py`
- `host_pc/raw_hid.py`
- `host_pc/serial_sender.py`
- `host_pc/web_content.py`
- `jetson/receiver.py`
- `jetson/db_manager.py`
- `host_pc/live_capture.py`
- `pico/code.py` (includes JetsonTransport integration and autoreload)
- `lcd_screen_ui/` (React UI kit, see its own README)

### Older or only partially current

- `documentation_reference.md`
  - Focused on the older host-only app architecture.
  - Poll interval, flush threshold, and extension points are not aligned with the current rebased branch.
- `diagram.md`
  - Earlier architecture direction; not the best representation of the current single-Pico hub model.
- `spark_desktop.egg-info/PKG-INFO`
  - Generated metadata and likely stale relative to the tracked source.
- `README.md`
  - Minimal and not useful as onboarding.
- `host_pc/raw_hid_example.py`
  - Appears out of sync with the current `host_pc/raw_hid.py` API surface because it references listener/event APIs that are not present in the current client implementation.

## Important Observations

- This branch introduced a significant architecture expansion: the repo now spans desktop UI, shared protocol code, firmware-facing relay behavior, and a Jetson backend.
- `spark_app_v2.py` talks to the Pico through `SparkHIDClient` and `SerialSender`; that is the current compatibility target for the firmware.
- `spark_app.py` still uses `KeyboardHIDManager`, but that path is legacy and should not be treated as the current Pico contract.
- The hard-coded macOS `sys.path.insert(...)` remains in both app entrypoints and is still a portability smell.
- The current `requirements.txt` reflects the newer hardware path and now includes both `hidapi` and `pyserial`.

## Practical Mental Model

Think of the current project as four slices:

- Desktop host app: capture context, render UI, handle user actions.
- Device bridge: talk to the Pico over Raw HID and CDC serial.
- Shared protocol: define and parse packets consistently across nodes.
- Jetson receiver: persist and react to window sessions and button events.

If you are changing behavior, first decide which slice owns it. That is the fastest way to stay oriented in this repo.
