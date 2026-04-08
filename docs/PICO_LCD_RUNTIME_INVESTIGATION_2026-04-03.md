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

## 2026-04-05 Baseline Reproduction Addendum

The exact historical standalone smoke test from commit `766b8d8` was restored onto the current board to answer a narrower question: does the original smoke test still reproduce on today's CircuitPython environment before any integrated-runtime work is attempted?

### Result

- The exact restored `766b8d8` smoke test did **not** reproduce as-is on CircuitPython `10.1.4`.
- The LCD stayed white.
- PB1-PB4 showed no visible effect.
- The Pico stayed connected and did not wedge.

### Evidence gathered

To avoid guessing, a wrapper and then a startup probe were used around the preserved historical script.

The first probe trace showed:

```text
[1.481] === run start reset=ok ===
[1.581] startup begin
[2.148] imports ready
[2.194] display release
[2.244] SPI object ready
[2.292] exception AttributeError: 'module' object has no attribute 'FourWire'
```

This proves the first reproduction failure happened before `ILI9341(...)` setup completed. The issue was not button handling, not display mutation, and not the later integrated runtime crash path.

### Minimal compatibility test

The smallest possible probe change was then applied:

- keep the historical smoke-test structure and pins the same
- replace `displayio.FourWire(...)` with `from fourwire import FourWire` and `FourWire(...)`

Hardware result after that one API change:

- the LCD UI appeared
- PB1-PB4 highlighted correctly
- the standalone path behaved like a working smoke test again

### Clean deployable smoke demo

After the compatibility finding was confirmed, a non-diagnostic current-compatible smoke demo was prepared for normal use:

- `pico/lcd_smoke_test_current.py`
- keeps the standalone 4-button UI behavior
- uses `from fourwire import FourWire`
- rotates the display clockwise by 90 degrees from the prior working probe angle, using `rotation=180`
- removes the wrapper/probe trace logic that had temporarily taken ownership of the CIRCUITPY filesystem

Hardware result with the clean smoke demo deployed as `code.py`:

- the rotation is correct
- PB1-PB4 still highlight correctly
- the Pico remains writable from the host while the demo is running

### Shared-module extraction step

The next recovery-branch reintegration step extracted the clean standalone path into shared modules without touching the active runtime:

- `pico/pin_config.py`
- `pico/lcd_ui.py`
- `pico/lcd_smoke_test_current.py` updated to import those modules
- `pico/code.py` intentionally left unchanged
- preserved historical baseline `pico/lcd_smoke_test.py` intentionally left unchanged

Hardware result after deploying the refactored standalone bundle:

- the rotated UI still looks correct
- PB1-PB4 still highlight correctly
- the Pico remains writable from the host while the refactored standalone bundle is running

### Active runtime idle-screen rung

The next reintegration rung reintroduced LCD initialization into `pico/code.py` without restoring button handling.

Properties of this rung:

- `pico/code.py` initializes the LCD once during startup
- the active runtime loop remains transport/HID-only
- no `keypad` import yet
- no button-driven LCD feedback yet

Hardware result after deploying the active runtime bundle manually to `CIRCUITPY`:

- the idle LCD screen appears during runtime boot
- PB1-PB4 do nothing, as intended for this rung
- the board stays healthy after boot

Host-side transport verification on the same rung:

- Raw HID client connected successfully
- `get_info()` returned protocol version `2`, chunk payload size `27`, max upload bytes `4096`
- `ping()` returned `OK` with detail `spark ready`

### Active runtime button-logging rung

The next reintegration rung enabled PB1-PB4 queue draining inside the active runtime without restoring any LCD mutation or transport-side button injection.

Properties of this rung:

- `keypad` is initialized from `BUTTON_PIN_NUMBERS`
- pressed buttons are emitted to the debug channel only
- no `serial_bridge.inject_button_press()` path
- no `lcd_ui.handle_press()` or `lcd_ui.tick()` calls in the runtime loop yet

Hardware result after reset and PB1/PB2 presses:

- the LCD stayed on the idle screen
- the board remained healthy
- Raw HID transport still answered `ping()` with `OK spark ready`

CDC debug capture over `COM10` showed the button events directly:

```text
[12:51:53] DEBUG button:PB1
[12:51:53] DEBUG button:PB2
```

This makes the button-logging-only rung the highest verified active-runtime state so far.

### Active runtime visual-feedback rung

The next reintegration rung threaded the shared LCD UI object into the active runtime loop and restored button-driven visual feedback:

- `_drain_button_events(..., ui, now=...)` called `ui.handle_press(...)`
- `_run_main_loop_iteration(..., ui=...)` called `ui.tick(now=...)`
- transport-side button injection still remained disabled

Observed result on hardware:

- runtime boot still showed the idle screen correctly
- pressing `PB1` disconnected or wedged the board immediately

Additional evidence:

- startup itself remained clean; no `runtime_error.txt` was produced
- the device re-enumerated afterward and Raw HID became visible again
- a post-repro Raw HID round-trip still worked once the board came back
- a 10-second CDC debug capture with a deliberate `PB1` press showed only heartbeat packets and never emitted a visible `button:PB1` packet before disconnect

This reproduces the same high-level failure boundary as the earlier LCD investigation: the active runtime remains stable until button-driven LCD feedback is reintroduced.

### Runtime auto-visual probe

One final isolating experiment removed the button path entirely and triggered the same LCD highlight automatically a short time after runtime boot.

Observed result:

- the LCD went full white on its own without any button input

Follow-up state checks after that white-screen event:

- `CIRCUITPY` still mounted
- the Raw HID interface still enumerated
- but `ping()` timed out instead of returning `spark ready`
- a CDC debug capture showed no packets at all in the stalled white-screen state

That is the strongest evidence gathered so far: on this hardware/software stack, active-runtime LCD mutation itself is sufficient to corrupt or stall the runtime even when button handling is removed from the triggering path.

### Isolated bridge-mode renderer proof spike

As the first redesign validation step, the recovery worktree introduced an isolated bridge-mode LCD proof spike that:

- booted directly into a temporary `lcd_bridge_spike.py`
- initialized a new bridge-mode SPI renderer backend instead of the integrated `displayio` runtime path
- auto-triggered one visual update without involving the full bridge runtime or button input

Observed result on hardware:

- the LCD stayed stable after the automatic visual update
- no immediate white-screen failure occurred
- no visible disconnect occurred
- the temporary proof spike did not yet render the action text labels, so the screen lost text during this minimal validation path

This is the first positive hardware evidence that a non-`displayio` runtime renderer may avoid the earlier integrated-runtime failure boundary. It does not prove the full bridge + interactive LCD design yet, but it justifies continuing with the architecture redesign instead of abandoning the integrated target immediately.

### Conclusion

The restored standalone demo failed on today's board because of CircuitPython API drift, not because the LCD wiring or the original smoke-test concept was fundamentally broken.

This changes the interpretation of the historical branch:

- the coworker's standalone demo can still be treated as a real working baseline concept
- reproducing it on the current board requires at least the `FourWire` API update
- the separate integrated-runtime crashes investigated above remain a different problem from this baseline reproduction failure

## 2026-04-07 Redesign Validation Addendum

The later bridge-mode redesign initially looked stuck again because the new runtime would white-screen or appear to stop before bridge-mode validation could advance. That diagnosis was incomplete.

### Actual first redesign blocker

The first real blocker in the redesigned runtime was not SPI initialization, not the new bridge renderer, and not the first bridge-mode press render.

It was a missing CircuitPython module:

- `pico/lcd_state.py` imported `dataclasses`
- this CircuitPython `10.1.4` build on the Pico does not provide `dataclasses`
- importing `lcd_ui` therefore failed before the redesigned bridge runtime could finish booting

This was proven with a minimal on-device import probe deployed as `code.py` and captured live over the USB console port:

```text
probe:version:lcd-ui-import-probe-v1
probe:name:__main__
probe:import:lcd_ui:start
probe:import:lcd_ui:error:ImportError:no module named 'dataclasses'
...
File "lcd_state.py", line 1, in <module>
ImportError: no module named 'dataclasses'
```

Minimal fix applied:

- removed `from dataclasses import dataclass` from `pico/lcd_state.py`
- replaced the frozen dataclass with a small plain `LcdStateChange` value object

### Post-fix hardware ladder

After removing the `dataclasses` dependency, the redesigned path was re-validated on real hardware in progressively larger rungs.

Verified in order:

1. `lcd_ui` import probe succeeded and stayed alive
2. `initialize_lcd_ui(mode="bridge")` succeeded and stayed alive
3. one synthetic `ui.handle_press(0, now=...)` succeeded and stayed alive
4. one delayed `ui.tick(now=...)` clear after the synthetic press also succeeded and stayed alive

Live renderer/debug evidence from the bridge-init probe included:

```text
lcd_ui:bridge:init:start
lcd_ui:bridge:init:renderer-imported
lcd_renderer:init:start
lcd_renderer:init:spi
lcd_renderer:init:pins
lcd_renderer:init:target
lcd_renderer:init:renderer
lcd_renderer:init:idle-layout
lcd_ui:bridge:init:renderer-ready
```

This proved that the redesigned bridge renderer can:

- boot cleanly
- render the idle layout
- render a first highlighted button state
- clear that highlight later through the normal tick path

### Actual runtime restored

After the probe ladder passed, the real redesigned runtime bundle was redeployed to the Pico:

- `pico/code.py`
- `pico/bridge_app.py`
- `pico/bridge_runtime.py`
- `pico/button_input.py`
- `pico/lcd_ui.py`
- `pico/lcd_renderer_spi.py`
- `pico/lcd_state.py`
- related support modules

Hardware result after reset:

- the board stayed up on the actual runtime
- repeated `heartbeat` CDC debug packets arrived from `BridgeRuntime`
- the LCD stayed initialized in bridge mode

### End-to-end host communication validation

With the actual runtime deployed, the host-side SPARK setup and smoke flow was rerun.

Observed result from `setup_spark.ps1`:

- `connected: true`
- `ping_ok: true`
- `smoke_ok: true`
- streamed response updates arrived incrementally
- `spark_app_v2.py` launched successfully

This proves the redesigned runtime still supports the HID upload path and Jetson-backed response flow.

### Concurrent UI + communication validation

One final real-world validation window exercised both sides together:

- actual runtime running on Pico
- live host-side HID/Jetson request in progress
- physical PB button presses during the same window

Observed result:

- host-side request succeeded and returned a full streamed response
- the Pico stayed alive throughout
- the LCD UI visibly reacted to the physical button presses

This is the first full hardware confirmation that the redesign target is now working:

- interactive LCD updates
- active bridge/runtime loop
- host app communication

all coexist on the same Pico runtime without reproducing the old crash boundary.

### Current status

The redesigned runtime is now past the earlier failure boundary.

What is now hardware-verified:

- bridge-mode LCD init
- bridge-mode idle render
- runtime-driven highlight render
- runtime-driven highlight clear
- actual `BridgeRuntime` heartbeat loop
- host `PING` / upload / streamed response path
- visible physical button reaction while the runtime and host communication remain active

Temporary debug-oriented changes still remain in the working runtime for observability, especially:

- `boot.py` currently enables `usb_cdc.enable(console=True, data=True)`
- several temporary probe scripts remain in the recovery worktree for rung-by-rung hardware checks

The next cleanup phase should focus on reducing temporary diagnostics and deciding what should remain in the final runtime bundle.

## 2026-04-08 Software Status Note

- The current worktree software routes the Pico-local LCD `PB1` summarize action through the bridge runtime and forwards `{"command": "summarize"}` directly instead of relying on Jetson-side `PKT_BUTTON_PRESS` ingestion.
- Targeted regression coverage for that path passed in this environment.
- No fresh deploy or on-device hardware validation was performed here, so manual validation of the physical LCD/button summarize flow remains pending.

## Removed Worktree Note

An unmerged experimental worktree named `pico-lcd-redesign` was later inspected and intentionally discarded.

That abandoned worktree contained:

- a larger LCD-state / renderer refactor in `pico/lcd_ui.py`
- startup and button debug changes in `pico/code.py` that re-enabled more CDC logging
- broader test rewrites in `tests/test_pico_code.py` and `tests/test_pico_lcd_ui.py`
- a small fake-serial helper adjustment in `tests/test_serial_sender.py`

It was not merged because the work was incomplete, unverified on hardware, and diverged from the narrower step-by-step hardware investigation documented above.

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
