# Release Output Markdown And Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Priority rule:** Tasks tagged `[USER-REQ]` implement non-negotiable user requirements. Tasks tagged `[AGENT-DECISION]` implement flexible agent design decisions. If a conflict arises during implementation, agent decisions yield to user requirements. If a user requirement cannot be met, stop and surface to the user.

**Goal:** Render release output Markdown while providing a low-lag plain-text copy path.

**Architecture:** Keep `QTextEdit` as the release output display, but stop writing to it directly from feature handlers. Route updates through a helper that stores raw output text and renders Markdown with `setMarkdown(...)`. Add a left-column Copy Output action that copies the stored raw text with `QApplication.clipboard().setText(...)`.

**Tech Stack:** PyQt6, Python `unittest`/`pytest`, existing `tests/test_spark_panel_ui.py` panel tests.

---

### Task 1: Release Output Copy Behavior [USER-REQ]

**Requirement:** Preserve reliable copy-paste behavior from release output.

**Files:**
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `spark_app_v2.py`

- [ ] **Step 1: Write the failing test**

Add a test that sets Markdown output, clicks or invokes the Copy handler, and asserts the clipboard receives the raw Markdown string.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_spark_panel_ui.py::SparkPanelUITests::test_copy_release_output_copies_raw_markdown_text -q`

Expected: FAIL because the Copy handler/control does not exist yet.

- [ ] **Step 3: Implement minimal code**

Add `_release_output_plain_text`, `_set_release_output(...)`, `_copy_release_output()`, and a Copy Output action in the left-side suggested actions grid.

- [ ] **Step 4: Run test to verify it passes**

Run the same targeted test and expect PASS.

### Task 1.5: Left-Side Copy Placement [USER-REQ]

**Requirement:** Place the Copy button on the left side of the panel with the existing suggested-action buttons.

**Files:**
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `spark_app_v2.py`

- [ ] **Step 1: Write the failing test**

Update the visible suggested-action button test to expect `Copy Output` alongside the existing visible actions.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_spark_panel_ui.py::SparkPanelUiTests::test_action_grid_hides_legacy_buttons_without_resizing_panel -q`

Expected: FAIL because Copy Output still lives in the release-output header.

- [ ] **Step 3: Implement minimal code**

Move the copy control from the release-output header into the left action grid as an `ActionButton`.

- [ ] **Step 4: Run test to verify it passes**

Run the same targeted test and expect PASS.

### Task 2: Markdown Rendering Path [USER-REQ]

**Requirement:** Render LLM Markdown output more properly in release output.

**Files:**
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `spark_app_v2.py`

- [ ] **Step 1: Write the failing test**

Add a test that patches `release_output_lbl.setMarkdown`, completes a feature request with Markdown, and asserts the raw Markdown is sent to the renderer while `toPlainText()` exposes readable text.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_spark_panel_ui.py::SparkPanelUITests::test_feature_completion_renders_markdown_output -q`

Expected: FAIL because the current code calls `setPlainText(...)`.

- [ ] **Step 3: Implement minimal code**

Replace direct release output `setPlainText(...)` calls with `_set_release_output(...)`.

- [ ] **Step 4: Run focused and related tests**

Run: `./.venv/bin/python -m pytest tests/test_spark_panel_ui.py tests/test_release_output.py -q`

Expected: PASS.

### Task 3: Final Verification [AGENT-DECISION]

**Requirement:** Keep the existing panel behavior stable while adding the new display/copy path.

**Files:**
- Verify: `spark_app_v2.py`
- Verify: `tests/test_spark_panel_ui.py`
- Verify: `tests/test_release_output.py`

- [ ] **Step 1: Compile-check the touched Python files**

Run: `./.venv/bin/python -m py_compile spark_app_v2.py host_pc/release_output.py tests/test_spark_panel_ui.py`

- [ ] **Step 2: Review the diff**

Run: `git diff -- spark_app_v2.py tests/test_spark_panel_ui.py docs/specs/2026-04-25-release-output-markdown-copy-design.md docs/plans/2026-04-25-release-output-markdown-copy.md`

- [ ] **Step 3: Restart note**

If the live app is running, relaunch it after the code change so the new widget behavior is active.
