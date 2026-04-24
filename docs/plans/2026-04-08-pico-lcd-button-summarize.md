# Pico LCD Button Summarize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pico LCD button `0` trigger the same downstream summarize request as the host `Summarize Window` action while preserving LCD feedback and the existing generic `FEATURE_1` request path.

**Architecture:** Keep request-start policy centralized in `pico/bridge_app.py`. Add one shared request-forwarding helper that both the host-facing `FEATURE_1` path and a new button callback reuse, then inject that callback from `pico/code.py` into `BridgeRuntime` so the runtime loop stays app-agnostic and non-blocking.

**Tech Stack:** CircuitPython, RP2040, Raw HID, UART, Python `unittest`, `pytest`, Windows Pico deployment flow

---

## File Structure

### Existing files to modify

- `pico/bridge_app.py`
  - extract the current `FEATURE_1` request-start rules into a reusable helper
  - add a button callback entry point that reuses the helper with the fixed summarize payload
- `pico/bridge_runtime.py`
  - accept an injected button callback and invoke it only for button index `0`
- `pico/code.py`
  - build the button callback during startup and pass it into `BridgeRuntime`
- `tests/test_pico_bridge_app.py`
  - add shared-helper, inline-context, contention, and button-failure coverage
- `tests/test_pico_bridge_runtime.py`
  - add callback invocation and non-zero button coverage while preserving one-event-per-loop behavior
- `tests/test_pico_code.py`
  - update composition-root wiring tests for the new callback dependency
- `documentation_reference.md`
  - add a durable architecture note that the Pico LCD button summarize path stays Pico-local and does not populate Jetson `button_events`
- `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`
  - append hardware validation notes and explicitly record that this Pico-local path does not use Jetson `PKT_BUTTON_PRESS`

### Existing files to verify only

- `tests/test_pico_llm_bridge.py`
  - already covers the downstream no-active-session summarize behavior
- `tests/test_summarize_stream.py`
  - already covers the host summarize payload contract
- `tests/test_spark_panel_ui.py`
  - already covers the host `Summarize Window` entry path staying lightweight

## Guardrails

- Do not route the LCD button through Jetson `PKT_BUTTON_PRESS`.
- Do not special-case `FEATURE_1` to summarize-only payloads; inline-context `summarize_window` requests must still pass through unchanged.
- Keep the current LCD feedback order: debug emit, UI press feedback, then optional summarize callback.
- Treat transport busy as a normal skip for button-triggered summarize.
- Keep `BridgeRuntime` free of app-layer request logic beyond calling an injected callback.

## Task 1: Centralize Pico Request Forwarding in `bridge_app`

**Files:**
- Modify: `pico/bridge_app.py`
- Modify: `tests/test_pico_bridge_app.py`
- Verify: `tests/test_pico_llm_bridge.py`
- Verify: `tests/test_summarize_stream.py`

- [ ] **Step 1: Write the failing bridge-app tests**

Add focused tests in `tests/test_pico_bridge_app.py` for these cases:

```python
def test_feature_1_forwards_lightweight_summarize_command_unchanged():
    from host_pc.summarize_stream import build_summarize_command
    from pico.bridge_app import BridgeApp, RuntimeStatus
    from pico.upload_protocol import AppCommand

    payload = build_summarize_command()
    transport = types.SimpleNamespace(start_request=mock.Mock())
    app = BridgeApp(
        jetson_transport=transport,
        runtime_status=lambda: RuntimeStatus(request_active=False),
    )

    result = app.prepare_upload_result(AppCommand.FEATURE_1, payload)

    transport.start_request.assert_called_once_with(payload.encode("utf-8"))
    assert result["detail"] == "forwarded"


def test_feature_1_forwards_inline_context_payload_unchanged():
    from pico.bridge_app import BridgeApp, RuntimeStatus
    from pico.upload_protocol import AppCommand

    payload = '{"command": "summarize_window", "window_text": "abc"}'
    transport = types.SimpleNamespace(start_request=mock.Mock())
    app = BridgeApp(
        jetson_transport=transport,
        runtime_status=lambda: RuntimeStatus(request_active=False),
    )

    result = app.prepare_upload_result(AppCommand.FEATURE_1, payload)

    transport.start_request.assert_called_once_with(payload.encode("utf-8"))
    assert result["detail"] == "forwarded"


def test_button_zero_uses_same_lightweight_summarize_payload_as_host():
    from host_pc.summarize_stream import build_summarize_command
    from pico.bridge_app import BridgeApp, RuntimeStatus

    transport = types.SimpleNamespace(start_request=mock.Mock())
    app = BridgeApp(
        jetson_transport=transport,
        runtime_status=lambda: RuntimeStatus(request_active=False),
    )

    result = app.handle_button_press(0)

    transport.start_request.assert_called_once_with(
        build_summarize_command().encode("utf-8")
    )
    assert result["detail"] == "forwarded"


def test_button_zero_skips_when_transport_is_busy():
    ...


def test_feature_1_returns_uart_unavailable_when_transport_missing():
    ...


def test_feature_1_returns_encode_failure_shape():
    ...


def test_feature_1_returns_start_failure_shape():
    ...


def test_feature_1_returns_outer_failure_shape():
    ...


def test_button_start_failure_is_contained_to_result():
    ...


def test_host_feature_1_returns_busy_while_button_started_request_is_active():
    ...
```

- [ ] **Step 2: Run the bridge-app tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_bridge_app.py -q
```

Expected: FAIL because `BridgeApp` does not yet expose a shared request helper or `handle_button_press(...)`.

- [ ] **Step 3: Implement the minimal shared forwarding helper and button wrapper**

In `pico/bridge_app.py`, keep the public upload behavior stable but move the actual request-start rules into one helper that both paths use:

```python
SUMMARIZE_COMMAND_TEXT = '{"command": "summarize"}'


class BridgeApp:
    def _forward_request_text(self, text, status):
        # Preserve the existing FEATURE_1 result contract here.
        ...

    def _prepare_feature_1(self, text, status):
        return self._forward_request_text(text, status)

    def handle_button_press(self, index):
        if index != 0:
            return {"detail": "ignored"}
        return self._forward_request_text(
            SUMMARIZE_COMMAND_TEXT,
            self._runtime_status(),
        )


def build_button_press_handler(*, jetson_transport, runtime_status):
    return BridgeApp(
        jetson_transport=jetson_transport,
        runtime_status=runtime_status,
    ).handle_button_press
```

Implementation requirements:

```text
- preserve current FEATURE_1 success and failure shapes exactly
- keep UTF-8 encoding inside the shared helper
- use the same busy guard for host and button-triggered requests
- do not import host-side UI code into Pico modules
- the new tests must lock down `uart unavailable`, `busy`, `encode:*`, `start:*`, and `outer:*` behavior before refactoring
```

- [ ] **Step 4: Run the targeted regression tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_bridge_app.py tests/test_pico_llm_bridge.py tests/test_summarize_stream.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add pico/bridge_app.py tests/test_pico_bridge_app.py
git commit -m "refactor: share pico summarize request forwarding"
```

## Task 2: Inject Button Summarize Trigger Into `BridgeRuntime`

**Files:**
- Modify: `pico/bridge_runtime.py`
- Modify: `tests/test_pico_bridge_runtime.py`

- [ ] **Step 1: Write the failing runtime tests**

Add or update tests in `tests/test_pico_bridge_runtime.py` for these cases:

```python
def test_bridge_runtime_button_zero_updates_ui_then_invokes_callback():
    call_log = []
    runtime = BridgeRuntime(
        ...,
        button_press_handler=lambda index: call_log.append(("callback", index)),
        ui=types.SimpleNamespace(
            handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
            tick=lambda *, now: call_log.append(("tick", now)),
        ),
    )

    runtime.run_once(now=1.5)

    assert call_log == [("ui", 0, 1.5), ("callback", 0), ("tick", 1.5)]


def test_bridge_runtime_non_zero_buttons_do_not_invoke_callback():
    ...


def test_bridge_runtime_continues_loop_when_button_handler_returns_failure_result():
    transport = types.SimpleNamespace(
        start_request=mock.Mock(side_effect=RuntimeError("boom")),
        request_active=False,
        response_len=0,
        response_complete=False,
        response_bytes=b"",
        poll=lambda *, max_chunk_size: None,
    )
    app = BridgeApp(
        jetson_transport=transport,
        runtime_status=lambda: RuntimeStatus(request_active=False),
    )
    call_log = []
    runtime = BridgeRuntime(
        ...,
        jetson_transport=transport,
        button_press_handler=lambda index: call_log.append(app.handle_button_press(index)),
        ui=types.SimpleNamespace(
            handle_press=lambda index, *, now: call_log.append(("ui", index, now)),
            tick=lambda *, now: call_log.append(("tick", now)),
        ),
        time_sleep=lambda seconds: call_log.append(("sleep", seconds)),
    )

    runtime.run_once(now=1.5)

    assert ("tick", 1.5) in call_log
    assert ("sleep", 0.002) in call_log


def test_bridge_runtime_still_processes_only_one_button_event_per_loop():
    ...
```

- [ ] **Step 2: Run the runtime tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py -q
```

Expected: FAIL because `BridgeRuntime` does not yet accept or invoke a button callback.

- [ ] **Step 3: Implement the minimal runtime callback hook**

Update `pico/bridge_runtime.py` like this:

```python
class BridgeRuntime:
    def __init__(..., button_press_handler=None, ...):
        ...
        self._button_press_handler = button_press_handler

    def run_once(self, *, now):
        ...
        for button_event in self._button_input.drain_pressed_events():
            self._emit_debug(f"button:{button_event.index}")
            if self._ui is not None:
                self._ui.handle_press(button_event.index, now=now)
            if button_event.index == 0 and self._button_press_handler is not None:
                self._button_press_handler(button_event.index)
            break
        ...
```

Constraints:

```text
- keep the existing UI feedback path intact
- keep the callback optional for non-bridge callers and tests
- do not add any request-start logic directly inside BridgeRuntime
- keep looping normally when the injected handler returns a failure result from the shared app helper
```

- [ ] **Step 4: Run the runtime tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add pico/bridge_runtime.py tests/test_pico_bridge_runtime.py
git commit -m "feat: trigger summarize callback from pico button zero"
```

## Task 3: Wire the Callback at Startup in `pico/code.py`

**Files:**
- Modify: `pico/code.py`
- Modify: `tests/test_pico_code.py`

- [ ] **Step 1: Write the failing startup-wiring test**

Extend `tests/test_pico_code.py` so the composition-root test captures both builders coming from `pico.bridge_app`:

```python
fake_bridge_app_module = types.SimpleNamespace(
    build_text_preparer=lambda *, jetson_transport, runtime_status: "bridge-preparer",
    build_button_press_handler=lambda *, jetson_transport, runtime_status: "button-handler",
)

...

self.assertIs(runtime.button_press_handler, "button-handler")
```

Also update `_FakeBridgeRuntime.__init__(...)` to accept `button_press_handler=None` and store it for assertions.

- [ ] **Step 2: Run the startup-wiring test to verify RED**

Run:

```bash
python -m pytest tests/test_pico_code.py -q
```

Expected: FAIL because `code.py` does not yet import or pass a button handler into `BridgeRuntime`.

- [ ] **Step 3: Implement the startup wiring**

Update `pico/code.py` so `_main(...)` builds the callback from `pico.bridge_app` and passes it into `BridgeRuntime`:

```python
from pico.bridge_app import build_button_press_handler, build_text_preparer

...

button_press_handler = build_button_press_handler(
    jetson_transport=jetson_transport,
    runtime_status=lambda: runtime.current_status(),
)

runtime = BridgeRuntime(
    ...,
    button_press_handler=button_press_handler,
    ...,
)
```

Requirements:

```text
- keep BridgeRuntime independent from BridgeApp construction
- keep the existing `build_text_preparer(...)` wiring unchanged
- preserve the current startup order and diagnostics checkpoints
```

- [ ] **Step 4: Run the startup and runtime regression tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_code.py tests/test_pico_bridge_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add pico/code.py tests/test_pico_code.py
git commit -m "refactor: inject pico button summarize handler"
```

## Task 4: Verify End-to-End Behavior and Record Hardware Results

**Files:**
- Modify: `documentation_reference.md`
- Modify: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`
- Verify: `tests/test_pico_bridge_app.py`
- Verify: `tests/test_pico_bridge_runtime.py`
- Verify: `tests/test_pico_code.py`
- Verify: `tests/test_pico_llm_bridge.py`
- Verify: `tests/test_summarize_stream.py`
- Verify: `tests/test_spark_panel_ui.py`

- [ ] **Step 1: Run the targeted regression suite**

Run:

```bash
python -m pytest tests/test_pico_bridge_app.py tests/test_pico_bridge_runtime.py tests/test_pico_code.py tests/test_pico_llm_bridge.py tests/test_summarize_stream.py tests/test_spark_panel_ui.py -q
```

Expected: PASS.

- [ ] **Step 2: Deploy the updated Pico runtime to hardware**

Use the existing deploy helper with the mounted `CIRCUITPY` path from `docs/WINDOWS_PICO_JETSON_BRINGUP.md`:

```bash
python tools/pico/deploy_to_pico.py --target D:\
```

If the board is mounted elsewhere, substitute the correct drive letter instead of editing the deploy script.

- [ ] **Step 3: Physically reset the Pico and perform the hardware validation ladder**

Record these outcomes:

```text
- LCD still shows the normal bridge idle screen after reset
- button 0 still highlights on the LCD
- button 0 triggers summarize while the bridge runtime is active
- repeated presses during an active summarize do not white-screen or wedge the board
- with no active Jetson session, the summarize path still falls back to the existing no-context behavior
- button-triggered summarize does not create a new host-panel streaming path in this step
```

- [ ] **Step 4: Append the validation note and telemetry caveat to the investigation log**

Update both `documentation_reference.md` and `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`:

```text
- in documentation_reference.md, add one durable note near the button_events table that only PKT_BUTTON_PRESS-based sources populate button_events today
- the exact firmware revision / branch used for the validation run
- whether button 0 summarize passed on hardware
- whether busy re-presses were safely ignored
- that this Pico-local summarize path intentionally does not use Jetson PKT_BUTTON_PRESS and therefore does not create button_events telemetry rows
```

- [ ] **Step 5: Commit Task 4**

```bash
git add documentation_reference.md docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md
git commit -m "docs: record pico button summarize validation"
```
