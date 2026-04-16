# Pytest Cleanup And Background Execution Design

## Context

The current repo has a broad Python test suite under `tests/`. On Windows, running the full suite causes distracting small windows to appear and disappear during execution. Investigation points to Qt UI tests using a real GUI backend, especially `tests/test_jetson_db_viewer_ui.py`, which currently calls `dialog.show()` in one test.

The suite also contains a layer of low-signal UI smoke coverage that asserts static construction details such as fixed labels, widths, and simple button presence. Those tests add maintenance cost without protecting much behavior.

## Goals

- Stop full-suite pytest runs from showing transient UI windows on Windows.
- Remove redundant or low-value pytest coverage without weakening behavior-focused regression protection.
- Keep the cleanup minimal and scoped to the tests that are actually causing noise or low signal.

## Non-Goals

- No changes to `setup_spark.ps1` for this task.
- No broad removal of behavior-heavy tests.
- No rewrite of the UI architecture or test framework.

## Chosen Approach

Use an offscreen Qt configuration for test runs, replace the visible-dialog auto-refresh test path with a non-visible trigger, and prune only the clearest low-value UI smoke tests.

## Design

### 1. Run Qt tests offscreen during pytest

Add a pytest-time environment guard so Qt uses an offscreen platform plugin during test runs. This keeps `QApplication`-based tests from opening real Windows GUI surfaces while preserving the same code paths for widget construction and signal handling.

The setting must be applied in early pytest bootstrap before any PyQt6 import or `QApplication` creation. It must remain test-only and must not change normal app runtime behavior.

### 2. Remove the visible-window dependency from the DB viewer test

`tests/test_jetson_db_viewer_ui.py` currently relies on `dialog.show()` to trigger `showEvent()` and the single-shot auto-refresh path. Replace that with a non-visible trigger strategy so the test still validates the real one-time auto-refresh-on-first-show contract without opening a real window.

The replacement must preserve `showEvent`/first-show semantics and verify the auto-refresh path only triggers once. It must not devolve into only calling `_on_refresh_clicked()` directly.

### 3. Prune low-signal UI smoke tests

Remove tests that mostly restate static construction details already covered indirectly by stronger behavior tests. Only assertions already protected by stronger behavior tests may be removed. Priority targets are assertions like:

- exact default window dimensions when not tied to behavior
- static label text that does not drive logic
- simple presence or visibility checks for controls when feature-flow tests already depend on those controls

Keep tests that validate:

- refresh and table-loading flows
- request lifecycle and in-flight guards
- error handling
- feature-trigger behavior
- state transitions that affect user-visible outcomes

## Expected File Changes

- Add a pytest test bootstrap file for test-only environment setup.
- Update `tests/test_jetson_db_viewer_ui.py` to avoid visible `show()`-driven execution.
- Trim low-value assertions or tests from `tests/test_spark_panel_ui.py` and, if justified after review, `tests/test_jetson_db_viewer_ui.py`.

## Verification

- Run the affected UI-focused pytest targets.
- Run at least one Windows full-suite pytest pass that exercises the offscreen Qt setup.
- Confirm the suite executes without transient Windows UI popups.
- Confirm the rewritten DB viewer auto-refresh test still passes without any visible-window dependency and still checks one-time first-show behavior.
- Confirm remaining UI tests still cover refresh, dialog invocation, and feature request behavior.

## Risks

- Offscreen Qt can behave slightly differently from an on-screen backend for a narrow set of UI timing cases.
- Over-pruning UI smoke tests could remove useful intent documentation if done too aggressively.

These risks are managed by keeping the cleanup conservative and preserving behavior-driven tests.
