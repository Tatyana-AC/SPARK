# Pico Button Physical Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Pico button naming match the physical hardware order so logs, LCD metadata, and host-visible status use one-based physical button numbers while internal runtime interfaces remain zero-based.

**Architecture:** Add one shared button-layout module that ties hardware scan order, LCD position, and action labels together. Keep `event.key_number` and runtime callbacks zero-based, convert human-facing debug events to one-based button numbers, and make `GET_RUNTIME_STATUS` always emit compact aliases so host/watch output stays deterministic under the 30-byte HID limit.

**Tech Stack:** CircuitPython, Python, Raw HID, PyQt6, `unittest`, `pytest`, Windows Pico deployment flow

---

## File Structure

### Create

- `pico/button_layout.py`
  - shared source of truth for internal index `0..3`, physical labels `PB1..PB4`, compact physical numbers `1..4`, action labels, and runtime-status alias helpers
- `tests/test_pico_button_layout.py`
  - focused coverage for the mapping, alias helpers, and invalid-index fallback behavior

### Modify

- `pico/lcd_ui.py`
  - consume shared button definitions instead of relying on a bare `ACTIONS` tuple
  - keep exported `ACTIONS` for renderer compatibility
  - convert bridge-mode debug messages from zero-based to one-based button numbers
- `pico/lcd_renderer_spi.py`
  - consume the shared layout metadata or the derived `ACTIONS` export from one source of truth
  - convert renderer debug messages from zero-based to one-based button numbers
- `pico/bridge_runtime.py`
  - convert `button`, `pre_press`, and `post_press` debug messages to one-based button numbers
  - normalize button-specific loop checkpoints for runtime-status serialization input
  - reject unmapped indices before calling UI/render paths
- `pico/upload_protocol.py`
  - make `GET_RUNTIME_STATUS` always emit compact aliases such as `button:1`, `pre:2`, `rdone:4`
  - keep runtime-status text deterministic and under 30 bytes without truncation in normal button flows
- `spark_app_v2.py`
  - move the summarize trigger match from `button:0` to `button:1`
  - keep response-polling behavior otherwise unchanged

### Modify Tests

- `tests/test_pico_bridge_app.py`
- `tests/test_pico_lcd_ui.py`
- `tests/test_pico_lcd_renderer_spi.py`
- `tests/test_pico_bridge_runtime.py`
- `tests/test_pico_upload_protocol.py`
- `tests/test_spark_panel_ui.py`
- `tests/test_watch_full_stack.py`
- `tests/test_pico_monitor.py`
- `tests/test_host_raw_hid_client.py`
- `tests/test_serial_sender.py`

### Verify Only

- `pico/button_input.py`
  - no behavior change expected; use this file to confirm `event.key_number` remains the zero-based input contract
- `pico/bridge_app.py`
  - no behavior change expected beyond continuing to treat internal index `0` as the summarize button path
- `watch_full_stack.py`
  - behavior should remain passthrough; only exact-string expectations in tests should change

## Guardrails

- Keep `ButtonPressed.index`, `event.key_number`, `ui.handle_press(index, ...)`, and `handle_button_press(index)` zero-based.
- The first physical button must still map to internal index `0` and therefore still drive the summarize/synthesis path.
- Use one shared mapping module; do not duplicate PB1/PB4 knowledge across UI, renderer, runtime, and tests.
- `GET_DEBUG_EVENT` should use readable one-based strings like `button:1` and `render_press_done:4`.
- `GET_RUNTIME_STATUS` should always use compact aliases like `pre:2` and `rdone:4`, not long-form button messages.
- Host and watcher output should treat runtime-status aliases as canonical transport text and should not expand them back to long-form names.
- Do not change debounce timing or the one-button-event-per-loop behavior.

## Task 1: Create the Shared Button Layout Contract

**Files:**
- Create: `pico/button_layout.py`
- Create: `tests/test_pico_button_layout.py`
- Verify: `pico/button_input.py`
- Verify: `pico/pin_config.py`

- [ ] **Step 1: Write the failing mapping and alias tests**

Add focused tests in `tests/test_pico_button_layout.py`:

```python
def test_button_definitions_match_hardware_and_lcd_order():
    from pico.button_layout import BUTTON_DEFINITIONS

    assert [(button.index, button.physical_number, button.name, button.action_label) for button in BUTTON_DEFINITIONS] == [
        (0, 1, "PB1", "SYNTHESIS"),
        (1, 2, "PB2", "REFORMAT"),
        (2, 3, "PB3", "SEARCH"),
        (3, 4, "PB4", "RESPOND"),
    ]


def test_button_definitions_follow_pin_config_scan_order():
    from pico.button_layout import BUTTON_DEFINITIONS
    from pico.pin_config import BUTTON_PIN_NUMBERS

    assert [button.index for button in BUTTON_DEFINITIONS] == list(range(len(BUTTON_PIN_NUMBERS)))


def test_debug_label_helpers_convert_zero_based_index_to_one_based_text():
    from pico.button_layout import debug_label, runtime_alias

    assert debug_label("button", 0) == "button:1"
    assert debug_label("render_press_done", 3) == "render_press_done:4"
    assert runtime_alias("render_press_done", 3) == "rdone:4"


def test_invalid_index_falls_back_to_question_mark():
    from pico.button_layout import debug_label, runtime_alias

    assert debug_label("button", 99) == "button:?"
    assert runtime_alias("pre_press", 99) == "pre:?"
```

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_button_layout.py -q
```

Expected: FAIL because `pico/button_layout.py` does not exist yet.

- [ ] **Step 3: Implement the shared mapping and helper API**

Create `pico/button_layout.py` with one small, explicit mapping and helper surface:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonDefinition:
    index: int
    physical_number: int
    name: str
    action_label: str


BUTTON_DEFINITIONS = (
    ButtonDefinition(0, 1, "PB1", "SYNTHESIS"),
    ButtonDefinition(1, 2, "PB2", "REFORMAT"),
    ButtonDefinition(2, 3, "PB3", "SEARCH"),
    ButtonDefinition(3, 4, "PB4", "RESPOND"),
)

ACTIONS = tuple(button.action_label for button in BUTTON_DEFINITIONS)


def button_definition(index):
    ...


def debug_label(kind, index):
    ...


def runtime_alias(kind, index):
    ...
```

Implementation notes:

```text
- keep helper names small and literal
- return `?` fallbacks for unmapped indices
- keep the alias table explicit: button, pre, post, draw, done, idle, rpress, rdone
- keep checkpoint alias helpers explicit too: `before_ui_press` -> `ui_pre`, `after_ui_press` -> `ui_post`
- do not move any behavior out of `button_input.py`; this module is naming metadata only
```

- [ ] **Step 4: Run the new tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_button_layout.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add pico/button_layout.py tests/test_pico_button_layout.py
git commit -m "refactor: add shared pico button layout mapping"
```

## Task 2: Rewire LCD UI and Renderer Around the Shared Mapping

**Files:**
- Modify: `pico/lcd_ui.py`
- Modify: `pico/lcd_renderer_spi.py`
- Modify: `tests/test_pico_lcd_ui.py`
- Modify: `tests/test_pico_lcd_renderer_spi.py`

- [ ] **Step 1: Write the failing LCD and renderer tests**

Add or update tests like:

```python
def test_ui_uses_button_definitions_in_physical_order():
    lcd_ui = _load_module("pico.lcd_ui")
    ui = _make_ui(lcd_ui)

    assert [cell.name for cell in ui.cell_views] == ["PB1", "PB2", "PB3", "PB4"]
    assert [cell.label.text for cell in ui.cell_views] == ["SYNTHESIS", "REFORMAT", "SEARCH", "RESPOND"]


def test_bridge_mode_debug_uses_one_based_button_numbers():
    lcd_ui = _load_module("pico.lcd_ui")
    debug_calls = []
    ui = _make_bridge_ui(lcd_ui)

    ui.set_debug_sender(debug_calls.append)
    ui.handle_press(1, now=10.0)
    ui.handle_press(3, now=10.1)

    assert debug_calls == [
        "draw_press:2",
        "press_done:2",
        "idle_prev:2",
        "draw_press:4",
        "press_done:4",
    ]


def test_renderer_emits_one_based_pressed_cell_stage_debug():
    renderer_spi = _load_module("pico.lcd_renderer_spi")
    target = _FakeBlitTarget()
    debug_calls = []
    renderer = renderer_spi.SpiLcdRenderer(target=target)
    renderer.set_debug_sender(debug_calls.append)
    renderer.draw_pressed_cell(1)

    assert debug_calls == ["render_press:2", "render_press_done:2"]
```

- [ ] **Step 2: Run the LCD-specific tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_lcd_ui.py tests/test_pico_lcd_renderer_spi.py -q
```

Expected: FAIL on the new PB metadata and one-based debug-string assertions.

- [ ] **Step 3: Implement the minimal LCD and renderer rewiring**

Update `pico/lcd_ui.py` and `pico/lcd_renderer_spi.py` to consume `BUTTON_DEFINITIONS` and exported `ACTIONS` from `pico/button_layout.py`:

```python
from pico.button_layout import ACTIONS, BUTTON_DEFINITIONS, button_definition, debug_label


for button in BUTTON_DEFINITIONS:
    x, y = cell_origin(button.index)
    cell_group = self._displayio.Group()
    cell_group.x = x
    cell_group.y = y
    label = self._label.Label(
        self._font,
        text=button.action_label,
        color=WHITE,
        anchor_point=(0.5, 0.5),
        anchored_position=(CELL_W // 2, CELL_H // 2),
    )
    self.cell_views.append(
        CellView(
            index=button.index,
            name=button.name,
            group=cell_group,
            pressed_overlay=pressed_overlay,
            label=label,
        )
    )


self._emit_debug(debug_label("draw_press", index))
```

Implementation notes:

```text
- keep the current 2x2 positions and highlight behavior unchanged
- preserve `ACTIONS` as a tuple export for renderer/test compatibility
- keep renderer drawing by zero-based cell index; only the emitted debug text changes
- do not introduce a second mapping inside the renderer
```

- [ ] **Step 4: Run the LCD-specific tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_lcd_ui.py tests/test_pico_lcd_renderer_spi.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add pico/lcd_ui.py pico/lcd_renderer_spi.py tests/test_pico_lcd_ui.py tests/test_pico_lcd_renderer_spi.py
git commit -m "refactor: align pico lcd button naming with hardware order"
```

## Task 3: Update Bridge Runtime Debug Output and Invalid-Index Safety

**Files:**
- Modify: `pico/bridge_runtime.py`
- Modify: `tests/test_pico_bridge_runtime.py`

- [ ] **Step 1: Write the failing bridge-runtime tests**

Add or update tests like:

```python
def test_bridge_runtime_emits_one_based_button_debug_messages():
    runtime = _make_runtime_with_single_button(index=0, call_log=call_log)
    runtime.run_once(now=1.5)

    assert call_log == [
        ("debug", "button:1"),
        ("debug", "pre_press:1"),
        ("ui", 0, 1.5),
        ("debug", "post_press:1"),
        ("tick", 1.5),
    ]


def test_bridge_runtime_skips_invalid_indices_before_ui_calls():
    from pico.bridge_runtime import BridgeRuntime

    ui_calls = []
    debug_messages = []
    runtime = BridgeRuntime(
        serial_bridge=types.SimpleNamespace(relay_once=lambda *, max_chunk_size: None),
        jetson_transport=types.SimpleNamespace(
            poll=lambda *, max_chunk_size: None,
            request_active=False,
            response_len=0,
            response_complete=False,
            response_bytes=b"",
        ),
        protocol_handler=types.SimpleNamespace(
            update_response_state=lambda response_bytes, *, complete, active: None,
            handle_report=lambda report: None,
        ),
        custom_hid=types.SimpleNamespace(
            get_last_received_report=lambda raw_report_id: None,
            send_report=lambda reply, raw_report_id: None,
        ),
        raw_report_id=9,
        button_input=types.SimpleNamespace(drain_pressed_events=lambda: iter([types.SimpleNamespace(index=99)])),
        ui=types.SimpleNamespace(
            handle_press=lambda index, *, now: ui_calls.append((index, now)),
            tick=lambda *, now: None,
        ),
        time_sleep=lambda _: None,
        debug_sender=lambda message: debug_messages.append(message) or "sent:31",
        heartbeat_interval_s=99.0,
    )

    runtime.run_once(now=2.0)

    assert ui_calls == []
    assert debug_messages == ["button:?"]
```

- [ ] **Step 2: Run the runtime and protocol tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py -q
```

Expected: FAIL on the one-based debug strings and invalid-index skip assertions.

- [ ] **Step 3: Implement the bridge-runtime changes**

Update `pico/bridge_runtime.py` with the shared helpers:

```python
from pico.button_layout import button_definition, debug_label


for button_event in self._button_input.drain_pressed_events():
    if button_definition(button_event.index) is None:
        self._emit_debug(debug_label("button", button_event.index))
        break
    self._emit_debug(debug_label("button", button_event.index))
    ...
    self._emit_debug(debug_label("pre_press", button_event.index))
    ...
    self._emit_debug(debug_label("post_press", button_event.index))
```

Implementation notes:

```text
- keep loop behavior unchanged: debounce, one event per loop, sticky non-heartbeat status
- skip unmapped button indices before UI/render/handler calls while still emitting safe fallback debug text
- preserve heartbeat behavior unchanged
```

- [ ] **Step 4: Run the bridge-runtime tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add pico/bridge_runtime.py tests/test_pico_bridge_runtime.py
git commit -m "refactor: use one-based pico runtime debug labels"
```

## Task 4: Add Deterministic Runtime-Status Aliases

**Files:**
- Modify: `pico/upload_protocol.py`
- Modify: `tests/test_pico_upload_protocol.py`
- Verify: `pico_monitor.py`
- Modify: `tests/test_pico_monitor.py`

- [ ] **Step 1: Write the failing runtime-status alias tests**

Add or update tests like:

```python
def test_get_runtime_status_always_uses_compact_aliases():
    from pico.bridge_app import RuntimeStatus

    self.handler.set_runtime_status_provider(
        lambda: RuntimeStatus(
            cdc_debug_status="render_press_done:4|sent:31",
            loop_checkpoint="after_sleep",
            request_active=True,
            response_length=42,
            response_complete=False,
        )
    )

    reply = self.handler.handle_report(bytes(report))

    assert reply[2:32].split(b"\x00", 1)[0].decode("utf-8") == "rdone:4|after_sleep"


def test_get_runtime_status_normalizes_after_ui_press_checkpoint():
    from pico.bridge_app import RuntimeStatus

    self.handler.set_runtime_status_provider(
        lambda: RuntimeStatus(
            cdc_debug_status="pre_press:2|sent:31",
            loop_checkpoint="after_ui_press:1",
            request_active=True,
            response_length=42,
            response_complete=False,
        )
    )

    reply = self.handler.handle_report(bytes(report))

    assert reply[2:32].split(b"\x00", 1)[0].decode("utf-8") == "pre:2|ui_post"


def test_get_runtime_status_normalizes_before_ui_press_checkpoint():
    from pico.bridge_app import RuntimeStatus

    self.handler.set_runtime_status_provider(
        lambda: RuntimeStatus(
            cdc_debug_status="pre_press:2|sent:31",
            loop_checkpoint="before_ui_press:1",
            request_active=True,
            response_length=42,
            response_complete=False,
        )
    )

    reply = self.handler.handle_report(bytes(report))

    assert reply[2:32].split(b"\x00", 1)[0].decode("utf-8") == "pre:2|ui_pre"


def test_get_runtime_status_button_paths_fit_without_truncation_at_boundary():
    from pico.bridge_app import RuntimeStatus

    self.handler.set_runtime_status_provider(
        lambda: RuntimeStatus(
            cdc_debug_status="render_press_done:4|sent:31",
            loop_checkpoint="after_sleep",
            request_active=True,
            response_length=42,
            response_complete=False,
        )
    )

    reply = self.handler.handle_report(bytes(report))
    text = reply[2:32].split(b"\x00", 1)[0].decode("utf-8")

    assert text == "rdone:4|after_sleep"
    assert len(text) <= 30


def test_runtime_status_never_reintroduces_zero_based_button_indices():
    from pico.bridge_app import RuntimeStatus

    self.handler.set_runtime_status_provider(
        lambda: RuntimeStatus(
            cdc_debug_status="post_press:1|sent:31",
            loop_checkpoint="after_ui_press:1",
            request_active=True,
            response_length=42,
            response_complete=False,
        )
    )

    reply = self.handler.handle_report(bytes(report))
    text = reply[2:32].split(b"\x00", 1)[0].decode("utf-8")

    assert ":0" not in text


def test_pico_monitor_keeps_runtime_status_text_verbatim():
    poller = HIDPoller()
    reply = bytearray(REPORT_SIZE)
    reply[0] = CMD_GET_RUNTIME_STATUS
    reply[1] = RESPONSE_FLAG_ACTIVE
    reply[2:15] = b"pre:2|ui_post"
    poller._send_and_match = lambda command: reply if command == CMD_GET_RUNTIME_STATUS else None

    state = poller.poll()

    assert state.runtime_status_text == "pre:2|ui_post"
```

- [ ] **Step 2: Run the runtime-status tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_upload_protocol.py tests/test_pico_monitor.py -q
```

Expected: FAIL on the compact alias and checkpoint-normalization assertions.

- [ ] **Step 3: Implement deterministic runtime-status alias packing**

Update `pico/upload_protocol.py` to always serialize alias text without relying on truncation:

```python
from pico.button_layout import runtime_alias


def _compact_runtime_text(status):
    debug_message = _runtime_debug_alias(getattr(status, "cdc_debug_status", ""))
    loop_checkpoint = _runtime_checkpoint_alias(getattr(status, "loop_checkpoint", ""))
    text = f"{debug_message}|{loop_checkpoint}" if loop_checkpoint else debug_message
    if len(text) > 30:
        raise ValueError(f"runtime status overflow: {text}")
    return text
```

Implementation notes:

```text
- make runtime-status aliases deterministic; do not switch between long and short forms based on current length
- normalize any button-specific checkpoint fragments before building runtime-status text
- prove the serialized button-path strings fit inside the 30-byte field without relying on truncation
- keep `pico_monitor.py` behavior passthrough; update tests only unless alias text reveals a real parsing bug
```

- [ ] **Step 4: Run the runtime-status tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_upload_protocol.py tests/test_pico_monitor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add pico/upload_protocol.py tests/test_pico_upload_protocol.py tests/test_pico_monitor.py
git commit -m "refactor: compact pico runtime status button labels"
```

## Task 5: Update Host and Watcher Consumers to the New Button Contract

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `tests/test_watch_full_stack.py`
- Modify: `tests/test_host_raw_hid_client.py`
- Modify: `tests/test_serial_sender.py`

- [ ] **Step 1: Write the failing host and watcher tests**

Update or add tests like:

```python
def test_button_one_debug_message_starts_response_polling():
    panel = self._make_panel()
    panel._on_pico_debug_message("button:1")
    assert panel._response_poll_timer.isActive()


def test_other_button_debug_messages_do_not_start_response_polling():
    panel = self._make_panel()
    panel._on_pico_debug_message("button:2")
    assert not panel._response_poll_timer.isActive()


def test_buttons_three_and_four_do_not_start_response_polling():
    panel = self._make_panel()
    panel._on_pico_debug_message("button:3")
    assert not panel._response_poll_timer.isActive()
    panel._on_pico_debug_message("button:4")
    assert not panel._response_poll_timer.isActive()


def test_watcher_renders_compact_runtime_status_aliases():
    state.runtime_status_text = "rdone:4|after_sleep"
    assert "debug=rdone:4|after_sleep" in build_pico_status_line(state)


def test_runtime_status_fallback_logs_alias_when_debug_queue_is_empty():
    hid_client.get_runtime_status.return_value = types.SimpleNamespace(
        active=False,
        complete=False,
        text="pre:2|ui_post",
    )
    hid_client.get_debug_event.return_value = None
    panel = self._make_panel(hid_client=hid_client)

    with mock.patch.object(spark_app_v2.logging.getLogger("pico.debug"), "info") as log_info:
        panel._poll_pico_runtime_status()

    log_info.assert_called_once_with("[PICO] %s", "pre:2|ui_post")


def test_host_runtime_status_parser_accepts_new_text_unchanged():
    info[2:24] = b"rdone:4|after_sleep"
    assert client.get_runtime_status().text == "rdone:4|after_sleep"
```

- [ ] **Step 2: Run the host and watcher tests to verify RED**

Run:

```bash
python -m pytest tests/test_spark_panel_ui.py tests/test_watch_full_stack.py tests/test_host_raw_hid_client.py tests/test_serial_sender.py -q
```

Expected: FAIL on the `button:1` trigger path and updated displayed status/debug text.

- [ ] **Step 3: Implement the minimal host/watch consumer updates**

Make the narrow consumer changes:

```python
def _on_pico_debug_message(self, message: str):
    if message == "button:1" and not self._summary_request_in_flight:
        self._start_device_response_polling()
```

Implementation notes:

```text
- keep the host trigger exact-match and narrow; do not broaden it to all `button:*` values
- keep `SparkHIDClient` and serial packet parsing transport-agnostic; only the expected test strings change
- let watcher output show compact runtime-status aliases exactly as received
- keep `watch_full_stack.py` logic unchanged unless a test proves a real behavioral gap; prefer expectation-only updates there
- keep runtime-status flag-driven polling behavior untouched
```

- [ ] **Step 4: Run the host and watcher tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_spark_panel_ui.py tests/test_watch_full_stack.py tests/test_host_raw_hid_client.py tests/test_serial_sender.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add spark_app_v2.py tests/test_spark_panel_ui.py tests/test_watch_full_stack.py tests/test_host_raw_hid_client.py tests/test_serial_sender.py
git commit -m "fix: align host button polling with physical button numbering"
```

## Task 6: Full Regression and Pico Hardware Validation

**Files:**
- Verify: `tests/test_pico_button_input.py`
- Verify: `tests/test_pico_lcd_ui.py`
- Verify: `tests/test_pico_lcd_renderer_spi.py`
- Verify: `tests/test_pico_bridge_runtime.py`
- Verify: `tests/test_pico_upload_protocol.py`
- Verify: `tests/test_spark_panel_ui.py`
- Verify: `tests/test_watch_full_stack.py`
- Verify: `tests/test_pico_monitor.py`
- Verify: `tests/test_host_raw_hid_client.py`
- Verify: `tests/test_serial_sender.py`
- Verify: `tests/test_pico_bridge_app.py`
- Verify: `watch_full_stack.py`

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
python -m pytest tests/test_pico_button_layout.py tests/test_pico_button_input.py tests/test_pico_bridge_app.py tests/test_pico_lcd_ui.py tests/test_pico_lcd_renderer_spi.py tests/test_pico_bridge_runtime.py tests/test_pico_upload_protocol.py tests/test_spark_panel_ui.py tests/test_watch_full_stack.py tests/test_pico_monitor.py tests/test_host_raw_hid_client.py tests/test_serial_sender.py -q
```

Expected: PASS.

- [ ] **Step 2: Deploy the updated Pico firmware to hardware**

Run:

```bash
python tools/pico/deploy_to_pico.py
```

Expected: deploy completes successfully to the mounted `CIRCUITPY` board.

- [ ] **Step 3: Perform physical validation**

Validate on hardware:

```text
- LCD still shows SYNTHESIS / REFORMAT / SEARCH / RESPOND in the same 2x2 positions
- top-left physical button logs as button 1 and still triggers summarize/synthesis
- top-right, bottom-left, and bottom-right log as buttons 2, 3, and 4 respectively
- bridge/debug output no longer shows zero-based button indices
- host/watch surfaces show compact runtime-status aliases without truncation artifacts
```

- [ ] **Step 4: Do not create an extra aggregate commit**

```text
Tasks 1-4 already include task-level commits. After hardware validation, leave git history as-is unless the execution flow explicitly skipped those earlier commit steps.
```
