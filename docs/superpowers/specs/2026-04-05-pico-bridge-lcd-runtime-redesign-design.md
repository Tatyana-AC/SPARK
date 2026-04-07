# Pico Bridge + LCD Runtime Redesign Design

## Summary

Redesign the Pico firmware so it can run the SPARK communication bridge and an interactive LCD UI at the same time without coupling runtime bridge behavior to runtime `displayio` mutation. The new design keeps the current HID/UART bridge contract, moves `pico/code.py` to a composition-root role, and replaces the integrated LCD runtime path with a renderer backend that is safe to update while the bridge loop is active.

## Context

The current safe production path on `sida` is the transport-only Pico runtime. The recovery worktree proved the following hardware boundaries:

- the standalone LCD demo works when it owns the whole board runtime
- the integrated runtime can boot an idle LCD screen safely
- the integrated runtime can drain and log button presses safely
- any integrated-runtime LCD visual mutation after boot destabilizes the runtime

The strongest evidence came from an automatic runtime-side visual probe: even with no button input, the active bridge runtime turned the LCD full white when the runtime triggered a highlight update on its own. That means the unsafe boundary is not just keypad handling. It is runtime LCD mutation while the communication runtime is active.

## Problem Statement

`pico/code.py` currently combines too many responsibilities:

- HID upload protocol composition and app-command response behavior
- UART bridge orchestration
- Jetson request lifecycle handling
- CDC debug emission and runtime diagnostics
- keypad input handling
- LCD initialization and runtime UI mutation
- temporary experimental probes

That design makes the runtime hard to reason about and obscures the real failure boundary. More importantly, it encourages the exact integration pattern that hardware has already rejected: bridge loop activity and runtime LCD mutation in one tightly coupled execution path.

## Goals

- Keep live SPARK bridge communication available on the Pico during normal runtime.
- Support interactive LCD updates while the bridge runtime is active.
- Remove application and device-policy logic from `pico/code.py`.
- Preserve the existing Raw HID protocol contract and host behavior.
- Keep the button-to-UI flow explicit and testable.
- Replace the integrated runtime LCD rendering strategy so it no longer depends on runtime `displayio` mutation.
- Make the architecture easier to debug with clearer module boundaries.

## Non-Goals

- Redesigning the host PC app or Jetson bridge protocol.
- Changing the Raw HID report format or app-command IDs.
- Adding new LCD screens beyond the existing 2x2 action grid during the first implementation phase.
- Solving deployment-manifest changes before the integrated runtime is proven stable again.

## Key Findings Driving The Redesign

### Known-safe boundaries

- Standalone LCD runtime with live highlighting.
- Integrated runtime with LCD initialized once at boot and left static.
- Integrated runtime with button logging only and no LCD mutation.
- Current `sida` transport runtime and end-to-end SPARK app communication.

### Known-unsafe boundaries

- Integrated runtime with button-driven LCD mutation using palette writes.
- Integrated runtime with prebuilt overlay visibility toggles in `displayio`.
- Integrated runtime with an automatic visual update and no button input.

### Implication

The architecture must not assume that a different `displayio` mutation strategy will eventually become safe enough. The redesign should treat runtime `displayio` mutation itself as untrusted inside the active bridge runtime.

## Chosen Approach

Use a split runtime architecture with a transport core and a pluggable UI backend.

The recommended design has three major decisions:

1. `pico/code.py` becomes a thin composition root only.
2. The communication bridge becomes its own runtime service layer with explicit loop ownership.
3. The integrated LCD runtime path uses a new renderer backend for runtime updates instead of the current integrated `displayio` mutation model.

This keeps the bridge logic close to the proven `sida` path while allowing the UI path to evolve behind a narrow interface.

## Rejected Alternatives

### Keep the highest safe rung forever

This would leave the integrated LCD static-only, which does not meet the required end state of simultaneous communication and interactive LCD updates.

### Continue iterating on the current integrated `displayio` UI design

The recovery worktree already disproved multiple variants of that direction. Continuing to tweak highlight mechanics would repeat the same architectural mistake.

### Use separate LCD mode and bridge mode only

This is a viable fallback if the final integrated design fails again, but it does not meet the required target behavior.

## Architecture

### `pico/code.py`

New role: composition root only.

Responsibilities:

- import modules
- configure hardware handles
- instantiate runtime services
- start the main loop

Non-responsibilities:

- protocol response composition
- button-to-UI policy
- LCD drawing logic
- Jetson request lifecycle policy
- experimental probes

### `pico/bridge_runtime.py`

Owns the active runtime loop.

Responsibilities:

- scheduling serial relay, Jetson polling, HID drain, input drain, UI updates, and heartbeats
- storing loop checkpoint state for diagnostics
- coordinating service order and timing
- exposing a small `run_once(now)` or equivalent execution surface for tests

### `pico/bridge_app.py`

Owns app-level behavior for HID commands.

Responsibilities:

- build the `text_preparer` used by `UploadProtocolHandler`
- map `FEATURE_1` into Jetson summarize requests
- map echo and feature-command behavior that is currently assembled in `pico/code.py`
- format response text and transport/debug status text

This removes the current `jetson_transport` global coupling from `pico/code.py`.

`PING` may remain in `pico/upload_protocol.py` during the first refactor phase if that keeps the protocol layer stable. The important boundary is that feature-command and response-composition logic move out of `pico/code.py`.

### `pico/button_input.py`

Owns keypad setup and event normalization.

Responsibilities:

- initialize button hardware from shared pin config
- drain raw `keypad` events
- expose normalized button events such as `ButtonPressed(index)`

The module should not know about LCD rendering or Jetson transport.

### `pico/lcd_state.py`

Pure UI state model.

Responsibilities:

- track active index
- track highlight expiry deadline
- apply `press(index, now)`
- apply `tick(now)`
- report whether visible state changed

No hardware dependency.

### `pico/lcd_renderer_spi.py`

New runtime renderer backend for the integrated bridge runtime.

Responsibilities:

- initialize the ILI9341 display for runtime use
- draw the full idle screen at startup
- redraw only changed cell regions during runtime updates
- avoid relying on integrated `displayio` mutation after boot

Bridge-mode runtime updates must not use `displayio` scene-graph, bitmap, palette, or visibility mutation after initialization. The implementation should use a non-`displayio` pixel-write path for runtime updates, either through a direct ILI9341 driver interface or a small SPI-backed drawing wrapper dedicated to the bridge runtime.

This backend is intentionally distinct from the current `displayio`-based standalone path. In bridge mode, this renderer should own LCD initialization and runtime updates from the start; there should be no bridge-mode handoff from a `displayio`-owned display tree into a later non-`displayio` update path.

### `pico/lcd_ui.py`

Facade/controller layer.

Responsibilities:

- keep the public LCD interface stable where practical
- connect `lcd_state` and the chosen renderer backend
- provide `handle_press(index, now=...)` and `tick(now=...)`

The facade should allow both:

- standalone LCD mode
- integrated bridge runtime mode

without forcing the two modes to share the same low-level runtime mutation strategy.

## Runtime Status Interface

To avoid recreating the current global-coupling pattern, `bridge_runtime` and `bridge_app` must communicate through an explicit runtime-status surface.

Required status fields:

- last CDC debug status
- last loop checkpoint
- whether a Jetson request is active
- current response length / completion state

Recommended shape:

- a small immutable snapshot returned by `bridge_runtime.current_status()`
- or a tiny shared state object passed into `bridge_app`

`bridge_app` may read status, but it should not own loop execution or directly mutate runtime scheduling state.

## Runtime Modes

### Mode A: Bridge Runtime Mode

Purpose: production SPARK communication path plus interactive LCD.

Properties:

- bridge loop active
- HID active
- UART bridge active
- button input active
- LCD initialized through the new runtime-safe backend

### Mode B: Standalone LCD Mode

Purpose: direct LCD bring-up and isolated hardware validation.

Properties:

- no bridge runtime
- no HID/UART bridge scheduling pressure
- same logical state/UI contract as bridge mode where possible

The two modes should share state and high-level UI behavior, but not necessarily the same renderer internals.

## Data Flow

### Button press in bridge runtime mode

1. `button_input` drains a press event.
2. `bridge_runtime` records diagnostics.
3. The event is passed to `lcd_ui.handle_press(index, now)`.
4. `lcd_state` updates state.
5. `lcd_renderer_spi` redraws only the affected visual region.
6. The bridge loop continues to service UART/HID normally.

### HID summarize request

1. `UploadProtocolHandler` assembles the request.
2. `bridge_app` maps the command into transport behavior.
3. `JetsonTransport` starts the UART request.
4. `bridge_runtime` polls UART and HID in its normal loop.
5. Response state is exposed back through the protocol layer.

## Rendering Strategy

### Bridge runtime renderer

The integrated runtime renderer should not rely on the current integrated `displayio` mutation model.

The preferred direction is a direct-draw renderer that:

- treats the LCD as a pixel-addressable target
- draws the whole screen once at startup
- redraws only the changed cell rectangle when pressed state changes
- redraws the cell back to idle when the flash expires

This should keep the update logic explicit and separate from the communication bridge loop.

For clarity: bridge-mode runtime should not use `displayio` display ownership at all. It should initialize the LCD through the dedicated runtime-safe renderer backend and keep all subsequent runtime updates in that same backend. Bridge-mode runtime updates should not call `TileGrid.hidden = ...`, palette writes, `Group.append/remove`, or any other `displayio` object mutation after startup because bridge-mode startup should not create a `displayio` scene graph in the first place.

### Standalone renderer

The standalone path may continue to use the simplest working LCD draw path, but the logical UI behavior should remain aligned with bridge mode.

That means bridge mode and standalone mode may intentionally use different low-level display ownership models:

- standalone mode may keep the simpler `displayio`-based LCD path if it remains useful for bring-up
- bridge mode should use the dedicated non-`displayio` runtime renderer from initialization onward

## Diagnostics Strategy

Heartbeat diagnostics remain in the bridge runtime.

Recommended diagnostics split:

- `bridge_runtime`: heartbeat and loop checkpoints
- `button_input`: optional normalized event tracing
- `bridge_app`: request/response status text
- `lcd_ui` / renderer: optional debug hooks for experimental validation only

Temporary probes such as automatic visual triggers should not stay in the steady-state runtime.

## File Plan

### New files expected

- `pico/bridge_runtime.py`
- `pico/bridge_app.py`
- `pico/button_input.py`
- `pico/lcd_state.py`
- `pico/lcd_renderer_spi.py`
- `tests/test_pico_bridge_runtime.py`
- `tests/test_pico_bridge_app.py`
- `tests/test_pico_button_input.py`
- `tests/test_pico_lcd_state.py`
- `tests/test_pico_lcd_renderer_spi.py`

### Existing files expected to change

- `pico/code.py`
- `pico/lcd_ui.py`
- `pico/upload_protocol.py`
- `tests/test_pico_code.py`
- `tests/test_pico_lcd_ui.py`
- `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`

### Existing files expected to stay mostly stable

- `pico/serial_bridge.py`
- `pico/jetson_transport.py`

## Testing Strategy

### Unit tests

- bridge runtime loop order
- bridge app response behavior
- button normalization and drain behavior
- LCD state transitions and timeout refresh
- LCD renderer region redraw behavior and draw-call minimization
- LCD facade compatibility with existing callers

### Integration tests

- `pico/code.py` startup wiring
- bridge runtime + button input interaction
- bridge runtime + LCD facade interaction
- existing HID protocol behavior remains stable

### Hardware validation gates

1. bridge boot + idle LCD screen
2. HID `ping()` while LCD is idle
3. repeated PB1-PB4 visual presses with bridge idle
4. repeated PB1-PB4 visual presses during bridge traffic
5. summarize smoke test while LCD interaction is active
6. soak test with repeated button presses and summarize traffic

## Risks

### The bridge runtime may still be incompatible with any live LCD drawing path

If even the new non-`displayio` runtime renderer destabilizes the board under bridge load, simultaneous integrated LCD + bridge may not be viable on this stack.

### Direct-draw LCD rendering may be slower or more complex than expected

That is acceptable if it provides correctness and runtime stability. The initial UI is only a 2x2 grid with short flash feedback.

### Scope creep from keeping two LCD modes fully identical

The shared contract should focus on state and behavior. The renderer implementation details may differ between standalone and bridge mode.

## Success Criteria

- `pico/code.py` is reduced to composition/wiring logic.
- Bridge communication remains as stable as current `sida` behavior.
- The integrated runtime supports repeated LCD button feedback without disconnect, white screen, or protocol stall.
- The standalone LCD mode still works as a hardware validation path.
- The bridge runtime and LCD path are independently testable.

## Fallback Decision Point

If the new runtime-safe renderer proof spike still fails during the earliest hardware gate, stop implementation and formally switch to a dual-mode architecture where bridge runtime and interactive LCD runtime are separate operating modes.
