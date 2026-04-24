# Pico LCD Redesign Design

## Summary

Redesign the Pico LCD implementation so the integrated runtime keeps visual button feedback without relying on runtime `displayio` scene-graph mutation. The new design builds the full display tree once at startup and limits runtime behavior to state changes on pre-existing display objects.

## Context

The current integrated Pico runtime shares `pico/lcd_ui.py` with the standalone smoke test. Real hardware investigation on 2026-04-03 showed that the integrated runtime crashes when button handling triggers dynamic highlight updates that remove and append `_highlight_grid` on `root_group`.

The current diagnostic workaround keeps the runtime stable by disabling highlight updates in `pico/code.py`. That preserves board stability but removes the intended visual press feedback.

The user wants to keep heartbeat diagnostics in place and continue developing visual feedback rather than freezing the LCD path in a degraded state.

## Problem Statement

The current LCD implementation mixes three concerns in one press path:

- tracking transient UI state
- deciding how that state should look on screen
- mutating the `displayio` scene graph dynamically at runtime

The hardware evidence says the third concern is the failure point. The redesign must remove that class of behavior by construction while preserving the existing external runtime contract.

## Goals

- Keep a visible brief-flash press response in the integrated Pico runtime.
- Keep the current heartbeat diagnostics in `pico/code.py`.
- Share one LCD implementation between the integrated runtime and `pico/lcd_smoke_test.py`.
- Make runtime press feedback safe on real hardware by avoiding `root_group.append(...)` and `root_group.remove(...)` after startup.
- Preserve the existing `handle_press(index, now=...)` and `tick(now=...)` style interface so `pico/code.py` stays simple.
- Make the LCD behavior easier to test with pure-Python unit tests.

## Non-Goals

- Redesigning the host app, Jetson path, or button-to-host protocol behavior.
- Adding new LCD screens beyond the existing idle 2x2 action grid.
- Adding animation sequences beyond a simple timed flash.
- Removing the current heartbeat debug path.

## Chosen Approach

Use a static scene graph with a small explicit UI state model.

This combines two ideas:

1. A pure state layer that decides which cell is active and when the flash expires.
2. A renderer layer that owns a fully prebuilt `displayio` object tree and only updates already-mounted objects.

This approach keeps the current CircuitPython rendering model, avoids the known dangerous mutation pattern, and gives the code a clearer separation between state and rendering.

## Rejected Alternatives

### Keep the current design and only disable dangerous branches

This is not sufficient because it preserves the same mixed design and leaves the runtime dependent on a growing list of exception flags like `skip_highlight_update`.

### Full custom framebuffer renderer

This would likely be safe enough but is larger than needed right now. It would replace convenient existing `displayio` primitives with more custom drawing code before the current design has been stabilized.

## Architecture

### `SparkLcdState`

A pure state object with no `displayio` dependency.

Responsibilities:

- store `active_index`
- store `flash_until`
- apply `press(index, now)`
- apply `tick(now)` and clear expired flash state
- expose whether the state changed and needs a render update

This object should be trivial to unit test.

### `SparkLcdRenderer`

Owns all `displayio` objects and builds the LCD screen once.

Responsibilities:

- create the root group and all child objects at startup
- prebuild one visual bundle per cell
- apply active/inactive visuals to existing objects only
- never allocate press-feedback display objects on demand
- never append or remove cell-highlight objects after startup

### `SparkLcdUi`

Thin controller that keeps the public interface stable.

Responsibilities:

- forward `handle_press(index, now=...)` into state updates
- forward `tick(now=...)` into state updates
- call the renderer only when state changes

This preserves the external usage pattern from both `pico/code.py` and `pico/lcd_smoke_test.py`.

## Rendering Strategy

### Startup-only object creation

During initialization, the renderer builds:

- background
- status bar
- divider accent
- title label
- four cell view bundles

Each cell view bundle contains pre-existing objects for:

- base fill
- borders or other static decoration
- label
- pressed visual state representation

After startup, the renderer must not perform any scene-graph structural changes for press feedback.

This invariant applies to the entire mounted display tree, not just `root_group`. After initialization, no mounted `displayio` group in the tree may be structurally mutated at runtime.

### Press visual model

The visual interaction target is a brief flash.

Behavior:

- a press activates exactly one cell
- the active cell shows a pressed state immediately
- the pressed state clears automatically after `HIGHLIGHT_SEC`
- a new press replaces the currently active cell and resets the timeout
- pressing the already-active cell refreshes the timeout for a full new `HIGHLIGHT_SEC` interval

### Safe runtime updates

The first implementation target should use prebuilt per-cell pressed overlays whose visibility is toggled at runtime on already-mounted objects. This is the most conservative path because it avoids both runtime scene-graph edits and runtime palette mutation as the primary mechanism.

Fallback option only if the chosen visibility mechanism proves unsupported or unstable on hardware:

- switch the pressed state by changing pre-existing cell palette values without changing the public LCD API

The design intentionally avoids:

- `root_group.append(...)`
- `root_group.remove(...)`
- moving a shared highlight object between parents or indices
- replacing `root_group`
- recreating label or tilegrid objects on button press

## Cell Design

Each of the four action cells should become an explicit view object or structured record rather than a loose set of arrays.

Each cell record should include:

- action name
- index
- background palette or background tilegrid reference
- optional pressed overlay reference if prebuilt
- label reference

This makes per-cell updates direct and avoids cross-cell bookkeeping like a shared movable highlight grid.

## Runtime Flow

### Initialization

1. `initialize_lcd_ui()` imports CircuitPython display dependencies.
2. It configures the SPI bus and ILI9341 driver.
3. It constructs `SparkLcdRenderer` and builds the full display tree.
4. It constructs `SparkLcdState` with no active cell.
5. It returns `SparkLcdUi(state, renderer, ...)`.

## Public API Compatibility

The redesign should preserve the public LCD module contract used today unless a follow-up design explicitly changes it.

Required compatibility points:

- keep exported `ACTIONS`
- keep zero-argument `initialize_lcd_ui()` valid for `pico/lcd_smoke_test.py`
- keep `initialize_lcd_ui(debug_hook=..., debug_checkpoint=...)` valid for `pico/code.py` and existing tests
- keep `handle_press(index, now=...)` and `tick(now=...)` on the returned UI object

The redesign may remove internal workaround kwargs once they are no longer needed, but externally visible call sites should not need broad rewrites.

### Press handling

1. `handle_press(index, now)` updates state.
2. The state marks the pressed cell active and updates the deadline.
3. If the visible state changed, the renderer applies the new active/inactive cell visuals.
4. If the same cell was pressed again, the state still refreshes the deadline even if the renderer does not need to change the visible state.
5. No runtime scene-graph mutation occurs.

### Tick handling

1. `tick(now)` checks whether the active flash expired.
2. If no change is required, it returns quickly.
3. If the flash expired, the state clears the active cell.
4. The renderer updates the existing cell visuals back to idle.

## Debugging Strategy

Heartbeat diagnostics stay in `pico/code.py` as requested.

The LCD module should support optional debug hooks for targeted instrumentation, but the safe rendering design should no longer depend on temporary runtime-skip flags like:

- `skip_highlight_update`
- partial workaround branches whose only purpose is to avoid known-bad runtime graph edits

Debug messages should remain optional and not be required for correct UI behavior.

The current `debug_hook` and `debug_checkpoint` keyword arguments should remain supported so existing runtime instrumentation and tests continue to work during the redesign.

## File Plan

Primary expected files:

- Modify `pico/lcd_ui.py`
- Modify `tests/test_pico_lcd_ui.py`
- Modify `tests/test_pico_code.py`
- Modify `pico/code.py`
- Validate with `pico/lcd_smoke_test.py` unchanged or only minimally updated for compatible imports

Recommended direction:

- keep the redesign in `pico/lcd_ui.py` unless the file becomes materially harder to read
- only split into an additional Pico-local helper module if the state/renderer separation becomes awkward inside one file

## Testing Strategy

The redesign should be implemented with TDD.

### State tests

- press activates the requested index
- second press replaces the active index
- pressing the same active index refreshes the flash deadline
- tick before timeout keeps the flash active
- tick after timeout clears the flash

### Renderer tests

- initialization builds a fixed root-group shape
- handling a press keeps the same `display.root_group` identity
- handling a press keeps the same child count, child order, and child identities for the full mounted display tree, including nested groups or cell bundles
- ticking out the flash keeps the same `display.root_group` identity
- ticking out the flash keeps the same child count, child order, and child identities for the full mounted display tree, including nested groups or cell bundles
- renderer updates existing mounted objects instead of appending, removing, or replacing them

### UI integration tests

- `handle_press()` updates visual state through the state/renderer path
- `tick()` clears the flash correctly
- the public LCD API remains compatible with current callers

### Runtime integration tests

- `pico/code.py` continues to call `handle_press()` and `tick()` normally
- heartbeat diagnostics remain enabled
- LCD-specific workaround flags are removed or reduced to comments documenting the hardware constraint

## Migration Notes

- Remove the current movable highlight-grid design.
- Replace cell palette arrays and shared highlight ownership with explicit per-cell view records.
- Keep screen constants like dimensions, labels, and color definitions unless implementation details require small adjustments.
- Keep the smoke test behavior aligned with the integrated runtime so hardware validation exercises the real rendering path.

## Risks

### Runtime visibility toggles may still have hardware-specific constraints

The redesign chooses prebuilt overlay visibility toggles as the first hardware-validation target because they avoid the known-bad highlight mutation pattern and avoid palette writes as the primary mechanism. That strategy still needs hardware verification under repeated presses after a physical reset.

### Runtime palette writes may still prove sensitive on hardware

The previous investigation identified scene-graph mutation as the confirmed crash path, but palette writes were also part of earlier hypotheses. If the first visibility-based strategy fails, the fallback should be validated carefully on hardware before it becomes the main path.

### Over-engineering the renderer split

The state/renderer separation should stay small. If dedicated classes add too much indirection, the implementation can keep them in a single file with tight interfaces.

## Success Criteria

- The integrated runtime keeps the heartbeat diagnostics.
- Pressing PB1-PB4 on real hardware no longer crashes or wedges the Pico.
- A pressed cell flashes briefly in the integrated runtime.
- `lcd_smoke_test.py` uses the same redesigned LCD implementation.
- Unit tests cover the new state flow and confirm the mounted scene graph keeps the same root identity, child order, and child identities during press handling and timeout clear.

## Open Validation Step

Before calling the redesign complete, verify on real hardware that the chosen prebuilt-object update strategy is stable under repeated button presses after a physical reset.
