# Pico LCD Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crash-prone Pico LCD highlight path with a startup-only display tree that keeps brief press feedback and preserves the current runtime API.

**Architecture:** Split the LCD behavior into a small pure state model plus a renderer that owns a fully prebuilt `displayio` tree. Runtime button presses should only update existing mounted objects, never append, remove, or replace display nodes anywhere in the mounted tree.

**Tech Stack:** CircuitPython, `displayio`, ILI9341, Python `unittest`, `pytest`

---

## File Map

- `pico/lcd_ui.py`
  - Add `SparkLcdState`
  - Add renderer-owned cell view records and static pressed overlays
  - Refactor `SparkLcdUi` to coordinate state + renderer while preserving current public API
- `pico/code.py`
  - Remove LCD runtime workaround flags from the integrated runtime call site
  - Keep heartbeat diagnostics and existing debug hook/checkpoint wiring
- `tests/test_pico_lcd_ui.py`
  - Add state tests
  - Add full-tree structural invariants for `handle_press()` and `tick()`
  - Rewrite legacy tests that depend on `cell_palettes`, `active_cell`, `press_time`, palette-write failure handling, or skip-mode workarounds
- `tests/test_pico_code.py`
  - Update runtime expectations if LCD constants or setup behavior change
  - Keep heartbeat and loop-checkpoint coverage intact
- `pico/lcd_smoke_test.py`
  - Expected to remain unchanged if API compatibility is preserved

## Task 1: Lock Down State Behavior First

**Files:**
- Modify: `tests/test_pico_lcd_ui.py`
- Modify: `pico/lcd_ui.py`
- Test: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Write the failing state tests**

Add focused tests for the new pure state object before writing any production state code.

```python
def test_state_press_sets_active_index_and_deadline(self):
    from pico.lcd_ui import HIGHLIGHT_SEC, SparkLcdState

    state = SparkLcdState()
    changed = state.press(2, now=10.0)

    self.assertTrue(changed)
    self.assertEqual(state.active_index, 2)
    self.assertEqual(state.flash_until, 10.0 + HIGHLIGHT_SEC)


def test_state_same_cell_press_refreshes_deadline(self):
    from pico.lcd_ui import HIGHLIGHT_SEC, SparkLcdState

    state = SparkLcdState()
    state.press(1, now=5.0)
    changed = state.press(1, now=5.2)

    self.assertFalse(changed)
    self.assertEqual(state.active_index, 1)
    self.assertEqual(state.flash_until, 5.2 + HIGHLIGHT_SEC)


def test_state_second_press_replaces_active_index(self):
    from pico.lcd_ui import HIGHLIGHT_SEC, SparkLcdState

    state = SparkLcdState()
    state.press(0, now=1.0)
    changed = state.press(3, now=1.1)

    self.assertTrue(changed)
    self.assertEqual(state.active_index, 3)
    self.assertEqual(state.flash_until, 1.1 + HIGHLIGHT_SEC)


def test_state_tick_before_deadline_keeps_active_index(self):
    from pico.lcd_ui import HIGHLIGHT_SEC, SparkLcdState

    state = SparkLcdState()
    state.press(0, now=2.0)

    changed = state.tick(now=2.0 + HIGHLIGHT_SEC - 0.01)

    self.assertFalse(changed)
    self.assertEqual(state.active_index, 0)


def test_state_tick_after_deadline_clears_active_index(self):
    from pico.lcd_ui import HIGHLIGHT_SEC, SparkLcdState

    state = SparkLcdState()
    state.press(0, now=2.0)

    changed = state.tick(now=2.0 + HIGHLIGHT_SEC + 0.01)

    self.assertTrue(changed)
    self.assertIsNone(state.active_index)
```

- [ ] **Step 2: Run the state tests to verify RED**

Put the new state tests in a dedicated `SparkLcdStateTests` class or use stable node IDs.

Run: `python -m pytest tests/test_pico_lcd_ui.py -k "SparkLcdStateTests or state_" -q`

Expected: FAIL with `ImportError`, `AttributeError`, or missing `SparkLcdState` behavior.

- [ ] **Step 3: Write the minimal `SparkLcdState` implementation**

Add a small state class to `pico/lcd_ui.py`.

```python
class SparkLcdState:
    def __init__(self):
        self.active_index = None
        self.flash_until = 0.0

    def press(self, index, *, now):
        changed = self.active_index != index
        self.active_index = index
        self.flash_until = now + HIGHLIGHT_SEC
        return changed

    def tick(self, *, now):
        if self.active_index is None or now <= self.flash_until:
            return False
        self.active_index = None
        return True
```

- [ ] **Step 4: Run the state tests to verify GREEN**

Run: `python -m pytest tests/test_pico_lcd_ui.py -k "SparkLcdStateTests or state_" -q`

Expected: the new state tests pass, even if renderer-related tests still fail.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pico_lcd_ui.py pico/lcd_ui.py
git commit -m "test: lock down pico lcd flash state behavior"
```

## Task 2: Lock Down Renderer Structural Invariants

**Files:**
- Modify: `tests/test_pico_lcd_ui.py`
- Modify: `pico/lcd_ui.py`
- Test: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Extend test doubles for a static-tree renderer test**

Update the fake `displayio` objects in `tests/test_pico_lcd_ui.py` so the tests can inspect mounted object identity without relying on real CircuitPython objects.

Add support like this:

```python
class FakeTileGrid:
    def __init__(self, bitmap, *, pixel_shader, x, y):
        self.bitmap = bitmap
        self.pixel_shader = pixel_shader
        self.x = x
        self.y = y
        self.hidden = False


def snapshot_tree(node):
    children = []
    if isinstance(node, list):
        for child in node:
            children.append(snapshot_tree(child))
    return (id(node), tuple(children))
```

- [ ] **Step 2: Write the failing renderer tests**

Add tests that capture the full mounted tree before and after `handle_press()` and `tick()`.

```python
def test_handle_press_keeps_full_display_tree_shape(self):
    before = snapshot_tree(self.ui.root_group)
    self.ui.handle_press(0, now=5.0)
    after = snapshot_tree(self.ui.root_group)
    self.assertEqual(before[0], after[0])
    self.assertEqual(before[1], after[1])
    self.assert_cell_pressed(0)


def test_tick_keeps_full_display_tree_shape(self):
    self.ui.handle_press(0, now=5.0)
    before = snapshot_tree(self.ui.root_group)
    self.ui.tick(now=5.0 + self.HIGHLIGHT_SEC + 0.01)
    after = snapshot_tree(self.ui.root_group)
    self.assertEqual(before[0], after[0])
    self.assertEqual(before[1], after[1])
    self.assert_cell_idle(0)
```

Also add an assertion that the same-cell re-press refreshes the timeout without requiring a tree shape change.

Keep the renderer assertions mechanism-agnostic. Add helpers like `assert_cell_pressed(index)` / `assert_cell_idle(index)` so the tests can survive an internal fallback from overlay visibility toggles to another prebuilt-object strategy while still enforcing visible behavior plus tree invariants.

Legacy LCD tests to rewrite or delete in this task before GREEN:

- tests that assert direct `cell_palettes` contents
- tests that assert public `active_cell` or `press_time` internals
- the palette-write error test tied to the old implementation
- skip-mode tests for `skip_palette_write` and `skip_highlight_update`
- tests that inspect `_highlight_grid` membership in `root_group`

- [ ] **Step 3: Run the renderer tests to verify RED**

Put the new renderer invariants in a dedicated `SparkLcdRendererTests` class or use stable node IDs.

Run: `python -m pytest tests/test_pico_lcd_ui.py -k "SparkLcdRendererTests or tree_shape or tree_invariant" -q`

Expected: FAIL because the current implementation removes/appends `_highlight_grid` and does not expose a stable static-tree renderer.

- [ ] **Step 4: Refine the tests until they fail for the correct reason**

The failure must prove one of these, not a typo:

- mounted tree structure changes during press handling
- no stable overlay visibility strategy exists yet
- same-cell re-press deadline refresh is missing

- [ ] **Step 5: Optional local-only checkpoint**

```bash
git add tests/test_pico_lcd_ui.py
git commit -m "test: capture pico lcd tree invariants"
```

Do not push or keep this commit if the branch is intentionally red. This step is only for a local TDD checkpoint.

## Task 3: Replace the Movable Highlight With Static Cell Views

**Files:**
- Modify: `pico/lcd_ui.py`
- Test: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Implement explicit per-cell view records**

Replace the loose `cell_palettes` + `_highlight_grid` structure with explicit per-cell state owned by the renderer.

Minimal direction:

```python
class CellView:
    def __init__(self, *, index, label, base_grid, pressed_overlay):
        self.index = index
        self.label = label
        self.base_grid = base_grid
        self.pressed_overlay = pressed_overlay
```

Use `collections.namedtuple`, a tiny class, or a dataclass only if it keeps the file simpler.

- [ ] **Step 2: Create `SparkLcdRenderer` explicitly**

Add `SparkLcdRenderer` in `pico/lcd_ui.py` as the owner of the mounted display tree.

It must:

- own `root_group`
- build the full display tree once at startup
- store `cell_views`
- expose `apply_state(state)`

Compatibility rule: keep `SparkLcdUi` as the public controller and preserve `ui.root_group = renderer.root_group` so `initialize_lcd_ui()` and the tests can continue to use `ui.root_group`.

If direct `SparkLcdUi(...)` construction becomes awkward in tests, add a tiny test helper or factory in `tests/test_pico_lcd_ui.py` rather than preserving the old constructor shape artificially.

- [ ] **Step 3: Build all pressed overlays at startup**

Refactor `_build_idle_screen()` so each cell mounts both its idle visuals and its pressed overlay immediately.

Implementation target:

```python
pressed_overlay = self._displayio.TileGrid(
    bitmap,
    pixel_shader=pressed_palette,
    x=x,
    y=y,
)
pressed_overlay.hidden = True
cell_group.append(pressed_overlay)
```

Required layering per cell:

- base fill
- pressed overlay
- borders or accent lines
- label

The pressed flash must not cover the label or border accents.

If `hidden` is not viable on real hardware, keep the public structure the same and switch the internal renderer only to the approved fallback from the spec: mutate pre-existing palette entries on already-mounted cell objects. Do not allocate, swap, or replace `TileGrid`, `Label`, `Palette`, or `pixel_shader` objects at runtime.

- [ ] **Step 4: Refactor `SparkLcdUi` to use state + renderer**

Update `handle_press()` and `tick()` so they become state-driven.

```python
def handle_press(self, index, *, now):
    changed = self._state.press(index, now=now)
    if changed:
        self._renderer.apply_state(self._state)


def tick(self, *, now):
    if self._state.tick(now=now):
        self._renderer.apply_state(self._state)
```

Adjust this slightly so same-cell re-presses refresh the timer without skipping any required debug checkpoint updates.

Add or preserve a regression test in `tests/test_pico_lcd_ui.py` that `debug_checkpoint="after_press_time"` still emits `lcd:handle_press:after_press_time index=<n>` on press, and keep `pico/code.py`'s `LCD_DEBUG_CHECKPOINT` constant aligned with a real checkpoint string used by `handle_press()`.

- [ ] **Step 5: Preserve the public API while deleting workaround-only branches**

Keep:

- `ACTIONS`
- `initialize_lcd_ui()`
- `initialize_lcd_ui(debug_hook=..., debug_checkpoint=...)`
- returned UI methods `handle_press()` and `tick()`

Remove or inline old workaround-specific paths once the static renderer is in place:

- `_set_highlight()`
- `skip_highlight_update`
- `skip_palette_write`
- code that only exists to avoid the old movable highlight mutation path

As part of this task, rewrite the LCD tests that referenced deleted internals so the test suite describes visible behavior and tree invariants rather than the old implementation details.

Compatibility decision for this task: keep the public `skip_palette_write` and `skip_highlight_update` kwargs temporarily during Task 3 while the internal state/renderer refactor and LCD test rewrites land. Delete those public `skip_*` kwargs only in Task 4, in the same change that updates `pico/code.py`, `tests/test_pico_code.py`, and the LCD API tests. Do not keep them as silent no-op kwargs after Task 4.

- [ ] **Step 6: Run the LCD tests to verify GREEN**

Run: `python -m pytest tests/test_pico_lcd_ui.py -q`

Expected: all LCD UI tests pass with the new renderer.

- [ ] **Step 7: Commit**

```bash
git add pico/lcd_ui.py tests/test_pico_lcd_ui.py
git commit -m "feat: redesign pico lcd renderer around static cell views"
```

## Task 4: Reconnect the Runtime Without LCD Workaround Flags

**Files:**
- Modify: `pico/code.py`
- Modify: `tests/test_pico_code.py`
- Modify: `tests/test_pico_lcd_ui.py`
- Modify: `pico/lcd_ui.py`
- Test: `tests/test_pico_code.py`
- Test: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Write the failing runtime expectation**

Add or update tests that prove:

- the integrated runtime still relies on the same LCD entry points and only passes `debug_hook` and `debug_checkpoint` into `initialize_lcd_ui(...)`
- the public LCD API no longer accepts `skip_palette_write` and `skip_highlight_update`

This is the task where the public `skip_*` kwargs are removed.

Example direction:

```python
def test_main_passes_only_debug_kwargs_to_initialize_lcd_ui(self):
    module = self._load_code_module()
    captured = {}

    def fake_initialize_lcd_ui(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after lcd init")

    # preload fake modules in sys.modules for board, busio, keypad,
    # supervisor, usb_cdc, usb_hid, pico.pin_config,
    # pico.jetson_transport, pico.serial_bridge,
    # pico.upload_protocol, and pico.usb_config
    # so _main(...) can reach initialize_lcd_ui(...)
    # also preload sys.modules["pico.lcd_ui"] with
    # initialize_lcd_ui = fake_initialize_lcd_ui so the in-function import
    # binds to the fake module and stops immediately after capturing kwargs
```

The assertion should check that the captured kwargs are exactly `debug_hook` and `debug_checkpoint`.

Implementation note for the engineer: reuse the existing `_load_code_module()` test harness, add fake module objects to `sys.modules`, explicitly install a fake `pico.lcd_ui` module exposing `initialize_lcd_ui = fake_initialize_lcd_ui`, optionally install `lcd_ui` too if the fallback import branch is being tested, make `fake_initialize_lcd_ui(**kwargs)` raise after capturing, then call `_main(record_step)` and assert the captured keys after the intentional stop.

Add a direct LCD API cleanup test in this task as well. Example direction:

```python
def test_initialize_lcd_ui_rejects_removed_skip_kwargs(self):
    from pico import lcd_ui

    with self.assertRaises(TypeError):
        lcd_ui.initialize_lcd_ui(skip_palette_write=True)
```

If direct `initialize_lcd_ui(...)` import setup is too heavy in unit tests, inspect the callable signature instead and assert the deprecated kwarg names are gone.

Minimum fake API surface needed to reach `fake_initialize_lcd_ui(...)`:

- `board.GP0`, `board.GP1`, and the button `GP*` pins referenced by `BUTTON_PIN_NUMBERS`
- `supervisor.runtime.autoreload`
- `busio.UART(...)`
- `keypad.Keys(...)`
- `usb_cdc.data`
- `usb_hid.devices` containing one object with matching `usage_page` and `usage`
- `UploadProtocolHandler(...)`
- `SerialBridge(...)`
- `JetsonTransport(...)`
- `RAW_REPORT_ID`, `RAW_USAGE_ID`, and `RAW_USAGE_PAGE`

These fakes only need to satisfy setup until the intentional `RuntimeError("stop after lcd init")`.

- [ ] **Step 2: Run the Pico runtime tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_code.py -q
python -m pytest tests/test_pico_lcd_ui.py -k "rejects_removed_skip_kwargs or removed_skip_kwargs" -q
```

Expected: FAIL because `pico/code.py` still carries the old skip-mode setup.

- [ ] **Step 3: Update `pico/code.py` minimally**

Keep:

- `CDC_DEBUG_HEARTBEAT_S`
- `_send_button_debug()`
- `LCD_DEBUG_CHECKPOINT`
- existing heartbeat and loop-checkpoint behavior

Remove the LCD workaround wiring from both `pico/code.py` and `pico/lcd_ui.py` so the runtime simply uses the redesigned safe renderer.

Target shape:

```python
lcd_ui = initialize_lcd_ui(
    debug_hook=_send_button_debug,
    debug_checkpoint=LCD_DEBUG_CHECKPOINT,
)
```

- [ ] **Step 4: Run the Pico runtime tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_code.py -q
python -m pytest tests/test_pico_lcd_ui.py -k "rejects_removed_skip_kwargs or removed_skip_kwargs" -q
```

Expected: all Pico runtime tests pass with heartbeat behavior unchanged.

- [ ] **Step 5: Commit**

```bash
git add pico/code.py pico/lcd_ui.py tests/test_pico_code.py tests/test_pico_lcd_ui.py
git commit -m "refactor: remove pico lcd runtime workaround flags"
```

## Task 5: End-to-End Verification and Hardware Validation Notes

**Files:**
- Modify: `tests/test_pico_lcd_ui.py` if any final expectation adjustments are still needed
- Test: `tests/test_pico_lcd_ui.py`
- Test: `tests/test_pico_code.py`
- Test: `tests/test_pico_runtime_runner.py`
- Test: `tests/test_watch_pico_cdc_debug.py`

- [ ] **Step 1: Run the full focused verification suite**

Run:

```bash
python -m pytest tests/test_pico_lcd_ui.py -q
python -m pytest tests/test_pico_code.py -q
python -m pytest tests/test_pico_runtime_runner.py -q
python -m pytest tests/test_watch_pico_cdc_debug.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Check the worktree before any optional commit squashing or PR work**

Run: `git status --short`

Expected: only intended LCD/runtime test and implementation files are modified.

- [ ] **Step 3: Perform the real-hardware validation checklist**

Manual hardware steps:

1. Deploy the updated Pico firmware to `CIRCUITPY`.
2. Physically reset the Pico so the new `code.py` is live.
3. Start `watch_pico_cdc_debug.py` against the Pico CDC port.
4. Confirm heartbeat packets continue.
5. Press PB1 through PB4 repeatedly.
6. Confirm the board stays enumerated, the heartbeat continues, and each pressed cell flashes briefly.
7. Press the same button repeatedly and confirm the flash duration refreshes each time.

- [ ] **Step 4: Validate the smoke-test compatibility path**

Confirm the zero-argument LCD entry point still works for `pico/lcd_smoke_test.py`.

Preferred check:

1. Deploy `pico/lcd_smoke_test.py` as `code.py` on the Pico.
2. Physically reset the board.
3. Confirm the LCD initializes successfully.
4. Press PB1 through PB4 and confirm the same brief flash behavior appears.

- [ ] **Step 5: Capture any hardware-specific fallback decision if needed**

If prebuilt overlay visibility toggles are unstable on real hardware, switch to the fallback renderer path described in the spec without changing the public LCD API, then rerun Task 5 Step 1 and Step 3.

Any fallback implementation must keep the renderer-agnostic visible-state assertions and full-tree structural invariants from Task 2 passing.

- [ ] **Step 6: Commit**

```bash
git add pico/lcd_ui.py pico/code.py tests/test_pico_lcd_ui.py tests/test_pico_code.py
git commit -m "fix: restore stable pico lcd press feedback"
```
