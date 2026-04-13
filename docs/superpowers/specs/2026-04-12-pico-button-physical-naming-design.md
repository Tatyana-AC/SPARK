# Pico Button Physical Naming Design

## Summary

Rename the Pico button-facing naming so the code, logs, and LCD layout use the physical button order instead of zero-based ambiguity. Keep the existing runtime behavior and zero-based internal event indices intact, but make the physical mapping explicit with `PB1`..`PB4` in code-facing definitions and one-based button numbers `1..4` in transport-constrained debug/status strings.

## Context

The current Pico LCD UI already renders the four actions in the physical order the user wants:

- top-left: `SYNTHESIS`
- top-right: `REFORMAT`
- bottom-left: `SEARCH`
- bottom-right: `RESPOND`

Internally, the stack still talks about the buttons with zero-based indices:

- LCD cell order uses indices `0..3`
- `ButtonInput` yields `ButtonPressed(index=event.key_number)`
- `BridgeRuntime` emits debug messages like `button:0`, `pre_press:1`, and `post_press:3`
- host-side polling logic in `spark_app_v2.py` currently keys summarize-response polling off `button:0`

That mix is easy to misread because physical button names start at `1`, not `0`.

## Problem Statement

The current logging and variable naming force developers to mentally translate between hardware labels (`PB1`..`PB4`) and software event indices (`0`..`3`). That is especially error-prone in a hardware-integrated path where the user is explicitly reasoning about physical button position and LCD layout. We need one clear naming contract that matches the real device without breaking the existing runtime behavior that already depends on zero-based indices.

## Goals

- Make the physical mapping explicit as physical buttons `1..4`, with `PB1`..`PB4` available in code-facing definitions where that improves readability.
- Keep the LCD layout aligned with that same physical naming.
- Rename local variables and constants in button-related UI/runtime code so they describe physical buttons more clearly.
- Update debug/log output to carry one-based physical button labels instead of ambiguous zero-based labels.
- Preserve current runtime behavior, including the summarize action currently tied to the first physical button.
- Preserve compatibility with the existing 30-byte HID runtime-status transport.

## Non-Goals

- Changing the physical pin wiring.
- Reordering the LCD cells.
- Changing which action each button triggers.
- Converting internal button interfaces to one-based numeric button IDs.
- Introducing a new host-Pico message format unless required for compatibility.

## Approaches Considered

### 1. Recommended: keep internal indices, add explicit physical button naming at the UI/logging boundary

Keep `0..3` where existing logic already depends on it, but add one clear mapping layer from internal index to physical button identity. Use that mapping for LCD-facing metadata, runtime debug text, and variable naming.

This is the smallest safe change. It removes the ambiguity humans see while minimizing risk to protocol behavior.

### 2. Convert the full runtime and host contract to one-based indices

This would make every layer literally use `1..4`, but it is broader and riskier because host polling, debug parsing, tests, and the current summarize trigger all assume the first button is internally `0`.

### 3. Update docs only

This is the lowest-risk option, but it does not solve the actual source of confusion inside the code and logs.

## Chosen Approach

Use an explicit physical-button naming layer while preserving existing zero-based internal indices, and prefer compact one-based button numbers in debug/status strings.

## Design

### Canonical Mapping

The canonical physical mapping is:

- `PB1` = top-left = `SYNTHESIS` = internal index `0`
- `PB2` = top-right = `REFORMAT` = internal index `1`
- `PB3` = bottom-left = `SEARCH` = internal index `2`
- `PB4` = bottom-right = `RESPOND` = internal index `3`

This mapping must live in one shared source-of-truth module, recommended as `pico/button_layout.py`, so LCD UI, bridge runtime, and renderer code all consume the same definitions and helper functions.

That shared mapping must be tied to the actual hardware event order produced by `BUTTON_PIN_NUMBERS` and `event.key_number` in the button-input path. The same source of truth must explain both the hardware scan order and the LCD/action naming order so physical button 1 cannot drift away from the summarize path.

### LCD Naming

The LCD layout should continue to render the same 2x2 action grid in the same positions, but the code that constructs the cells should stop relying on anonymous action-only tuples where that obscures the physical mapping.

The required shape is a small ordered button definition structure per cell containing at least:

- physical name such as `PB1`
- compact physical number such as `1`
- action label such as `SYNTHESIS`
- internal zero-based index
- grid position implied by order

This keeps the layout and physical naming tied together instead of forcing readers to infer that index `0` happens to mean the top-left cell.

To avoid breaking bridge-mode rendering, the implementation should preserve one compatibility export for the current renderer contract.

Required shape:

- add a richer ordered constant such as `BUTTON_DEFINITIONS` in the shared source-of-truth module
- derive `ACTIONS` from it as the existing tuple of label strings
- keep `pico/lcd_renderer_spi.py` consuming the derived `ACTIONS` tuple unless that file is intentionally updated in the same change to consume the richer structure directly

This avoids creating two competing sources of truth while keeping existing renderer imports valid.

### Runtime And Logging Contract

Human-facing debug events should use one-based physical button numbers rather than raw zero-based numeric labels.

Examples:

- `button:1` instead of `button:0`
- `pre_press:2` instead of `pre_press:1`
- `post_press:4` instead of `post_press:3`

This rename scope also includes the other existing index-bearing debug events in the Pico LCD path so the naming contract stays consistent:

- `draw_press:n`
- `press_done:n`
- `idle_prev:n`
- `render_press:n`
- `render_press_done:n`

The runtime must keep passing zero-based indices to internal methods such as `ui.handle_press(index, now=...)` and existing callback hooks. This is a hard compatibility requirement, not an optional implementation choice.

If any host-side control flow currently keys off the old debug strings, that host logic must be updated in the same change so the new log names do not break summarize polling or runtime observability.

That compatibility scope includes not only `spark_app_v2.py`, but also all repo observability surfaces that consume exact debug text, including watch utilities and protocol tests.

### Surface Contract Matrix

To avoid mixed naming, the rename should follow one explicit output contract per surface:

- internal event objects and method arguments: keep zero-based integer indices `0..3`
- LCD button-definition metadata: expose `PB1`..`PB4`, compact physical numbers `1..4`, and the associated zero-based index
- `GET_DEBUG_EVENT` payloads: emit one-based physical button numbers, for example `button:1` and `draw_press:3`
- host log lines derived from debug events: show the same one-based button numbers
- `BridgeRuntime.loop_checkpoint`: raw internal checkpoint names may remain unchanged internally, but `GET_RUNTIME_STATUS` serialization must normalize any button-specific checkpoint so host-visible status text never reintroduces zero-based button indices
- `GET_RUNTIME_STATUS` text: always use a compact alias table for the debug-message portion so transport output is deterministic and stays within 30 bytes; the checkpoint suffix remains observability-only and must not become a control-flow dependency
- watch/debug helpers and tests that assert exact strings: update to the new one-based values in the same change

This keeps each surface deterministic and prevents half-migrated output such as `button:1|after_ui_press:0`.

### Runtime Status Length Budget

`pico/upload_protocol.py` currently compacts runtime text to 30 bytes via `debug_message|loop_checkpoint`. One-based button numbers help, but some bridge-mode messages are still too long if copied through verbatim, so the spec must explicitly preserve transport safety.

The implementation should avoid relying on truncation for normal button events.

Required rule:

- keep `GET_DEBUG_EVENT` messages human-readable and one-based, such as `button:1`, `pre_press:2`, and `render_press_done:4`
- normalize button-specific checkpoint suffixes during runtime-status serialization so host-visible runtime text never contains zero-based `:0..:3` fragments
- always emit aliased debug-message prefixes in `GET_RUNTIME_STATUS`, not the long-form debug labels

Required runtime-status alias examples:

- `button:1`
- `pre:2` for `pre_press:2`
- `post:4` for `post_press:4`
- `draw:3` for `draw_press:3`
- `done:3` for `press_done:3`
- `idle:2` for `idle_prev:2`
- `rpress:2` for `render_press:2`
- `rdone:4` for `render_press_done:4`
- `ui_pre` for any `before_ui_press:{index}` checkpoint
- `ui_post` for any `after_ui_press:{index}` checkpoint

This keeps combined status strings such as `rdone:4|after_sleep` within the existing limit while preserving the physical-button index contract.

Non-button-specific checkpoints such as `after_sleep` and `after_button_events` can remain unchanged.

Because `BridgeRuntime.run_once()` continues advancing through later checkpoints like `after_button_events`, `before_ui_tick`, `after_ui_tick`, and `after_sleep`, the checkpoint suffix is not a sticky button-event contract. The stable contract for host-visible button naming is the debug-message portion and the separate debug-event queue, not long-lived retention of a button-specific checkpoint suffix.

Host and watch surfaces should display runtime-status aliases as-is. They should not expand `pre` back to `pre_press` or `rdone` back to `render_press_done`. These aliases are the canonical transport-level runtime-status vocabulary, while `GET_DEBUG_EVENT` remains the richer event stream.

### Variable Naming

Where current button-related variables are generic or index-centric, rename them so they reflect the physical meaning when that improves clarity.

Examples of preferred direction:

- `ACTIONS` -> a more explicit button definition constant if the structure changes
- local `index`-only iteration in LCD construction -> button definition objects that expose `physical_name`, `physical_number`, and `action_label`
- debug/log helper logic -> names that distinguish `button_index` from `physical_button_number`

The important constraint is not the exact identifier spelling; it is that the code should no longer make readers guess whether `1` means the first internal index plus one or the actual physical button identity.

### Compatibility Constraint

The first physical button must continue to drive the existing summarize functionality.

That means any current logic equivalent to "internal index `0` triggers summarize behavior" remains true after the rename, even if logs and metadata now call that same button `1` or `PB1`.

Concretely, any host behavior that currently listens for `button:0` must be updated to listen for `button:1` in the same change.

The following internal interfaces must remain zero-based after the rename:

- `ButtonPressed.index`
- `ButtonInput.drain_pressed_events()` yield values
- `ui.handle_press(index, now=...)`
- button-action callback inputs such as `handle_button_press(index)`

## Error Handling

- If an unexpected button index is encountered outside the defined `0..3` mapping, the runtime should continue to behave safely.
- Mapping helpers should use one exact fallback physical label, `?`, rather than crashing the runtime only because a debug string could not be named.
- Renaming work must not change debounce behavior, button dispatch order, or the single-event-per-loop invariant.
- Runtime status text must remain safe under the existing HID payload cap; normal button-path statuses should fit without silent truncation of the button name.

For invalid button indices, the safe-handling rule applies at the runtime/UI boundary rather than inside the low-level renderer. The button-processing path should reject or skip unmapped indices before calling renderer code that assumes `0..3`. The renderer may keep its defensive `IndexError` for direct programmer misuse.

Fallback examples:

- `button:?`
- `pre_press:?`
- `rdone:?`

These fallback forms stay within the existing transport budget and keep observability consistent across runtime, UI, renderer, and host surfaces.

## Testing

Add or update focused coverage for:

- the canonical `PB1`..`PB4` and `1..4` mapping to internal indices `0..3`
- LCD layout order still matching `PB1` top-left through `PB4` bottom-right
- debug/log messages using one-based physical button numbers
- bridge-mode debug/render messages using one-based physical button numbers for `draw_press`, `press_done`, `idle_prev`, `render_press`, and `render_press_done`
- host-side summarize polling still starting from the first physical button after the log rename
- host-side direct debug-message polling starts for `button:1` and does not start for `button:2`, `button:3`, or `button:4`
- host-side response polling driven by runtime-status active/complete flag transitions remains unchanged
- existing button press handling and highlight behavior remaining unchanged
- `ACTIONS` compatibility for bridge rendering if a richer button-definition constant is introduced
- runtime-status packing under the 30-byte HID cap, including exact boundary checks for compact aliases such as `rdone:4|after_sleep`
- watch/debug utilities and protocol-level tests that consume exact debug text
- debounce behavior remaining unchanged after the rename
- the single-event-per-loop runtime invariant remaining unchanged after the rename
- per-press debug emission order across runtime, UI, and renderer remaining unchanged aside from the new one-based labels
- host fallback behavior when `GET_DEBUG_EVENT` is empty and only aliased `GET_RUNTIME_STATUS` text is available

After unit coverage passes, perform Pico hardware validation:

- deploy the updated firmware to the mounted `CIRCUITPY` board
- verify the LCD still shows the same button/action positions
- press each physical button and confirm the reported/logged name matches the device position
- verify physical button 1 still drives the summarize path

## Risks And Limits

- If host code or test utilities parse exact debug strings, renaming those strings without updating consumers will silently break behavior.
- The term "button 1" is ambiguous unless the code makes it clear whether it means physical button `1` or internal index `1`; the implementation should avoid that ambiguity in identifiers and test names.
- This change improves naming clarity, not feature scope. It does not assign new behaviors to physical buttons `2`..`4`.

## Success Criteria

- The codebase has one explicit mapping from internal button indices to physical buttons `1..4`, with `PB1`..`PB4` available in shared metadata.
- LCD-related code reads in physical-button order instead of relying on implied zero-based meaning.
- Logs and debug messages use one-based physical button labels consistently.
- Physical button 1 still triggers the existing synthesis/summarize path without behavior regression.
