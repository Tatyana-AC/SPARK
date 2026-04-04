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

### 7. Re-enable palette writes while keeping highlight mutation disabled

To test whether visible feedback could safely come back through the existing cell palette, the runtime was changed to:

- keep `skip_highlight_update=False`
- temporarily set `LCD_SKIP_PALETTE_WRITE = False`

Result on hardware:

- pressing `PB1` crashed the Pico again
- no visible LCD feedback was observed before the crash
- CDC heartbeats stopped and the device later dropped off USB

Conclusion:

- first-press palette mutation is also unsafe in the integrated runtime

### 8. Fix the PB2/PB3 logical order

Observed hardware behavior showed that button indexes `1` and `2` were swapped relative to the physical labels.

Change made:

- `BUTTON_PIN_NUMBERS` updated from `(2, 4, 3, 5)` to `(2, 3, 4, 5)`

Status:

- code and tests were updated
- this is not fully hardware-validated yet because `PB1` crash experiments still blocked broader button verification

### 9. Replace append/remove with an always-attached highlight tile

The next visual-feedback experiment kept palette writes disabled and changed the highlight overlay behavior so the tile is:

- attached once during idle-screen construction
- moved in-place with `x/y` on press
- hidden offscreen instead of being removed from `root_group`

Result on hardware:

- pressing `PB1` produced `lcd:handle_press:after_press_time index=0`
- one additional heartbeat arrived afterward
- the LCD still did not visibly update before failure
- roughly 20 seconds later the Pico disconnected from USB

Conclusion:

- the initial in-place highlight move is safer than append/remove or palette writes, because the handler returns and the loop advances at least once
- however, the runtime still destabilizes later in the button-highlight lifecycle

### 10. Current one-variable experiment

The latest build on the branch keeps:

- `LCD_SKIP_PALETTE_WRITE = True`
- `LCD_SKIP_HIGHLIGHT_UPDATE = False`
- `LCD_SKIP_HIGHLIGHT_CLEAR = True`

Purpose:

- isolate whether the delayed crash is caused by the timeout clear path in `lcd_ui.tick()` rather than the initial in-place highlight move

Status:

- code and tests are updated for this experiment
- at the time of this note, this specific build had been deployed but not yet hardware-verified

## Final Finding

This is not an app-level debounce issue.

There is no explicit debounce window in our firmware:

- `pico/code.py` consumes `keypad.Keys(...)` events directly
- no custom cooldown or duplicate suppression is applied in the runtime loop

The real breakage is the runtime-time LCD feedback path, not debounce and not basic LCD startup.

Confirmed unsafe operations:

- cell palette mutation on press
- highlight `root_group.append/remove` mutation on press

Partially safer but still unresolved:

- moving an always-attached highlight tile in-place lets `handle_press()` complete and the loop continue briefly, but the integrated runtime still later wedges

What was ruled out:

- basic LCD startup/init
- standalone smoke-test bring-up
- first-press palette writes as a safe solution
- button-wrapper CDC debug messages
- generic CDC heartbeat output
- app-level debounce as the primary cause

## Current Runtime Workaround

The most recently hardware-verified stable build keeps the device stable by avoiding runtime LCD mutations that were shown to crash the board:

- `LCD_SKIP_PALETTE_WRITE = True`
- `LCD_SKIP_HIGHLIGHT_UPDATE = True`
- `BUTTON_EVENT_DEBUG_ENABLED = False`

The current branch head is a newer experiment, not yet fully verified on hardware. It keeps:

- `LCD_SKIP_PALETTE_WRITE = True`
- `LCD_SKIP_HIGHLIGHT_UPDATE = False`
- `LCD_SKIP_HIGHLIGHT_CLEAR = True`
- `BUTTON_PIN_NUMBERS = (2, 3, 4, 5)`

Temporary diagnostics currently remain in place:

- CDC heartbeat packets
- last CDC debug status capture
- last loop checkpoint capture in HID echo responses

## Recommended Next Steps

The next cleanup pass should:

1. hardware-test the current `skip_highlight_clear` branch build
2. if that still crashes, conclude that even the initial in-place highlight move is unsafe in the integrated runtime
3. preserve the corrected `BUTTON_PIN_NUMBERS = (2, 3, 4, 5)` mapping regardless of LCD outcome
4. remove the temporary heartbeat and loop-checkpoint diagnostics after the LCD path is settled
5. leave the standalone smoke test unchanged

If a visual button indication is still needed after the `skip_highlight_clear` test, the remaining safe direction is to drop integrated-runtime LCD feedback entirely or redesign it around an even less dynamic path than current `displayio` tile movement.

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
