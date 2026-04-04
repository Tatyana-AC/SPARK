# Pico LCD Runtime Investigation 2026-04-03

## Scope

This note documents the real-hardware investigation into why the shared LCD UI worked in the standalone smoke test but broke the integrated Pico runtime when button handling was enabled.

## Environment

- Windows host workspace at `C:\SPARK`
- Pico mounted as `D:\` with filesystem label `CIRCUITPY`
- Pico CDC data port enumerated as `COM11`
- Custom USB VID/PID `0xC4C4:0x5350`
- CircuitPython `10.1.4` on Raspberry Pi Pico

## Original Symptom

- The standalone LCD smoke test worked.
- The integrated runtime booted and sent periodic heartbeats.
- Pressing a button caused the runtime to stall for roughly 10-20 seconds.
- During the stall, no further heartbeat packets arrived and later USB enumeration failed.
- The board often required a physical unplug/replug to come back.

## Important Early Finding

Deploying to `D:\` was not enough to switch the active runtime after `code.py` changed.

- `pico/code.py` disables CircuitPython autoreload.
- Copying new files updated the on-disk firmware but did not replace the running code.
- A physical Pico reset was required before any newly deployed diagnostic build was actually live.

This explained several early false negatives while monitoring CDC output.

## Investigation Steps

### 1. Confirm shared startup path

Compared `pico/lcd_smoke_test.py` and `pico/code.py`.

- Both call the same `initialize_lcd_ui(...)` entry point.
- This made plain LCD bring-up a weaker suspect than runtime-time button/display updates.

### 2. Check palette mutation hypothesis

The runtime already had `LCD_SKIP_PALETTE_WRITE = True`, but the skip was incomplete.

- `pico/lcd_ui.py` still wrote the previous cell palette on a second press.
- `pico/lcd_ui.py` still wrote the active cell palette during timeout clear in `tick()`.

Work performed:

- added regression tests covering second-press and timeout-clear skip mode
- patched skip mode so all palette writes are suppressed when the debug/runtime workaround is active

Result:

- this fixed a real gap in the workaround
- but the Pico still crashed on the first button press on hardware

Conclusion:

- palette writes were not the remaining first-press root cause

### 3. Verify CDC debug path separately

Added a temporary heartbeat over `usb_cdc.data` and built a local watcher:

- `watch_pico_cdc_debug.py`
- `watch_pico_cdc_debug.cmd`

Result after a physical reset:

- heartbeat packets streamed normally over CDC
- HID remained responsive

Conclusion:

- generic CDC debug output was healthy
- the runtime was not dead at startup

### 4. Remove button-path CDC wrappers as a variable

Disabled the explicit button wrapper debug messages:

- no `PBx pressed`
- no `PBx done`

Heartbeat remained enabled.

Result:

- pressing `PB1` still stalled the runtime and later dropped the device from USB

Conclusion:

- the crash was not caused by those outer button debug writes

### 5. Narrow to the first remaining LCD mutation

At that point the first-press path had already removed palette writes and outer button debug wrappers.

The main remaining LCD-side mutation on the first press was the highlight overlay update:

- `_set_highlight(...)` removes/re-appends `_highlight_grid` on `root_group`

Relevant code path:

- `pico/lcd_ui.py:132-142`
- called from `pico/lcd_ui.py:163` in `handle_press()`

### 6. Disable highlight updates in the runtime path

Added a debug/runtime flag to suppress highlight overlay mutation:

- `skip_highlight_update=True`
- wired from `pico/code.py` via `LCD_SKIP_HIGHLIGHT_UPDATE = True`

Result on hardware:

- after reset, pressing `PB1` no longer crashed the Pico
- CDC log showed `lcd:handle_press:after_press_time index=0`
- heartbeats continued after the press
- HID query returned:

```text
PICO ECHO: diag
CDC DEBUG: heartbeat|sent:27
LOOP CHECKPOINT: after_response_sync
```

Conclusion:

- disabling highlight updates made the integrated runtime stable
- the board survived the first press and kept running the main loop

## Final Finding

This is not an app-level debounce issue.

There is no explicit debounce window in our firmware:

- `pico/code.py` consumes `keypad.Keys(...)` events directly
- no custom cooldown or duplicate suppression is applied in the runtime loop

The real breakage is the runtime-time LCD highlight mutation, specifically dynamic `displayio` scene-graph mutation on button press.

Most likely trigger:

- `pico/lcd_ui.py:_set_highlight()` removing and appending `_highlight_grid` on `root_group`

What was ruled out:

- basic LCD startup/init
- standalone smoke-test bring-up
- first-press palette writes
- button-wrapper CDC debug messages
- generic CDC heartbeat output
- app-level debounce as the primary cause

## Current Runtime Workaround

The current runtime diagnostic build keeps the device stable by avoiding runtime LCD mutations that were shown to crash the board:

- `LCD_SKIP_PALETTE_WRITE = True`
- `LCD_SKIP_HIGHLIGHT_UPDATE = True`
- `BUTTON_EVENT_DEBUG_ENABLED = False`

Temporary diagnostics currently remain in place:

- CDC heartbeat packets
- last CDC debug status capture
- last loop checkpoint capture in HID echo responses

## Recommended Next Steps

The next cleanup pass should:

1. remove the temporary heartbeat and loop-checkpoint diagnostics
2. keep the runtime stable by leaving highlight updates disabled
3. leave the standalone smoke test unchanged
4. keep a short code comment explaining why runtime highlight updates are disabled on real hardware

If a visual button indication is needed later, redesign it so all display objects are attached at startup and only existing state changes at runtime. Avoid `root_group.append(...)` / `root_group.remove(...)` on press in the integrated runtime.

## Files Touched During Investigation

- `pico/code.py`
- `pico/lcd_ui.py`
- `pico/pico_debug.py`
- `tests/test_pico_code.py`
- `tests/test_pico_lcd_ui.py`
- `tests/test_watch_pico_cdc_debug.py`
- `watch_pico_cdc_debug.py`
- `watch_pico_cdc_debug.cmd`

## Verification Used

Relevant automated checks run during the investigation:

- `python -m pytest tests/test_pico_code.py -q`
- `python -m pytest tests/test_pico_lcd_ui.py -q`
- `python -m pytest tests/test_pico_runtime_runner.py -q`
- `python -m pytest tests/test_watch_pico_cdc_debug.py -q`

Relevant on-device observations:

- heartbeat traffic over `COM11`
- HID ping/echo responses via `host_pc.raw_hid.SparkHIDClient`
- repeated physical reset requirement after `code.py` deploys because autoreload is disabled
