# Pico LCD Purge Design

> Historical note (repo cleanup 2026-04-18): references below to `pico_reference/main.py` describe a reference sketch that existed when this design was written but was later removed from the repo.

## Summary

Remove the Pico-side LCD implementation entirely and make the physical pushbuttons inert in the active runtime. The Pico firmware should continue to support USB CDC relay, Raw HID commands, and Jetson UART summarize forwarding, but it should no longer import, deploy, initialize, or test any LCD-specific code.

## Goals

- Remove the active Pico LCD implementation from the repo-owned runtime.
- Ensure PB1-PB4 do absolutely nothing in the active firmware loop.
- Remove LCD-specific Pico tests.
- Remove Pico deploy references to LCD firmware files and LCD runtime libraries.
- Update active documentation so it no longer describes an LCD path as part of the current Pico runtime.

## Non-Goals

- Removing the standalone `lcd_screen_ui/` React prototype.
- Changing host Raw HID behavior, CDC relay behavior, or Jetson summarize behavior.
- Reworking unrelated Pico diagnostics unless they only exist for LCD/button debugging.

## Chosen Approach

Use a hard delete on the Pico LCD path.

This means:

- delete `pico/lcd_ui.py`
- delete `pico/lcd_smoke_test.py`
- delete `pico/pin_config.py` because it only carries LCD/button pin assignments for the purged path
- remove all LCD imports, setup, and tick/press handling from `pico/code.py`
- remove LCD firmware/runtime-library deployment expectations from `tools/pico/deploy_to_pico.py`
- delete LCD-focused Pico tests and adjust deploy/runtime tests that currently assert LCD or button-pin presence
- remove or rewrite active Pico documentation that still treats the LCD as part of the current runtime

This is preferred over leaving dormant files or no-op shims because the user asked for a complete purge and for the physical buttons to do nothing.

## Runtime Design

### `pico/code.py`

The active runtime loop becomes transport-only.

Changes:

- remove `LCD_DEBUG_CHECKPOINT`, `LCD_SKIP_PALETTE_WRITE`, `LCD_SKIP_HIGHLIGHT_UPDATE`, and `LCD_SKIP_HIGHLIGHT_CLEAR`
- remove LCD imports and `initialize_lcd_ui(...)` setup
- remove button queue draining that calls `lcd_ui.handle_press(...)`
- remove `lcd_ui.tick(now=...)` from the main loop
- remove button object construction if no button handling remains
- remove LCD/button-only debug paths that become dead after button handling is gone
- keep heartbeat, CDC relay, Raw HID handling, and Jetson transport intact

Result:

- PB1-PB4 are ignored by the runtime
- the firmware loop retains its non-LCD responsibilities unchanged

### Remaining button-only helpers

`pico/serial_bridge.py` still contains `inject_button_press(...)`, but after the purge there is no active runtime consumer for it.

Chosen direction:

- remove `inject_button_press(...)` and any Pico-local button packet helper that only exists to support physical button injection
- keep the shared protocol constants/builders in `core/protocol.py`, `jetson/protocol.py`, and `pico/protocol.py` unchanged for wire-compatibility and existing parser coverage
- after the purge, no active Pico runtime path or Pico helper should produce a `BUTTON_PRESS` packet

Result:

- no Pico-side runtime or helper module still claims an active button-injection path

### `pico_reference/main.py`

`pico_reference/main.py` cannot remain as-is because it imports `pin_config.py`, polls physical buttons, and emits `BUTTON_PRESS` packets.

Chosen direction:

- rewrite it as a transport-only behavioral reference that mirrors the post-purge runtime shape
- remove its button wiring section, button polling logic, and `pin_config.py` dependency

Result:

- the readable reference matches the new no-button, no-LCD runtime contract

## Deploy Design

### `tools/pico/deploy_to_pico.py`

Remove LCD-owned runtime assets from the default deployment bundle.

Changes:

- drop `lcd_ui.py` from `FIRMWARE_FILES`
- drop `pin_config.py` from `FIRMWARE_FILES`
- drop `adafruit_bus_device`, `adafruit_display_text`, and `adafruit_ili9341.py` from default runtime library paths if they are only needed by the LCD path
- keep existing HID-related runtime libraries and runtime ordering guarantees

Because the deploy helper exact-syncs `CIRCUITPY`, the purge must also preserve the stale-file cleanup behavior.

Required verification:

- tests must prove previously deployed LCD assets are deleted on redeploy
- tests must cover both removed firmware files and removed LCD runtime libraries

### Vendored LCD assets

The repo also contains cached LCD-only vendor assets under `tools/pico/vendor/`.

Chosen direction:

- delete `tools/pico/vendor/adafruit_ili9341.py`
- delete `tools/pico/vendor/adafruit_display_text/`
- delete `tools/pico/vendor/adafruit_bus_device/`

Result:

- the repo no longer carries Pico-side LCD runtime dependencies after the hard purge

Result:

- default deploys exact-sync the transport firmware only
- `CIRCUITPY` no longer carries LCD-specific code by default

## Test Design

### Delete

- `tests/test_pico_lcd_ui.py`
- `tests/test_pico_pin_config.py`

### Rewrite

- `tests/test_pico_code.py`
  - remove LCD/button expectations
  - keep transport/heartbeat/checkpoint coverage that still applies
- `tests/test_pico_deploy_to_pico.py`
  - remove assertions that the firmware bundle includes `lcd_ui.py`
  - remove assertions that the firmware bundle includes `pin_config.py`
  - remove assertions that default runtime libraries include LCD support
  - add coverage proving exact-sync deploy removes stale LCD firmware/library files from the target
- `tests/test_pico_serial_bridge.py`
  - remove button-injection tests tied to `inject_button_press(...)`
  - keep CDC relay coverage that still applies

## Documentation Design

Update active docs so they reflect the post-purge runtime.

Expected edits:

- `ENGINEERING_SPEC.md`
- `README.md`
- `REPO_STRUCTURE.md`
- `diagram.md`
- `documentation_reference.md`
- `docs/pico/README.md`
- `docs/pico/HARDWARE_SMOKE_TEST.md`
- `lcd_screen_ui/README.md`
- `pico_reference/main.py`

Historical investigation notes may stay if clearly historical, but active runtime docs should stop presenting LCD behavior as current functionality.

## Risks

- Deploy tests may fail if they still assume LCD library extraction.
- Some docs may still mention historical LCD work; active/runtime docs need careful distinction.
- If any hidden runtime dependency still imports LCD support indirectly, the purge will expose it quickly.

## Verification

- `python -m pytest tests/test_pico_code.py -q`
- `python -m pytest tests/test_pico_deploy_to_pico.py -q`
- `python -m pytest tests/test_pico_serial_bridge.py -q`
- run any remaining Pico-focused unit tests that touch the changed runtime/deploy surface
- verify no active code path imports `pico.lcd_ui` or `lcd_ui`
- redeploy to a real `CIRCUITPY` board and confirm stale LCD files are removed
- after deploy, press PB1-PB4 and confirm the runtime shows no LCD feedback and emits no button-side effect
