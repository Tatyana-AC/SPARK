# Pico Bridge + LCD Runtime Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Pico runtime that keeps SPARK bridge communication working while supporting interactive LCD updates through a new bridge-mode LCD backend that does not depend on runtime `displayio` mutation.

**Architecture:** Keep the known-good `sida` bridge/runtime behavior as the baseline, move `pico/code.py` to a composition-root role, extract bridge and input services into focused modules, and add a separate bridge-mode LCD renderer backend that owns LCD initialization and runtime drawing from start to finish. The standalone LCD mode may keep a simpler path, but bridge mode must stop depending on the current integrated `displayio` runtime model.

**Tech Stack:** CircuitPython, RP2040, Raw HID, `usb_cdc`, UART, ILI9341 SPI LCD, Python `unittest`, `pytest`, manual `CIRCUITPY` deployment on Windows

---

## File Structure

### Existing files to modify

- `pico/code.py`
  - reduce to composition/wiring only
- `pico/lcd_ui.py`
  - keep public LCD facade, add explicit mode selection, and route bridge mode into the new renderer backend
- `pico/upload_protocol.py`
  - make the protocol layer compatible with extracted app behavior if needed
- `tests/test_pico_code.py`
  - preserve runtime wiring coverage while shrinking direct logic in `code.py`
- `tests/test_pico_lcd_ui.py`
  - keep facade/API coverage and mode-selection tests
- `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`
  - append new hardware validation results as work proceeds

### New files to create

- `pico/bridge_runtime.py`
  - active loop orchestration and runtime checkpoints
- `pico/bridge_app.py`
  - app-command behavior and response composition
- `pico/button_input.py`
  - keypad initialization and normalized button events
- `pico/lcd_state.py`
  - pure LCD interaction state
- `pico/lcd_renderer_spi.py`
  - bridge-mode runtime-safe LCD renderer backend
- `tests/test_pico_bridge_runtime.py`
- `tests/test_pico_bridge_app.py`
- `tests/test_pico_button_input.py`
- `tests/test_pico_lcd_state.py`
- `tests/test_pico_lcd_renderer_spi.py`

### Files that should stay mostly stable

- `pico/serial_bridge.py`
- `pico/jetson_transport.py`
- `pico/runtime_runner.py`

## Guardrails

- Treat `sida` transport runtime behavior as the contract to preserve.
- Do not use the current integrated `displayio` mutation path as the bridge-mode renderer.
- Do not reintroduce LCD assets into `tools/pico/deploy_to_pico.py` until the new integrated runtime is hardware-stable.
- Keep the experimental work in the recovery worktree until all hardware gates pass.
- If the bridge-mode renderer proof spike fails the first hardware gate, stop and switch to the fallback dual-mode architecture instead of continuing to refactor blindly.

## Task 1: Build a Bridge-Mode LCD Renderer Proof Spike

**Files:**
- Create: `pico/lcd_renderer_spi.py`
- Create: `pico/lcd_bridge_spike.py`
- Create: `tests/test_pico_lcd_renderer_spi.py`
- Modify: `pico/lcd_ui.py`
- Test: `tests/test_pico_lcd_renderer_spi.py`

- [ ] **Step 1: Write the failing renderer-backend tests**

Cover at minimum:

```python
def test_renderer_draws_idle_layout_once():
    ...

def test_renderer_redraws_single_pressed_cell_region():
    ...

def test_renderer_clears_pressed_cell_without_displayio_mutation_calls():
    ...
```

- [ ] **Step 2: Run the renderer tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_lcd_renderer_spi.py -q
```

Expected: FAIL because `pico/lcd_renderer_spi.py` does not exist yet.

- [ ] **Step 3: Implement the minimal bridge-mode renderer backend**

Requirements:

```text
- add an explicit mode selector such as `initialize_lcd_ui(mode="bridge")`
- keep zero-argument `initialize_lcd_ui()` valid for standalone callers
- own LCD initialization for bridge mode
- draw full idle screen at startup
- redraw only changed cell rectangles on press/clear
- no bridge-mode displayio scene graph ownership
```

- [ ] **Step 4: Run the renderer tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_lcd_renderer_spi.py -q
```

- [ ] **Step 5: Wire the proof spike into the LCD facade without touching the bridge runtime yet**

Constraint: keep standalone mode behavior intact while adding bridge-mode selection support.

Required compatibility in this task:

```text
- ACTIONS
- zero-argument initialize_lcd_ui()
- SparkLcdUi export
- build_display_bus export
- build_display export
```

- [ ] **Step 5.1: Add a temporary bridge-mode hardware spike harness**

Create a small one-purpose entry point such as `pico/lcd_bridge_spike.py` that:

```text
- initializes the new bridge-mode LCD backend explicitly
- auto-triggers one highlight update after boot
- emits a simple debug marker before and after the visual update
- avoids the full bridge runtime so the renderer proof is isolated
```

- [ ] **Step 6: Deploy the proof spike manually to the Pico and verify the first hardware gate**

Manual deploy file set:

```powershell
Copy-Item pico\lcd_bridge_spike.py D:\code.py
Copy-Item pico\lcd_renderer_spi.py D:\lcd_renderer_spi.py
Copy-Item pico\lcd_ui.py D:\lcd_ui.py
Copy-Item pico\pin_config.py D:\pin_config.py
```

Then physically reset the Pico before judging the result.

Hardware validation:

```text
- boot bridge-mode display init
- auto-trigger one visual cell update without button input
- verify no white screen
- verify no disconnect
```

These checks intentionally validate only the renderer spike itself. HID `ping()` and CDC heartbeat checks belong to the later integrated-runtime hardware ladder after the bridge runtime is wired back in.

- [ ] **Step 7: Commit the renderer proof spike**

```bash
git add pico/lcd_renderer_spi.py pico/lcd_ui.py tests/test_pico_lcd_renderer_spi.py
git commit -m "feat: add bridge-mode pico lcd renderer spike"
```

## Task 2: Extract Bridge App Logic Out of `pico/code.py`

**Files:**
- Create: `pico/bridge_app.py`
- Modify: `pico/code.py`
- Modify: `pico/upload_protocol.py`
- Create: `tests/test_pico_bridge_app.py`
- Modify: `tests/test_pico_code.py`

- [ ] **Step 1: Write failing tests for extracted app-command behavior**

Cover at minimum:

```python
def test_feature_1_forwards_to_jetson_request_when_idle():
    ...

def test_feature_1_returns_busy_when_request_active():
    ...

def test_echo_response_formats_runtime_status_text():
    ...
```

- [ ] **Step 2: Run the new bridge-app tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_bridge_app.py -q
```

- [ ] **Step 3: Implement `pico/bridge_app.py` with explicit runtime-status input**

Required boundary:

```text
- no module-global jetson transport coupling
- no loop scheduling logic
- app behavior only
```

- [ ] **Step 4: Update `pico/code.py` to stop owning app-command composition directly**

- [ ] **Step 5: Update `pico/upload_protocol.py` only as needed for the new app hook shape**

- [ ] **Step 6: Run bridge-app and runtime tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_bridge_app.py tests/test_pico_code.py tests/test_pico_upload_protocol.py -q
```

- [ ] **Step 7: Commit the bridge-app extraction**

```bash
git add pico/bridge_app.py pico/code.py pico/upload_protocol.py tests/test_pico_bridge_app.py tests/test_pico_code.py
git commit -m "refactor: extract pico bridge app behavior"
```

## Task 3: Extract Button Input Into Its Own Module

**Files:**
- Create: `pico/button_input.py`
- Create: `tests/test_pico_button_input.py`
- Modify: `pico/code.py`
- Modify: `tests/test_pico_code.py`

- [ ] **Step 1: Write failing tests for normalized button input behavior**

Cover at minimum:

```python
def test_button_input_initializes_keypad_from_shared_pin_config():
    ...

def test_button_input_yields_pressed_events_only():
    ...

def test_button_input_does_not_own_ui_or_bridge_side_effects():
    ...
```

- [ ] **Step 2: Run the button-input tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_button_input.py -q
```

- [ ] **Step 3: Implement `pico/button_input.py`**

Required boundary:

```text
- keypad setup
- event drain
- normalized pressed events only
- no LCD drawing
- no bridge app behavior
```

- [ ] **Step 4: Update `pico/code.py` to consume normalized button events**

- [ ] **Step 5: Run button-input and runtime tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_button_input.py tests/test_pico_code.py -q
```

- [ ] **Step 6: Commit the button-input extraction**

```bash
git add pico/button_input.py pico/code.py tests/test_pico_button_input.py tests/test_pico_code.py
git commit -m "refactor: extract pico button input service"
```

## Task 4: Extract the Active Bridge Runtime Loop

**Files:**
- Create: `pico/bridge_runtime.py`
- Create: `tests/test_pico_bridge_runtime.py`
- Modify: `pico/code.py`
- Modify: `tests/test_pico_code.py`

- [ ] **Step 1: Write failing tests for runtime loop orchestration**

Cover at minimum:

```python
def test_bridge_runtime_run_once_orders_services_correctly():
    ...

def test_bridge_runtime_updates_loop_checkpoint_and_heartbeat():
    ...

def test_bridge_runtime_passes_button_events_to_ui_without_bridge_side_effects():
    ...
```

- [ ] **Step 2: Run the bridge-runtime tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py -q
```

- [ ] **Step 3: Implement `pico/bridge_runtime.py`**

Required surface:

```text
- owns service order
- owns heartbeat timing
- owns loop checkpoint state
- exposes current runtime status snapshot
```

- [ ] **Step 4: Reduce `pico/code.py` to hardware creation + runtime start**

- [ ] **Step 5: Run runtime-focused tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py tests/test_pico_code.py tests/test_pico_bridge_app.py tests/test_pico_button_input.py -q
```

- [ ] **Step 6: Commit the runtime-loop extraction**

```bash
git add pico/bridge_runtime.py pico/code.py tests/test_pico_bridge_runtime.py tests/test_pico_code.py
git commit -m "refactor: extract pico bridge runtime loop"
```

## Task 5: Extract Pure LCD State From The Facade

**Files:**
- Create: `pico/lcd_state.py`
- Create: `tests/test_pico_lcd_state.py`
- Modify: `pico/lcd_ui.py`
- Modify: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Write failing tests for pure LCD state transitions**

Cover at minimum:

```python
def test_press_sets_active_index_and_deadline():
    ...

def test_same_cell_repress_refreshes_deadline():
    ...

def test_tick_clears_after_timeout():
    ...
```

- [ ] **Step 2: Run the LCD-state tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_lcd_state.py -q
```

- [ ] **Step 3: Implement `pico/lcd_state.py` and update `pico/lcd_ui.py` to use it**

- [ ] **Step 4: Preserve the public facade API**

Required compatibility:

```text
- ACTIONS
- initialize_lcd_ui(...)
- SparkLcdUi
- build_display_bus
- build_display
- handle_press(index, now=...)
- tick(now=...)
```

- [ ] **Step 5: Run LCD-state and LCD-facade tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_lcd_state.py tests/test_pico_lcd_ui.py -q
```

- [ ] **Step 6: Commit the LCD-state extraction**

```bash
git add pico/lcd_state.py pico/lcd_ui.py tests/test_pico_lcd_state.py tests/test_pico_lcd_ui.py
git commit -m "refactor: extract pico lcd state model"
```

## Task 6: Integrate The New Bridge-Mode LCD Backend Into The Active Runtime

**Files:**
- Modify: `pico/lcd_ui.py`
- Modify: `pico/lcd_renderer_spi.py`
- Modify: `pico/bridge_runtime.py`
- Modify: `tests/test_pico_code.py`
- Modify: `tests/test_pico_bridge_runtime.py`
- Modify: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Write failing integration tests for runtime-side UI updates through the new backend**

Cover at minimum:

```python
def test_bridge_runtime_forwards_pressed_button_to_lcd_ui():
    ...

def test_bridge_runtime_ticks_lcd_ui_each_loop():
    ...

def test_lcd_ui_bridge_mode_selects_non_displayio_renderer():
    ...
```

- [ ] **Step 2: Run the focused integration tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_bridge_runtime.py tests/test_pico_lcd_ui.py -q
```

- [ ] **Step 3: Implement the bridge-mode runtime integration**

Constraints:

```text
- no integrated displayio mutation path in bridge mode
- no auto-probe left in steady-state runtime
- no serial_bridge.inject_button_press()
- button events flow to lcd_ui through bridge_runtime only, not into bridge_app
```

- [ ] **Step 4: Run the combined Pico runtime test set to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_code.py tests/test_pico_bridge_runtime.py tests/test_pico_bridge_app.py tests/test_pico_button_input.py tests/test_pico_lcd_state.py tests/test_pico_lcd_ui.py tests/test_pico_lcd_renderer_spi.py tests/test_pico_upload_protocol.py tests/test_pico_jetson_transport.py tests/test_pico_serial_bridge.py -q
```

- [ ] **Step 5: Commit the integrated runtime redesign**

```bash
git add pico/lcd_ui.py pico/lcd_renderer_spi.py pico/bridge_runtime.py tests/test_pico_code.py tests/test_pico_bridge_runtime.py tests/test_pico_lcd_ui.py tests/test_pico_lcd_renderer_spi.py
git commit -m "feat: integrate bridge-safe pico lcd runtime"
```

## Task 7: Hardware Validation Ladder For The New Integrated Runtime

**Files:**
- Modify: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`

- [ ] **Step 1: Manually deploy the redesigned runtime bundle to `CIRCUITPY`**

Deploy file set:

```powershell
Copy-Item pico\code.py D:\code.py
Copy-Item pico\bridge_runtime.py D:\bridge_runtime.py
Copy-Item pico\bridge_app.py D:\bridge_app.py
Copy-Item pico\button_input.py D:\button_input.py
Copy-Item pico\lcd_state.py D:\lcd_state.py
Copy-Item pico\lcd_renderer_spi.py D:\lcd_renderer_spi.py
Copy-Item pico\lcd_ui.py D:\lcd_ui.py
Copy-Item pico\pin_config.py D:\pin_config.py
Copy-Item pico\jetson_transport.py D:\jetson_transport.py
Copy-Item pico\serial_bridge.py D:\serial_bridge.py
Copy-Item pico\upload_protocol.py D:\upload_protocol.py
Copy-Item pico\usb_config.py D:\usb_config.py
Copy-Item pico\protocol.py D:\protocol.py
Copy-Item pico\pico_debug.py D:\pico_debug.py
Copy-Item pico\runtime_runner.py D:\runtime_runner.py
```

- [ ] **Step 2: Physically reset the Pico before each rung evaluation**

- [ ] **Step 3: Validate boot + idle LCD + HID ping**

Pass criteria:

```text
- LCD boots into idle screen
- no white screen
- HID ping returns OK spark ready
- CDC heartbeat visible
```

- [ ] **Step 4: Validate single button highlight with no Jetson summarize traffic**

Pass criteria:

```text
- PB1 visibly highlights
- no disconnect
- no white screen
- ping still works after press
```

- [ ] **Step 5: Validate repeated PB1-PB4 presses with no summarize traffic**

Pass criteria:

```text
- PB1-PB4 all visibly respond
- repeated presses do not white-screen the LCD
- repeated presses do not disconnect or stall the Pico
- HID ping still works after the press sequence
- CDC heartbeat remains visible after the press sequence
```

- [ ] **Step 6: Validate repeated button presses during summarize traffic**

Pass criteria:

```text
- summarize still streams correctly
- LCD interaction still works
- runtime does not stall
```

- [ ] **Step 7: Run `setup_spark.ps1` as the final end-to-end proof**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_spark.ps1
```

Expected:

```text
- smoke test passes
- app launches
- LCD interaction still remains stable
```

- [ ] **Step 8: Append exact hardware results to the investigation doc**

- [ ] **Step 9: Commit the validated hardware findings**

```bash
git add docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md
git commit -m "docs: record redesigned pico lcd runtime validation"
```

## Task 8: Reintroduce Deploy Support Only After Hardware Stability

**Files:**
- Modify: `tools/pico/deploy_to_pico.py`
- Modify: `tests/test_pico_deploy_to_pico.py`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`
- Modify: `README.md`
- Modify: `REPO_STRUCTURE.md`

- [ ] **Step 1: Write failing deploy tests for the restored integrated LCD assets**

- [ ] **Step 2: Run the deploy tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_deploy_to_pico.py -q
```

- [ ] **Step 3: Restore the required bridge-mode LCD files and libraries to the deploy manifest**

- [ ] **Step 4: Run deploy tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_deploy_to_pico.py -q
```

- [ ] **Step 5: Update user-facing docs to reflect the supported integrated LCD runtime**

- [ ] **Step 6: Commit deploy and documentation support**

```bash
git add tools/pico/deploy_to_pico.py tests/test_pico_deploy_to_pico.py docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md README.md REPO_STRUCTURE.md
git commit -m "build: restore deploy support for redesigned pico lcd runtime"
```

## Stop Conditions

- Stop immediately if the bridge-mode LCD renderer proof spike fails the first hardware gate.
- Stop immediately if integrated runtime visual updates still white-screen or stall the board under the new non-`displayio` renderer.
- Stop immediately if bridge communication regresses below current `sida` behavior.
- If Tasks 1-6 pass in tests but Task 7 still fails at the first hardware visual rung, switch to the fallback dual-mode architecture instead of continuing to patch the integrated design.

## Verification Checklist

- `python -m pytest tests/test_pico_bridge_runtime.py -q`
- `python -m pytest tests/test_pico_bridge_app.py -q`
- `python -m pytest tests/test_pico_button_input.py -q`
- `python -m pytest tests/test_pico_lcd_state.py -q`
- `python -m pytest tests/test_pico_lcd_renderer_spi.py -q`
- `python -m pytest tests/test_pico_lcd_ui.py tests/test_pico_code.py tests/test_pico_upload_protocol.py tests/test_pico_jetson_transport.py tests/test_pico_serial_bridge.py -q`
- hardware boot + idle LCD + HID ping
- repeated interactive button presses under no-load and summarize-load conditions
- final `setup_spark.ps1` success on the redesigned runtime

## Expected Outcome

If this plan succeeds, the Pico will run bridge communication and interactive LCD updates simultaneously under a redesigned runtime with clearer module boundaries. If it fails at the renderer proof spike or first integrated hardware visual gate, the result should still be decisive enough to justify a formal switch to separate bridge and LCD operating modes.
