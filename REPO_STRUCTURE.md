# SPARK Repo Structure Notes

## What This Repo Is

SPARK is no longer just a desktop capture panel. On the current `sida` branch, it is a distributed three-node system:

- Host PC app: PyQt desktop app that captures desktop context, tracks window state in memory, talks to hardware, and renders local UI state.
- Pico Hub: RP2040/CircuitPython device that exposes custom Raw HID and USB CDC serial, bridging context packets toward Jetson and accepting HID uploads from the host.
- Jetson Brain: UART bridge plus SQLite store for rich context sessions, button events, and summarize handling.

The current codebase is best understood as a host application plus protocol and hardware integration layers.

## Top-Level Layout

```text
SPARK/
|- spark_app_v2.py                 # Active host UI and hardware-integrated desktop panel
|- run_spark_setup_and_launch.ps1  # Preferred Windows wrapper around setup_spark.ps1
|- run_spark_setup_and_launch.bat  # Double-clickable wrapper for the PowerShell launcher
|- host_pc/                        # Host-side runtime package
|  |- accessibility/               # Cross-platform text capture
|  |- browser.py                   # OS-dispatched browser metadata entrypoint
|  |- browser_windows.py           # Windows browser tab metadata helper
|  |- context.py                   # LLM-friendly host context object
|  |- jetson_db_snapshot.py        # Read-only Jetson DB snapshot helpers for the viewer dialog
|  |- hotkeys.py                   # Global hotkeys
|  |- live_capture.py              # Live-capture feed dedupe helper
|  |- raw_hid.py                   # Raw HID upload client for SPARK device
|  |- serial_sender.py             # CDC serial sender to Pico Hub / Jetson path
|  |- single_instance.py           # Single-instance guard for the active app
|  |- snapshot_policy.py           # Snapshot relevance/fingerprinting helpers
|  |- web_content.py               # OS-aware browser text extractor
|  `- web_content_windows.py       # Windows browser live-tab heuristics and fallback filters
|- core/                           # Shared wire protocol builder/parser and app log contract
|- jetson/                         # Deployable Jetson bridge bundle and DB layer
|- pico/                           # Pico-runnable CircuitPython runtime files and smoke helpers
|- tools/
|  |- diagnostics/                 # One-off Pico / Jetson investigation helpers
|  |- macos/                       # macOS setup helpers
|  |- monitoring/                  # Passive watcher and Pico runtime monitor scripts
|  `- pico/                        # Host-side Pico deploy tooling and vendor cache
|- lcd_screen_ui/                  # React/Vite LCD workflow UI kit for the ILI9341 target
|- tests/                          # Focused unit tests
|- ENGINEERING_SPEC.md             # Best architecture source of truth
|- documentation_reference.md      # Current developer lookup for host behavior and extension points
|- diagram.md                      # Current three-node architecture diagram
|- requirements.txt                # Current Python dependencies
|- spark.db                        # Older host runtime artifact; not used by the active V2 path
`- docs/pico/assets/pin_layout.png # Hardware wiring reference asset
```

## Architecture Summary

### 1. Host Node

The host node is the user-facing desktop application.

- `spark_app_v2.py`
  - Main active entrypoint.
  - Runs a 125 ms polling loop.
  - Captures active-window context through `AccessibilityManager`.
  - Refuses duplicate launches through `SingleInstanceGuard`.
  - Updates in-memory context state via `WindowContextTracker`.
  - Maintains a deduped live-capture feed via `LiveCaptureFeed`.
  - Persists host window position through `QSettings`.
  - Exposes `View Jetson DB`, which reads a validated snapshot copy of the Jetson database and pages rows in the UI.
  - Sends host context packets over serial to the Pico Hub using `SerialSender`.
  - Uploads release text to the SPARK device over Raw HID using `SparkHIDClient`.
  - Shows accepted release output locally in the UI after device acknowledgment.
  - Shows device connection state in the panel header.
  - Sends `Summarize Window` requests over Raw HID and streams Jetson responses into `RELEASE OUTPUT` through a second 125 ms response poll timer.
### 2. Shared Protocol Layer

- `core/protocol.py`
  - Defines the SPARK wire protocol.
  - Builds:
    - `CONTEXT_NEW` (`0x01`)
    - `CONTEXT_UPDATE` (`0x02`)
    - `SUMMARIZE_REQUEST` (`0x03`)
    - `SUMMARIZE_CHUNK` (`0x04`)
    - `SUMMARIZE_DONE` (`0x06`)
    - `ERROR` (`0x07`)
  - Implements packet framing:
    - magic bytes `SP`
    - packet type
    - little-endian payload length
    - payload
    - CRC-8/MAXIM
  - Uses versioned JSON bodies for structured packets.
  - Also contains `PacketParser`, which the Pico and Jetson bridge use to decode the serial stream.

### 3. Pico Hub Layer

- `pico/boot.py`
  - CircuitPython USB bootstrap.
  - Sets the SPARK USB identity and enables:
    - one USB CDC data interface
    - one custom Raw HID interface
- `pico/code.py`
  - Active CircuitPython runtime loop.
  - Relays CDC host packets continuously, forwards `FEATURE_1` summarize requests to Jetson UART, and exposes the streamed Jetson response back over Raw HID.
- `pico/jetson_transport.py`
  - Transport-only Pico helper for framed summarize requests, response buffering, and completion state.
- `pico/upload_protocol.py`
  - Pure-Python implementation of the V2 upload protocol state machine and host-readable response buffer metadata.
- `pico/serial_bridge.py`
  - CDC-to-UART relay helper.
- `ENGINEERING_SPEC.md`
  - The real source of truth for the distributed architecture and the CircuitPython-based single-Pico design.

### 4. Jetson Layer

- `jetson/pico_llm_bridge.py`
  - Deployable Jetson bridge entrypoint.
  - Owns the UART, persists context to SQLite, and forwards summarize requests to the local llama.cpp OpenAI-compatible server.
- `jetson/receiver.py`
  - Compatibility wrapper to the active bridge entrypoint.
- `jetson/db_manager.py`
  - Rich-session SQLite store for the Jetson side.
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
  - Keeps current and prior snapshots in memory only.
  - Provides the `context_key` logic used to detect window changes.

### Host-Side Supporting Modules

- `browser.py`
  - OS-dispatched browser metadata entrypoint for supported desktop browsers.
- `browser_windows.py`
  - Windows browser tab metadata helper used by `host_pc.browser`.
- `jetson_db_snapshot.py`
  - Creates validated read-only snapshot copies of `jetson_spark.db`.
  - Provides deterministic table listing and bounded row paging for the viewer dialog.
- `web_content.py`
  - OS-aware browser text extractor for supported macOS/Windows browser tabs.
  - Uses live-tab extraction with HTTP fallback depending on platform and URL.
- `web_content_windows.py`
  - Windows-specific live-tab extraction heuristics.
  - Rejects browser chrome noise before accepting focused-element or full-window fallback text.
- `context.py`
  - LLM-ready host context object.
- `hotkeys.py`
  - Global hotkey listener.
  - Current Windows defaults: `Win+Alt+C` for capture, `Win+Alt+V` for release, and `Win+Alt+Space` for window toggle.
  - Avoid `Alt+Space`-based bindings on Windows because `Alt+Space` opens the active window system menu.
  - If a local Windows setup must suppress that effect, the current documented workaround is an AutoHotkey rule: `#!Space::return`.
- `live_capture.py`
  - Small helper extracted from V2 to manage live-capture display lines.
  - Important behavior: dedupes repeated poll entries, but still allows explicit event entries like `[CAPTURED] ...`.
- `single_instance.py`
  - Cross-platform guard that prevents duplicate `spark_app_v2.py` launches.
- `snapshot_policy.py`
  - Filters low-value snapshots and fingerprints repeated browser captures before `CONTEXT_NEW` / `CONTEXT_UPDATE` sends.

### Hardware / Device Communication

- `raw_hid.py`
  - Synchronous Raw HID client used by `spark_app_v2.py`.
  - Talks directly to the SPARK device for:
    - capability query
    - upload begin/chunk/commit
    - text submission
- `serial_sender.py`
  - Sends protocol packets to the Pico CDC serial interface.
  - Used by V2 to emit `CONTEXT_NEW` on context change and `CONTEXT_UPDATE` while the same context remains active.

## Current Runtime Flow

The main V2 app flow is now:

1. `spark_app_v2.py` starts the Qt panel.
2. It creates:
   - `AccessibilityManager`
   - `GlobalHotkeyManager`
   - `WindowContextTracker`
   - `SparkHIDClient`
   - `SerialSender`
   - `LiveCaptureFeed`
   - `WebContentExtractor`
3. Every 125 ms:
    - read active window info
    - ignore the SPARK panel, watcher, and Jetson DB viewer windows
    - apply privacy guard
    - optionally enrich browser metadata
    - try browser extraction for supported tabs
    - on Windows, prefer live UIA page extraction and then HTTP fallback for fetchable external pages
    - if browser extraction stays noisy, evaluate focused-element text through Windows browser heuristics
    - fallback to full-window text if needed, again through the same Windows heuristics for browsers
    - note: this is the unchanged poll-loop fallback order in `spark_app_v2.py`
    - update in-memory host tracker/history
   - append deduped live-capture output
   - send `CONTEXT_NEW` or `CONTEXT_UPDATE` over serial toward the Pico/Jetson path
4. On `Capture Text`:
   - selected text is copied from the active app
   - stored as `captured_text`
   - mirrored into `processed_text`
   - release becomes enabled
   - `[CAPTURED] ...` is appended to live capture
5. On `Release Text`:
   - the host uploads `processed_text` to the SPARK device through Raw HID
   - the host updates the release-output panel after the device acknowledges the upload
6. On `Summarize Window`:
   - the host builds a structured summarize request from the current active window
   - the host sends it to the Pico through Raw HID `FEATURE_1`
   - the Pico forwards that request to Jetson over framed UART packets and buffers the streamed response
   - the host polls the Pico response buffer and updates the release-output panel incrementally

## Important File Ownership

- Main current app: `spark_app_v2.py`
- Windows launch wrappers:
  - `run_spark_setup_and_launch.ps1`
  - `run_spark_setup_and_launch.bat`
- Host context capture and in-memory state:
  - `host_pc/accessibility/`
  - `host_pc/context.py`
  - `host_pc/snapshot_policy.py`
- Host hardware communication:
  - `host_pc/raw_hid.py`
  - `host_pc/serial_sender.py`
- Host browser extraction helpers:
  - `host_pc/browser.py`
  - `host_pc/browser_windows.py`
  - `host_pc/web_content.py`
  - `host_pc/web_content_windows.py`
- Monitoring tools:
  - `tools/monitoring/watch_full_stack.py`
  - `tools/monitoring/pico_monitor.py`
- Jetson DB viewer support:
  - `host_pc/jetson_db_snapshot.py`
- Shared protocol contract: `core/protocol.py`
- Jetson receiver/storage:
  - `jetson/pico_llm_bridge.py`
  - `jetson/receiver.py`
  - `jetson/db_manager.py`
- Architecture spec: `ENGINEERING_SPEC.md`

## Tests and Verification

The repo now has a focused unit test suite covering the active host/device contract:

- `tests/test_pico_serial_bridge.py`
- `tests/test_browser.py`
- `tests/test_browser_windows.py`
- `tests/test_web_content.py`
- `tests/test_web_content_windows.py`
- `tests/test_jetson_db_snapshot.py`
- `tests/test_jetson_db_viewer_ui.py`
- `tests/test_serial_sender.py`
- `tests/test_windows_provider.py`
- `tests/test_spark_panel_ui.py`
- `tests/test_tracker_persistence.py`
- `tests/test_jetson_db.py`
- `tests/test_watch_full_stack.py`
- `tests/conftest.py` forces Qt into `offscreen` mode during pytest collection so the UI suite can run headlessly on Windows.

There is still no CI configuration checked in, but the repo is no longer in a "single test file" state.

## Current Understanding of What Is Active vs. Stale

### Active / trustworthy

- `README.md`
- `ENGINEERING_SPEC.md`
- `diagram.md`
- `documentation_reference.md`
- `spark_app_v2.py`
- `core/protocol.py`
- `host_pc/raw_hid.py`
- `host_pc/serial_sender.py`
- `jetson/pico_llm_bridge.py`
- `jetson/receiver.py`
- `jetson/db_manager.py`
- `host_pc/live_capture.py`

## Important Observations

- This branch introduced a significant architecture expansion: the repo now spans desktop UI, shared protocol code, firmware-facing relay behavior, and a Jetson backend.
- `spark_app_v2.py` talks to the Pico through `SparkHIDClient` and `SerialSender`; that is the current compatibility target for the firmware.
- The hard-coded macOS `sys.path.insert(...)` remains in both app entrypoints and is still a portability smell.
- The current `requirements.txt` reflects the newer hardware path and now includes both `hidapi` and `pyserial`.
- The currently verified summarize path is Raw HID host<->Pico plus UART Pico<->Jetson, and direct framed CDC summarize packets can also be used for hardware debugging.

## Practical Mental Model

Think of the current project as four slices:

- Desktop host app: capture context, render UI, handle user actions.
- Device bridge: talk to the Pico over Raw HID and CDC serial.
- Shared protocol: define and parse packets consistently across nodes.
- Jetson bridge: persist and react to window sessions, button events, and summarize requests.

If you are changing behavior, first decide which slice owns it. That is the fastest way to stay oriented in this repo.
