# Pico LCD Button Summarize Trigger Design

## Summary

Wire the first Pico LCD button press to trigger the same downstream summarize command that the `Summarize Window` button in `spark_app_v2.py` already sends today: the lightweight JSON payload `{"command":"summarize"}`. Keep the change Pico-local, preserve current LCD feedback behavior, avoid any host-side event plumbing in this step, and do not weaken the existing general `FEATURE_1` request path used by inline-context summarize actions.

## Context

The current host app and Pico runtime already share the same summarize destination, but they reach it through different entry paths.

- In `spark_app_v2.py`, `SparkPanel._on_summarize()` builds `build_summarize_command()` and sends it through Raw HID `FEATURE_1`.
- In `pico/bridge_app.py`, the `FEATURE_1` path forwards whatever request text arrives to `JetsonTransport.start_request(...)`. That includes both `build_summarize_command()` and inline-context payloads from `build_summary_request(...)`.
- In `pico/bridge_runtime.py`, LCD button presses currently stop at `ui.handle_press(...)` and do not trigger any command.
- In `jetson/pico_llm_bridge.py`, the Jetson already knows how to handle `{"command":"summarize"}` by reading the active session from its database.
- In `jetson/pico_llm_bridge.py`, there is also an existing `PKT_BUTTON_PRESS` path that records a button event and starts summarize, but the current Pico LCD runtime does not feed that packet path.

That means the missing piece is not a new summarize protocol. It is a Pico-side dispatch path from button input into the existing summarize request flow.

## Problem Statement

The LCD/button runtime gives visual feedback, but pressing a hardware button does not currently trigger the same summarize request that the desktop app can send. If we duplicate request-start logic in multiple places, the Pico runtime will become harder to reason about and easier to drift from the host-triggered behavior. If we over-specialize the shared path to summarize-only payloads, we also risk breaking the current inline-context `FEATURE_1` requests used by `Custom Context`.

## Goals

- Make button index `0` trigger the same downstream summarize command used by the host app today.
- Reuse existing Pico summarize-start behavior instead of creating a separate button-only implementation.
- Keep the current LCD feedback path intact.
- Ignore button-triggered summarize attempts while a summarize request is already active.
- Keep the runtime loop non-blocking and easy to test.

## Preconditions

- Button-triggered summarize depends on the normal host polling flow having already populated an active session on Jetson.
- If no active session exists yet, the downstream summarize command may still run but Jetson will return its existing no-context response path.

## Non-Goals

- Mapping all four LCD buttons to different commands.
- Sending button presses back to the host app so `spark_app_v2.py` literally handles the event.
- Changing the host Raw HID protocol, Jetson summarize format, or LCD layout.
- Making the host app automatically display responses for button-triggered summarize in this step.
- Switching the LCD button path over to the Jetson `PKT_BUTTON_PRESS` mechanism in this step.

## Approaches Considered

### 1. Trigger summarize directly inside `bridge_runtime`

This is the smallest possible change, but it risks duplicating the request-start rules already embedded in the existing `FEATURE_1` path.

### 2. Recommended: extract a shared Pico request-forwarding helper plus a button callback

Create one small helper that owns the Pico-side rule for starting any Jetson request when the transport is idle. Keep it generic over request text so it still supports inline-context summarize payloads. Then expose a narrow button callback that uses that helper with the fixed summarize payload.

- the existing HID `FEATURE_1` path in `pico/bridge_app.py`
- the new LCD button index `0` callback injected into `pico/bridge_runtime.py`

This keeps the desktop-triggered and button-triggered paths aligned after they enter the Pico.

### 3. Route button presses up to the host app

This is the most literal interpretation of "same command as the button in the Spark app," but it is much larger work because the current architecture has no host callback path from Pico button input into `spark_app_v2.py` actions.

## Chosen Approach

Use a shared Pico request-forwarding helper and trigger it from button index `0` through an injected callback.

The shared helper should preserve the existing `FEATURE_1` semantics by accepting arbitrary request text and returning the same rich forwarded, busy, unavailable, encode-failure, and start-failure results the host path already uses today. The button callback should call that helper with the fixed summarize payload `{"command":"summarize"}` and collapse the result into button-appropriate behavior: start when idle, skip when busy, catch failures, and continue the loop.

## Design

### Button Policy

- Keep all current LCD visual feedback behavior.
- When `BridgeRuntime.run_once(...)` drains a pressed button event:
  - always call `ui.handle_press(...)` when UI is present
  - if the pressed button index is `0`, invoke an injected button-action callback that attempts to start a summarize request
  - do nothing command-wise for other button indices in this step
- Preserve the current runtime invariant of handling at most one pressed button event per loop iteration.

### Runtime Injection Boundary

`BridgeRuntime` should not import or construct `BridgeApp` directly.

Instead, `pico/code.py` should inject a narrow callback during runtime composition, for example a callable shaped like `handle_button_press(index)`. That callback may be built by `BridgeApp` or by a tiny adapter next to it, but `BridgeRuntime` should only know that it can notify button presses.

This keeps the runtime loop layer independent from app-layer request logic while still allowing button-triggered commands.

### Shared Request Forwarding

Add a focused helper in the Pico app layer that:

- accepts arbitrary request text
- checks whether the transport is currently busy
- calls `JetsonTransport.start_request(...)` when idle
- preserves the current host-facing result semantics for the `FEATURE_1` path

For the LCD button path, add a tiny wrapper that:

- uses the fixed summarize payload `{"command":"summarize"}`
- calls the shared request-forwarding helper
- treats `busy` as a normal skip
- catches start failures so one failed button-trigger attempt does not terminate `BridgeRuntime.run_forever(...)`

`pico/bridge_app.py` should use this helper for the existing `FEATURE_1` path so host-triggered summarize and custom-context requests still pass through unchanged. The injected LCD button callback should reuse the same helper rather than reimplementing transport checks.

### Explicit Non-Use Of `PKT_BUTTON_PRESS`

This change should not route the LCD button through the Jetson `PKT_BUTTON_PRESS` path.

Reason:
- the user request is to trigger the same command as the current Spark app summarize button
- the current Pico LCD button flow is local to the Pico runtime
- reusing `PKT_BUTTON_PRESS` here would create two competing hardware-trigger summarize mechanisms and could double-trigger summarize later if both paths become active

The existing `PKT_BUTTON_PRESS` support on Jetson may remain in place for other sources, but it is not the mechanism used by this LCD-button hookup.

Accepted consequence:
- this LCD-button summarize path will not create Jetson `button_events` telemetry rows in this step
- preserving button-event telemetry can be handled later as a separate design if it is still needed without reintroducing a second summarize trigger path
- implementation should update any architecture docs that currently imply this LCD-button path records Jetson `button_events`, or add a follow-up note where appropriate

### Runtime Flow

Button path after this change:

1. physical button `0` pressed
2. `ButtonInput.drain_pressed_events()` yields `ButtonPressed(index=0)`
3. `BridgeRuntime.run_once(...)` updates LCD feedback through `ui.handle_press(...)`
4. `BridgeRuntime` invokes the injected button callback for index `0`
5. the button callback uses the shared Pico request-forwarding helper with `{"command":"summarize"}`
6. `JetsonTransport.start_request(...)` forwards the request to Jetson
7. Jetson handles `command == "summarize"` using the active DB session

Host app and custom-context paths remain:

1. `SparkPanel._on_summarize()` or `_on_custom_context()`
2. `build_summarize_command()` or `build_summary_request(...)`
3. Raw HID `FEATURE_1`
4. `BridgeApp` shared request-forwarding helper
5. `JetsonTransport.start_request(...)` forwards the request to Jetson

The summarize-button path is therefore identical to the host summarize-button path from the shared Pico request helper onward, while custom-context requests continue using the same helper with their original inline payload.

### Shared-Transport Contention

The hardware-button path and the host `FEATURE_1` path continue to share the same single `JetsonTransport.request_active` guard.

That means:

- if a button-triggered summarize is active, host `Summarize Window` and `Custom Context` requests should continue to receive the existing `BUSY` behavior
- if a host-triggered request is active, button `0` should continue to skip summarize start as a normal busy case
- no new queueing or preemption behavior is introduced in this step

## Error Handling

- If `jetson_transport.request_active` is true, do not start another request.
- Preserve the full existing host-facing `FEATURE_1` result contract, including `busy`, `uart unavailable`, encode failures, `start_request(...)` failures, and the current outer failure fallback shape.
- Treat a busy transport as a normal no-op for button-triggered summarize.
- If a button-triggered request start raises or returns a failure result, keep that failure local to the current runtime iteration and continue the main loop.
- Reuse the existing debug hook only for lightweight observability, not for control flow.

## Testing

Add or update focused unit coverage for:

- button index `0` starts a summarize request with `{"command":"summarize"}`
- non-zero button indices do not start summarize yet
- busy transport skips the request
- no-active-session behavior is covered, either as a request-level test at the Jetson boundary or as a documented hardware validation expectation
- inline-context `FEATURE_1` requests still pass through unchanged
- the existing host-triggered summarize path still reaches the same shared Pico request helper
- host `Summarize Window` and `Custom Context` still return the existing `BUSY` behavior when a button-triggered summarize is already active
- a button-triggered start failure is contained to one runtime iteration and does not kill the runtime loop
- `pico/code.py` startup wiring injects the button callback into `BridgeRuntime` without making `BridgeRuntime` import app-layer logic
- `BridgeRuntime` still processes at most one pressed button event per loop iteration after the callback is added

Add a minimal hardware validation requirement after unit tests pass:

- deploy the updated Pico runtime to hardware
- physically reset the Pico before judging the validation run
- verify the LCD still gives visual feedback on button `0`
- verify button `0` triggers summarize while the bridge runtime is active
- verify the expected no-context behavior if host polling has not yet created an active Jetson session
- verify repeated presses during or around an active summarize request do not white-screen or stall the runtime

## Risks And Limits

- Button-triggered summarize will not automatically populate the host app's `RELEASE OUTPUT` panel, because the host did not initiate the response polling path.
- If the desired future behavior is full host-visible streaming for hardware-triggered summarize, that should be a separate design and implementation step.
- This step intentionally trades off Jetson `button_events` telemetry for a single explicit summarize trigger path.

## Success Criteria

- Pressing LCD button `0` while the bridge runtime is active starts a Jetson summarize request.
- The payload sent downstream matches the existing host summarize command payload.
- Existing host `Summarize Window` and `Custom Context` behavior still work.
- No additional button mappings are introduced in this change.
