# Pico LCD Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Pico-side LCD implementation, make PB1-PB4 inert in the active runtime, and clean up deploy/tests/docs so the repo no longer treats LCD support as part of the shipped Pico firmware.

**Architecture:** Strip the active Pico runtime down to CDC relay, Raw HID handling, and Jetson summarize transport only. Delete LCD/button-only Pico modules and deploy assets, then rewrite tests and active docs so they validate and describe the transport-only firmware shape.

**Tech Stack:** CircuitPython, Python `unittest`/`pytest`, repo Markdown docs, exact-sync deploy helper

---

## File Map

- Delete: `pico/lcd_ui.py`
- Delete: `pico/lcd_smoke_test.py`
- Delete: `pico/pin_config.py`
- Delete: `tests/test_pico_lcd_ui.py`
- Delete: `tests/test_pico_pin_config.py`
- Delete: `tools/pico/vendor/adafruit_ili9341.py`
- Delete: `tools/pico/vendor/adafruit_display_text/`
- Delete: `tools/pico/vendor/adafruit_bus_device/`
- Modify: `pico/code.py`
- Modify: `pico/serial_bridge.py`
- Modify: `pico_reference/main.py`
- Modify: `tools/pico/deploy_to_pico.py`
- Modify: `tests/test_pico_code.py`
- Modify: `tests/test_pico_serial_bridge.py`
- Modify: `tests/test_pico_deploy_to_pico.py`
- Modify: `README.md`
- Modify: `REPO_STRUCTURE.md`
- Modify: `documentation_reference.md`
- Modify: `ENGINEERING_SPEC.md`
- Modify: `diagram.md`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`
- Modify: `lcd_screen_ui/README.md`
- Keep historical context only: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`

### Task 1: Remove LCD and Button Behavior From The Active Runtime

**Files:**
- Modify: `tests/test_pico_code.py`
- Modify: `pico/code.py`
- Test: `tests/test_pico_code.py`

- [ ] **Step 1: Write the failing runtime tests for the transport-only loop**

Replace the LCD/button-specific assertions in `tests/test_pico_code.py` with tests for the post-purge behavior.

Use cases to add:

```python
def test_main_runtime_no_longer_imports_lcd_or_button_modules(self):
    module = self._load_code_module()

    original_import = builtins.__import__
    imported = []

    def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
        imported.append(name)
        if name in {"keypad", "pico.lcd_ui", "lcd_ui", "pico.pin_config", "pin_config"}:
            raise AssertionError(f"unexpected import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    with mock.patch("builtins.__import__", side_effect=tracking_import):
        with self.assertRaises(SystemExit):
            module._main(lambda step: None)
```


def test_run_main_loop_iteration_skips_button_and_lcd_steps(self):
    module = self._load_code_module()
    call_log = []
    serial_bridge = _FakeSerialBridge(call_log)
    jetson_transport = _FakeJetsonTransport(call_log)
    sleeps = []

    module._send_button_debug = lambda message: call_log.append(("debug", message))
    module._sync_response_state = lambda protocol_handler_arg, transport_arg: call_log.append(("sync", None))
    module._drain_hid_reports = (
        lambda custom_hid_arg, protocol_handler_arg, raw_report_id: call_log.append(("hid", raw_report_id))
    )

    last_debug_heartbeat = module._run_main_loop_iteration(
        now=5.0,
        last_debug_heartbeat=0.0,
        serial_bridge=serial_bridge,
        jetson_transport=jetson_transport,
        protocol_handler=object(),
        custom_hid=object(),
        raw_report_id=9,
        time_sleep=sleeps.append,
    )

    self.assertEqual(last_debug_heartbeat, 5.0)
    self.assertEqual(
        call_log,
        [
            ("debug", "heartbeat"),
            ("serial", module.CDC_RELAY_SLICE_BYTES),
            ("transport", module.CDC_RELAY_SLICE_BYTES),
            ("sync", None),
            ("hid", 9),
        ],
    )
    self.assertEqual(sleeps, [module.BUTTON_POLL_SLEEP_S])


def test_runtime_module_no_longer_exports_lcd_flags(self):
    module = self._load_code_module()

    self.assertFalse(hasattr(module, "LCD_DEBUG_CHECKPOINT"))
    self.assertFalse(hasattr(module, "LCD_SKIP_PALETTE_WRITE"))
    self.assertFalse(hasattr(module, "LCD_SKIP_HIGHLIGHT_UPDATE"))
    self.assertFalse(hasattr(module, "LCD_SKIP_HIGHLIGHT_CLEAR"))
```

- [ ] **Step 2: Run the runtime tests to verify RED**

Run: `python -m pytest tests/test_pico_code.py -q`

Expected: FAIL because `pico/code.py` still requires button/LCD arguments and still exports LCD constants.

- [ ] **Step 3: Write the minimal runtime implementation**

Update `pico/code.py` to remove LCD/button behavior from the active loop.

Implementation targets:

```python
def _run_main_loop_iteration(
    *,
    now,
    last_debug_heartbeat,
    serial_bridge,
    jetson_transport,
    protocol_handler,
    custom_hid,
    raw_report_id,
    time_sleep,
):
    global _last_loop_checkpoint

    if (now - last_debug_heartbeat) >= CDC_DEBUG_HEARTBEAT_S:
        _send_button_debug("heartbeat")
        last_debug_heartbeat = now
        _last_loop_checkpoint = "after_heartbeat"

    serial_bridge.relay_once(max_chunk_size=CDC_RELAY_SLICE_BYTES)
    _last_loop_checkpoint = "after_serial_bridge"
    jetson_transport.poll(max_chunk_size=CDC_RELAY_SLICE_BYTES)
    _last_loop_checkpoint = "after_transport_poll"
    _sync_response_state(protocol_handler, jetson_transport)
    _last_loop_checkpoint = "after_response_sync"
    _drain_hid_reports(custom_hid, protocol_handler, raw_report_id)
    _last_loop_checkpoint = "after_hid_drain"
    time_sleep(BUTTON_POLL_SLEEP_S)
    _last_loop_checkpoint = "after_sleep"
    return last_debug_heartbeat
```

Also remove:

- LCD imports and `initialize_lcd_ui(...)`
- `keypad` import and button setup
- `_drain_button_events(...)`
- dead LCD/button debug constants
- any `_main(...)` path that still imports `lcd_ui`, `pin_config`, or `keypad`

- [ ] **Step 4: Run the runtime tests to verify GREEN**

Run: `python -m pytest tests/test_pico_code.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the runtime purge slice**

```bash
git add tests/test_pico_code.py pico/code.py
git commit -m "refactor: remove pico lcd runtime path"
```

### Task 2: Remove Button Injection Helpers And Dead Pico Files

**Files:**
- Modify: `tests/test_pico_serial_bridge.py`
- Modify: `pico/serial_bridge.py`
- Modify: `pico_reference/main.py`
- Delete: `pico/lcd_ui.py`
- Delete: `pico/lcd_smoke_test.py`
- Delete: `pico/pin_config.py`
- Delete: `tests/test_pico_lcd_ui.py`
- Delete: `tests/test_pico_pin_config.py`
- Test: `tests/test_pico_serial_bridge.py`

- [ ] **Step 1: Write the failing serial bridge tests for the post-button shape**

Trim `tests/test_pico_serial_bridge.py` so it asserts only the surviving relay behavior, plus one explicit absence check for the button helper.

Add:

```python
def test_serial_bridge_has_no_button_injection_helper(self):
    from pico.serial_bridge import SerialBridge

    bridge = SerialBridge(FakeCDC(), FakeUART())

    self.assertFalse(hasattr(bridge, "inject_button_press"))
```

Remove the old `build_button_press_packet` and `inject_button_press(...)` tests.

- [ ] **Step 2: Run the serial bridge tests to verify RED**

Run: `python -m pytest tests/test_pico_serial_bridge.py -q`

Expected: FAIL because `SerialBridge` still exposes `inject_button_press(...)`.

- [ ] **Step 3: Write the minimal helper cleanup**

Update `pico/serial_bridge.py` to the relay-only form:

```python
class SerialBridge:
    def __init__(self, cdc_data, uart):
        self._cdc_data = cdc_data
        self._uart = uart

    def relay_once(self, max_chunk_size=64):
        available = getattr(self._cdc_data, "in_waiting", 0)
        if available > 0:
            chunk = self._cdc_data.read(min(max_chunk_size, available))
            if chunk:
                self._uart.write(chunk)
                return len(chunk)
        return 0
```

Then delete:

- `pico/lcd_ui.py`
- `pico/lcd_smoke_test.py`
- `pico/pin_config.py`
- `tests/test_pico_lcd_ui.py`
- `tests/test_pico_pin_config.py`

Rewrite `pico_reference/main.py` so it documents only CDC-to-UART relay behavior and no button logic.

- [ ] **Step 4: Run the serial bridge tests to verify GREEN**

Run: `python -m pytest tests/test_pico_serial_bridge.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the helper/file cleanup slice**

```bash
git add tests/test_pico_serial_bridge.py pico/serial_bridge.py pico_reference/main.py
git add -u pico tests
git commit -m "refactor: remove pico button helper files"
```

### Task 3: Purge LCD Assets From The Deploy Bundle

**Files:**
- Modify: `tests/test_pico_deploy_to_pico.py`
- Modify: `tools/pico/deploy_to_pico.py`
- Delete: `tools/pico/vendor/adafruit_ili9341.py`
- Delete: `tools/pico/vendor/adafruit_display_text/`
- Delete: `tools/pico/vendor/adafruit_bus_device/`
- Test: `tests/test_pico_deploy_to_pico.py`

- [ ] **Step 1: Write the failing deploy tests for the transport-only manifest**

In `tests/test_pico_deploy_to_pico.py`, replace LCD-inclusive expectations with transport-only expectations.

Add or rewrite tests like:

```python
def test_firmware_bundle_excludes_removed_lcd_modules(self):
    self.assertNotIn("lcd_ui.py", deploy_to_pico.FIRMWARE_FILES)
    self.assertNotIn("pin_config.py", deploy_to_pico.FIRMWARE_FILES)


def test_runtime_library_paths_exclude_removed_lcd_support(self):
    self.assertNotIn("adafruit_bus_device", deploy_to_pico.RUNTIME_LIBRARY_PATHS)
    self.assertNotIn("adafruit_display_text", deploy_to_pico.RUNTIME_LIBRARY_PATHS)
    self.assertNotIn("adafruit_ili9341.py", deploy_to_pico.RUNTIME_LIBRARY_PATHS)


def test_default_desired_target_paths_exclude_removed_lcd_libraries(self):
    root = self._workspace_tempdir("desired-target-paths")
    repo_root = root / "repo"
    self._populate_firmware_repo(repo_root)
    self._populate_runtime_library_repo(repo_root)

    source_plan = deploy_to_pico.build_source_plan(repo=repo_root)
    desired = deploy_to_pico.default_desired_target_paths_from_source_plan(source_plan)

    self.assertNotIn("lcd_ui.py", desired)
    self.assertNotIn("pin_config.py", desired)
    self.assertNotIn("lib/adafruit_bus_device/__init__.py", desired)
    self.assertNotIn("lib/adafruit_display_text/__init__.py", desired)
    self.assertNotIn("lib/adafruit_ili9341.py", desired)
```

Add explicit exact-sync cleanup coverage that seeds a fake target with stale LCD files and stale LCD libraries and verifies the delete plan removes them.

Also rewrite the current LCD-specific library tests so they prove the opposite behavior now:

- `extract_required_libraries_from_bundle(...)` only yields `adafruit_hid`
- `ensure_runtime_libraries(...)` only caches and copies `adafruit_hid`
- no test still expects cached or copied LCD support files

- [ ] **Step 2: Run the deploy tests to verify RED**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -q`

Expected: FAIL because the deploy manifest and runtime libraries still include LCD assets.

- [ ] **Step 3: Write the minimal deploy implementation**

Update `tools/pico/deploy_to_pico.py` so the defaults ship only the transport runtime.

Expected edits:

```python
FIRMWARE_FILES = (
    "boot.py",
    "jetson_transport.py",
    "pico_debug.py",
    "protocol.py",
    "runtime_runner.py",
    "upload_protocol.py",
    "serial_bridge.py",
    "usb_config.py",
    "code.py",
)

RUNTIME_LIBRARY_PATHS = (
    "adafruit_hid",
)
```

Then delete the LCD-only vendor cache paths under `tools/pico/vendor/`.

- [ ] **Step 4: Run the deploy tests to verify GREEN**

Run: `python -m pytest tests/test_pico_deploy_to_pico.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the deploy cleanup slice**

```bash
git add tests/test_pico_deploy_to_pico.py tools/pico/deploy_to_pico.py tools/pico/vendor
git commit -m "refactor: drop pico lcd deploy assets"
```

### Task 4: Update Active Docs To Match The Purged Runtime

**Files:**
- Modify: `README.md`
- Modify: `REPO_STRUCTURE.md`
- Modify: `documentation_reference.md`
- Modify: `ENGINEERING_SPEC.md`
- Modify: `diagram.md`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`
- Modify: `lcd_screen_ui/README.md`
- Test: repository grep-based verification

- [ ] **Step 1: Write the failing documentation verification checks**

Before editing docs, establish a reproducible RED search that proves active docs still describe the old runtime.

Run:

```bash
rg "lcd_ui.py|lcd_smoke_test.py|pin_config.py|button scan|BUTTON_PRESS|keep the LCD idle screen active|button-feedback|physical button" README.md REPO_STRUCTURE.md documentation_reference.md ENGINEERING_SPEC.md diagram.md docs/pico lcd_screen_ui/README.md pico_reference/main.py
```

Expected: matches are returned from active docs/reference files, proving the RED state.

- [ ] **Step 2: Rewrite the docs to the transport-only story**

Required doc changes:

- `README.md`: remove the note that `lcd_smoke_test.py` is part of the current Pico story
- `REPO_STRUCTURE.md`: remove LCD/runtime-button ownership from the Pico layer description
- `documentation_reference.md`: keep Pico edits focused on transport/deploy/USB, not LCD UI
- `ENGINEERING_SPEC.md`: remove button scan / button injection from sections 4.1-4.5 and fix any stale pin table
- `diagram.md`: change `code.py` label from `CDC relay + button scan + HID handler` to transport-only wording
- `docs/pico/README.md`: remove LCD/button runtime behavior and smoke-test instructions from the active quickstart
- `docs/pico/HARDWARE_SMOKE_TEST.md`: convert to a transport-focused Pico verification checklist or remove LCD-specific verification language
- `lcd_screen_ui/README.md`: remove the reference to `pico/lcd_smoke_test.py`

Do not rewrite the historical investigation note unless a stale sentence there incorrectly claims current behavior.

- [ ] **Step 3: Verify the docs no longer describe current Pico LCD behavior**

Run targeted searches:

```bash
rg "lcd_ui.py|lcd_smoke_test.py|pin_config.py|button scan|BUTTON_PRESS|keep the LCD idle screen active|button-feedback|physical button" README.md REPO_STRUCTURE.md documentation_reference.md ENGINEERING_SPEC.md diagram.md docs/pico lcd_screen_ui/README.md pico_reference/main.py
```

Expected: no matches in active docs/reference files. Historical investigation notes are out of scope for this grep.

- [ ] **Step 4: Run the focused Pico test suite again**

Run: `python -m pytest tests/test_pico_code.py tests/test_pico_deploy_to_pico.py tests/test_pico_serial_bridge.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the doc cleanup slice**

```bash
git add README.md REPO_STRUCTURE.md documentation_reference.md ENGINEERING_SPEC.md diagram.md docs/pico lcd_screen_ui/README.md pico_reference/main.py
git commit -m "docs: remove pico lcd runtime references"
```

### Task 5: Final Verification

**Files:**
- Verify all changes above

- [ ] **Step 1: Run the full changed-area test suite**

Run:

```bash
python -m pytest tests/test_pico_code.py tests/test_pico_deploy_to_pico.py tests/test_pico_serial_bridge.py tests/test_protocol_packets.py tests/test_context_stream_e2e.py -q
```

Expected: PASS with no LCD-specific failures and no button-protocol regressions in the shared parser tests.

- [ ] **Step 2: Verify the worktree no longer contains shipped Pico LCD files**

Run:

```bash
git ls-files pico tools/pico/vendor tests | rg "lcd_ui|lcd_smoke_test|pin_config|adafruit_ili9341|adafruit_display_text|adafruit_bus_device|test_pico_lcd_ui|test_pico_pin_config"
```

Expected: no matches for the purged Pico LCD assets.

- [ ] **Step 3: Verify there are no active Pico LCD imports left**

Run:

```bash
rg "pico\.lcd_ui|from lcd_ui|import lcd_ui|pico\.pin_config|from pin_config import" pico tools/pico tests README.md REPO_STRUCTURE.md documentation_reference.md ENGINEERING_SPEC.md diagram.md docs/pico lcd_screen_ui/README.md
```

Expected: no active runtime/deploy/test/doc references remain.

- [ ] **Step 4: Verify no Pico helper still produces button-side effects**

Run:

```bash
rg "inject_button_press|build_button_press\(|_build_button_press|BUTTON_PIN_NUMBERS|keypad\.Keys" pico pico_reference tests/test_pico_code.py tests/test_pico_serial_bridge.py
```

Expected: no matches in the active Pico runtime/helper/test surface. Shared protocol parser coverage outside the active Pico runtime may still mention `BUTTON_PRESS`.

- [ ] **Step 5: Hardware acceptance check**

Deploy the runtime and confirm on a real board:

```bash
python tools/pico/deploy_to_pico.py
```

Acceptance:

- stale LCD files are removed from `CIRCUITPY`
- PB1-PB4 do nothing
- pressing PB1-PB4 produces no observable UART/CDC/button-side effect in the deployed runtime
- Raw HID ping/upload path still works
- summarize transport still works

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "refactor: purge pico lcd and button runtime"
```
