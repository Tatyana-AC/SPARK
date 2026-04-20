# SPARK Documentation Reference

This file is a developer lookup for the active SPARK runtime on the current branch.
It is centered on `spark_app_v2.py`, the CircuitPython Pico Hub flow, and the current
Jetson-owned persistence model.

## Core Data Flow

```text
Poll tick (every 125 ms in spark_app_v2.py)
  |
  +-- AccessibilityManager.get_active_window_info()
  +-- PrivacyGuard.is_safe(...)
  +-- get_browser_tab(app_name) when app_name is supported
  +-- host_pc/browser.py dispatches OS-specific tab metadata providers
  +-- on macOS: host_pc/web_content.py browser text extraction (live-tab for supported Safari/Chrome-family tabs)
  +-- on Windows: browser metadata from host_pc/browser_windows.py, live UIA extraction from host_pc/web_content_windows.py,
      then HTTP extraction for fetchable external pages when live extraction is weak
  +-- if browser extraction stays weak or noisy, evaluate get_focused_element_text() through Windows browser-noise heuristics
  +-- then evaluate get_window_text() through the same heuristics
  |
  +-- WindowContextTracker.update(info, text, source, tab)
  |     |
  |     +-- Same context_key? --> update current in-memory snapshot
  |     +-- Different context_key? --> move prior snapshot into in-memory history,
  |                                    set the new current snapshot,
  |                                    increment unique switch count
  |
  +-- LiveCaptureFeed.push_poll_line(...)
  +-- SerialSender.send_context_new(...) or send_context_update(...)
```

The host app's "Release Text" path is separate from the polling path:

```text
Capture Text
  -> AccessibilityManager.get_selected_text()
  -> captured_text / processed_text on the host
  -> Release Text
  -> SparkHIDClient.upload(AppCommand.SUBMIT_TEXT, processed_text)
  -> Pico STATUS reply
  -> local RELEASE OUTPUT panel update
```

The active release flow does not inject keyboard input back into the focused external app.

The current `Summarize Window` path is separate:

```text
Summarize Window
  -> AccessibilityManager.get_window_text()
  -> build_summary_request(...)
  -> SparkHIDClient.stream_round_trip_text(AppCommand.FEATURE_1, request)
  -> Pico forwards request to Jetson UART
  -> Jetson wraps the prompt and streams a response back
  -> Pico response buffer updates over Raw HID
  -> local RELEASE OUTPUT panel update
```

The visible app also has two debug summarize actions:

```text
Test Context
  -> build_test_summary_request()
  -> SparkHIDClient.stream_round_trip_text(AppCommand.FEATURE_1, request)
  -> local RELEASE OUTPUT panel update

Custom Context
  -> CustomContextDialog
  -> build_summary_request(...)
  -> SparkHIDClient.stream_round_trip_text(AppCommand.FEATURE_1, request)
  -> local RELEASE OUTPUT panel update
```

The current host app also exposes a Jetson DB debug surface:

```text
View Jetson DB
  -> create_snapshot_with_retry()
  -> open validated read-only snapshot copy
  -> list_user_tables()
  -> load_table_rows(..., limit=100, offset=...)
  -> render current page in JetsonDbViewerDialog
  -> optional Load More pagination
  -> delete_snapshot(...) when swapped or closed
```

Operational note:

- Before launching another SPARK app manually during debugging, close any older `spark_app_v2.py` processes first.
- Duplicate host app processes can contend for the same Pico Raw HID session and show up as `BUSY`, `read error`, or device-response timeouts during summarize requests.
- If a summarize request fails with a Raw HID timeout or the Pico appears connected but does not answer `GET_INFO`, do a physical Pico reset before trying software-side fixes. Soft reloads can recover some wedged runtime states, but they are not reliable enough to be the first recovery step.

## Where To Edit What

| You want to... | Edit this file | Look at... |
|---|---|---|
| Change poll speed | `spark_app_v2.py` | `SparkPanel.POLL_INTERVAL = 125` |
| Change privacy filtering | `spark_app_v2.py` | `PrivacyGuard` and `_on_poll_tick()` |
| Change text extraction order | `spark_app_v2.py`, `host_pc/browser.py`, `host_pc/web_content.py` | `_on_poll_tick()`, `get_browser_tab()`, `get_focused_element_text()`, `get_window_text()` |
| Change Windows browser live-extraction heuristics | `host_pc/web_content_windows.py` | `extract_windows_live_tab_text()`, `evaluate_focused_fallback()`, `evaluate_window_fallback()` |
| Add another browser integration | `host_pc/browser.py` | `BROWSER_APPS` and `get_browser_tab()` |
| Change Windows browser URL/title detection | `host_pc/browser_windows.py` | `_find_address_bar()`, `_read_address_bar_url()`, `get_active_browser_tab()` |
| Change what counts as a unique context | `host_pc/accessibility/base.py` | `WindowContextSnapshot.context_key` |
| Change in-memory context tracking | `host_pc/accessibility/tracker.py` | `WindowContextTracker.update()` and history accessors |
| Change snapshot relevance gating before serial sends | `host_pc/snapshot_policy.py` | `is_relevant_snapshot()`, `snapshot_fingerprint()` |
| Change Jetson-side persisted context shape | `jetson/db_manager.py` | `_create_tables()`, `on_context_new()`, `on_context_update()` |
| Change Jetson DB viewer snapshot/paging behavior | `spark_app_v2.py`, `host_pc/jetson_db_snapshot.py` | `JetsonDbViewerDialog`, `create_snapshot_with_retry()`, `load_table_rows()` |
| Change host panel position persistence | `spark_app_v2.py` | `QSettings` reads and writes for panel geometry |
| Change duplicate-launch protection | `host_pc/single_instance.py`, `spark_app_v2.py` | `SingleInstanceGuard`, `main()` |
| Change release output formatting | `host_pc/release_output.py` | `format_release_output()` |
| Change Raw HID upload / response-read behavior | `host_pc/raw_hid.py` | `SparkHIDClient.upload()`, `get_response_info()`, `fetch_response()`, `stream_round_trip_text()` |
| Change summarize request payload shape | `host_pc/summarize_stream.py` | `build_summary_request()` |
| Change the fixed test summarize payload | `host_pc/summarize_stream.py` | `build_test_summary_request()` |
| Change serial packet behavior | `host_pc/serial_sender.py` and `core/protocol.py` | `send_context_new()`, `send_context_update()`, packet builders |
| Change the Pico upload state machine | `pico/upload_protocol.py` | `UploadProtocolHandler` |
| Change the Pico UART summarize transport | `pico/jetson_transport.py` and `pico/code.py` | `JetsonTransport.start_request()`, `JetsonTransport.poll()` |
| Change the Jetson bridge or llama handoff | `jetson/pico_llm_bridge.py` | `handle_summarize_request()`, `_emit_summary_response()`, `run_bridge()` |
| Change Pico USB identity or HID descriptor | `pico/usb_config.py` and `pico/boot.py` | USB constants and `usb_hid.enable(...)` |
| Change deploy-to-board behavior | `tools/pico/deploy_to_pico.py` | `FIRMWARE_FILES`, `run_deploy()` |
| Change hotkeys | `host_pc/hotkeys.py` | `get_hotkey_config()` and `GlobalHotkeyManager` |
| Change the Windows launcher wrapper flow | `run_spark_setup_and_launch.ps1`, `run_spark_setup_and_launch.bat`, `setup_spark.ps1` | wrapper args and bring-up orchestration |
| Change UI test backend behavior | `tests/conftest.py` | `QT_QPA_PLATFORM` setup |

Windows hotkey note:
- Current Windows defaults are `Win+Alt+C` for capture, `Win+Alt+V` for release, and `Ctrl+F1` for toggle.

## File-By-File Summary

| File | Purpose |
|---|---|
| `spark_app_v2.py` | Active PyQt host panel, poll loop, privacy guard, live capture, release flow, and summarize UI |
| `host_pc/accessibility/base.py` | Shared dataclasses and `context_key` logic |
| `host_pc/accessibility/manager.py` | Cross-platform facade over macOS and Windows accessibility providers |
| `host_pc/accessibility/macos_provider.py` | macOS AX-based extraction and selection capture |
| `host_pc/accessibility/windows_provider.py` | Windows accessibility and text capture path |
| `host_pc/accessibility/tracker.py` | Current snapshot, previous-window history, and context-change detection |
| `host_pc/browser.py` | OS-dispatched browser metadata entrypoint (`get_browser_tab`) |
| `host_pc/browser_windows.py` | Windows browser tab metadata helper for title/URL extraction |
| `host_pc/jetson_db_snapshot.py` | Read-only snapshot creation, validation, and paging helpers for the Jetson DB viewer |
| `host_pc/context.py` | LLM-ready context object built from current snapshots |
| `host_pc/live_capture.py` | Live-capture line retention and poll-line dedupe |
| `host_pc/raw_hid.py` | Active host Raw HID upload client, response reader, and summarize stream poller |
| `host_pc/release_output.py` | Formatting for the local RELEASE OUTPUT panel |
| `host_pc/single_instance.py` | Single-instance guard used by `spark_app_v2.py` |
| `host_pc/snapshot_policy.py` | Filtering and fingerprinting helpers for deciding when a snapshot is worth serializing |
| `host_pc/summarize_stream.py` | Structured summarize-request payload builder |
| `host_pc/serial_sender.py` | Host CDC writer for `CONTEXT_NEW` / `CONTEXT_UPDATE` packets |
| `host_pc/web_content.py` | OS-aware browser text extraction helper used by poll loop |
| `host_pc/web_content_windows.py` | Windows-specific live-tab extraction heuristics and filtered accessibility fallbacks |
| `core/protocol.py` | Shared packet framing, CRC, builders, and streaming parser |
| `jetson/pico_llm_bridge.py` | Jetson-side UART broker, DB writer, and llama.cpp bridge |
| `jetson/receiver.py` | Compatibility wrapper to the active Jetson bridge entrypoint |
| `jetson/db_manager.py` | Rich-session Jetson SQLite store |
| `pico/boot.py` | Pico USB identity and interface configuration |
| `pico/code.py` | Active Pico runtime loop for CDC relay, Jetson summarize transport, and HID handling |
| `tools/monitoring/watch_full_stack.py` | Passive watcher for host, Pico, and Jetson logs |
| `tools/monitoring/pico_monitor.py` | Direct Pico HID/runtime monitor used by the watcher |
| `tools/pico/deploy_to_pico.py` | Cross-platform deploy helper for a mounted `CIRCUITPY` board |
| `run_spark_setup_and_launch.ps1` | Preferred Windows wrapper that delegates to `setup_spark.ps1` |
| `run_spark_setup_and_launch.bat` | Double-clickable wrapper for the PowerShell launcher |

## Key Data Models

### WindowInfo (`host_pc/accessibility/base.py`)

```python
@dataclass
class WindowInfo:
    title: str
    app_name: str
    process_name: str
    pid: int
    bundle_id: Optional[str] = None
    bounds: Optional[Dict[str, int]] = None
```

### WindowContextSnapshot (`host_pc/accessibility/base.py`)

```python
@dataclass
class WindowContextSnapshot:
    window_info: WindowInfo
    text: str
    source: TextSource
    tab_title: Optional[str] = None
    url: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def context_key(self) -> str:
        if self.url:
            return f"{self.window_info.app_name}|{self.url}"
        return f"{self.window_info.app_name}|{self.window_info.title}"
```

### Context (`host_pc/context.py`)

```python
@dataclass
class Context:
    app_name: str
    window_title: str
    tab_title: Optional[str]
    url: Optional[str]
    text: str
    source: str
    timestamp: float
    pid: int
```

## Jetson Database Schema (`jetson_spark.db`)

Table: `sessions`

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `context_key` | TEXT | Session identity derived from app and title or URL |
| `content_fingerprint` | TEXT | Stable content fingerprint for the current payload |
| `app_name` | TEXT | Active application name |
| `window_title` | TEXT | Window title when captured |
| `process_name` | TEXT | Process identifier |
| `pid` | INTEGER | Process ID |
| `source` | TEXT | `selected`, `focused_element`, or `full_window` |
| `tab_title` | TEXT | Browser tab title when available |
| `url` | TEXT | Browser URL when available |
| `text` | TEXT | Extracted text |
| `host_observed_at` | REAL | Host-side capture timestamp |
| `started_at` | REAL | First time this contiguous session was seen on Jetson |
| `updated_at` | REAL | Most recent refresh time for this session |

Table: `button_events`

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `button_id` | INTEGER | Physical Pico button index |
| `session_id` | INTEGER | Optional active session foreign key |
| `timestamp` | REAL | Event timestamp |

Today this table is populated only by sources that emit `PKT_BUTTON_PRESS` into the Jetson bridge. The Pico-local LCD button summarize path forwards `{"command": "summarize"}` directly and does not create a `button_events` row.

Host UI position is not stored in SQLite anymore. The active `spark_app_v2.py` path uses Qt `QSettings` for panel geometry.

## LLM Integration Notes

Two places are obvious extension points today:

1. `SparkPanel._on_summarize()` in `spark_app_v2.py`:
   The current button sends a structured summarize request to the Pico over Raw HID. The Pico forwards that request to Jetson and the host streams the Jetson response into `RELEASE OUTPUT`.
2. `SparkPanel._on_test_context()` and `SparkPanel._on_custom_context()` in `spark_app_v2.py`:
   These bypass accessibility extraction and send fixed or user-edited fake contexts through the same Jetson summarize pipeline.
3. `jetson/pico_llm_bridge.py`:
   Jetson now owns summarize prompt wrapping, llama.cpp HTTP calls, and response chunking for the real Pico UART path.

If a real model is added, those two places are the most direct integration points.

## Unique Switch Logic

A switch is counted when `WindowContextSnapshot.context_key` changes:

- Browsers: `"app_name|url"`
- Non-browsers: `"app_name|window_title"`

## Poll-loop behavior note

- For supported browser apps, the poll loop in `spark_app_v2.py` still follows this order:
  - Browser metadata lookup through `host_pc.browser`
  - Browser text extraction attempt first
  - On Windows, live UIA extraction first, then HTTP fallback for fetchable pages
  - If browser extraction is still weak, evaluate focused-element text through the Windows browser-noise heuristics
  - then evaluate full-window text through the same heuristics

The tracker keeps:

- one current snapshot
- up to two previous snapshots in memory
- no host-local persisted snapshot DB in the active `spark_app_v2.py` runtime
- duplicate `spark_app_v2.py` launches are rejected by `SingleInstanceGuard`

## Notes
- `pico/typeback.py` and its old typeback queue path were removed from the active CircuitPython runtime.
- The currently verified summarize path is Raw HID host<->Pico plus UART Pico<->Jetson.
- The current Jetson deployment target is the `demo/pico_bridge` folder. The repo `jetson/` directory is structured to be copied there directly.
