# Pytest Cleanup And Background Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Windows pytest runs from showing transient Qt windows and remove a small set of redundant low-signal UI tests.

**Architecture:** Add an early pytest bootstrap that forces Qt into offscreen mode before any PyQt6 imports, then rewrite the one DB viewer test that currently depends on `dialog.show()` so it still validates first-show auto-refresh semantics without a visible window. Keep the test cleanup conservative by removing only smoke-style assertions already covered by stronger behavior tests.

**Tech Stack:** Python 3, pytest, unittest, PyQt6

---

### Task 1: Add Early Pytest Qt Bootstrap

**Files:**
- Create: `tests/conftest.py`
- Test: `tests/test_spark_panel_ui.py`
- Test: `tests/test_jetson_db_viewer_ui.py`

- [ ] **Step 1: Write the failing test**

Add a top-level assertion near the PyQt import guard in `tests/test_jetson_db_viewer_ui.py` that requires `os.environ["QT_QPA_PLATFORM"] == "offscreen"` before any `QApplication` creation.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jetson_db_viewer_ui.py -q`
Expected: FAIL during collection because the offscreen bootstrap is not set yet.

- [ ] **Step 3: Write minimal implementation**

Create `tests/conftest.py` that sets `QT_QPA_PLATFORM=offscreen` with `os.environ.setdefault(...)` before test modules import PyQt6.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jetson_db_viewer_ui.py tests/test_spark_panel_ui.py -q`
Expected: PASS with the same functional outcomes, now using offscreen Qt.

### Task 2: Preserve DB Viewer First-Show Auto-Refresh Without Visible Windows

**Files:**
- Modify: `tests/test_jetson_db_viewer_ui.py`
- Test: `tests/test_jetson_db_viewer_ui.py`

- [ ] **Step 1: Write the failing test**

Replace the visible-window test with one that exercises `showEvent`/first-show semantics directly and asserts auto-refresh happens once.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_showing_dialog_auto_refreshes_once -q`
Expected: FAIL until the rewritten test is renamed and matches the real non-visible trigger path.

- [ ] **Step 3: Write minimal implementation**

Update the test to patch `QTimer.singleShot`, call `showEvent` with a real `QShowEvent`, invoke the queued callback without calling `dialog.show()`, and assert a second `showEvent` does not queue another refresh.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jetson_db_viewer_ui.py::JetsonDbViewerUiTests::test_show_event_auto_refreshes_only_once_without_showing_window -q`
Expected: PASS

### Task 3: Prune Low-Signal UI Smoke Coverage

**Files:**
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `tests/test_jetson_db_viewer_ui.py`
- Test: `tests/test_spark_panel_ui.py`
- Test: `tests/test_jetson_db_viewer_ui.py`

- [ ] **Step 1: Write the failing test**

Identify the assertions/tests to remove only when a stronger behavior test already proves the same contract.

- [ ] **Step 2: Run test to verify current coverage baseline**

Run: `pytest tests/test_spark_panel_ui.py tests/test_jetson_db_viewer_ui.py -q`
Expected: PASS before pruning.

- [ ] **Step 3: Write minimal implementation**

Delete only these low-value smoke-style tests when their contract is already covered by surviving behavior tests:

- `tests/test_spark_panel_ui.py::test_release_output_uses_fixed_height_scrollable_text_widget`
- `tests/test_spark_panel_ui.py::test_reformat_button_is_visible`
- the window-width assertion from `tests/test_spark_panel_ui.py::test_action_grid_hides_legacy_buttons_without_resizing_panel`
- the title/size/status-label cosmetic assertions from `tests/test_jetson_db_viewer_ui.py::test_viewer_dialog_has_expected_defaults`

Keep the state assertions in `test_viewer_dialog_has_expected_defaults` that verify refresh tokens, empty table state, and refresh flags.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_spark_panel_ui.py tests/test_jetson_db_viewer_ui.py -q`
Expected: PASS with leaner coverage.

### Task 4: Verify Full Suite Behavior

**Files:**
- No code changes required

- [ ] **Step 1: Run focused verification**

Run: `pytest tests/test_spark_panel_ui.py tests/test_jetson_db_viewer_ui.py -q`
Expected: PASS

- [ ] **Step 2: Run full-suite verification**

Run: `pytest -q`
Expected: PASS. On Windows, observe that the run no longer shows transient Qt windows while the suite executes.
