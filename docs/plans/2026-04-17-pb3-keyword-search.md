# PB3 Keyword Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PB3 keyword search so selected text can query the 3 most recent matching Jetson DB entries and return a summarized result to the panel and clipboard.

**Architecture:** Reuse the existing host-to-Pico Raw HID feature request path with a new `FEATURE_3` JSON command. Keep DB searching and summary generation on Jetson so the host only supplies the selected keyword text while Pico continues to act as a relay.

**Tech Stack:** Python, PyQt6, unittest, SQLite, existing SPARK Raw HID/UART bridge

---

### Task 1: Request Builder

**Files:**
- Modify: `C:/SPARK/host_pc/summarize_stream.py`
- Test: `C:/SPARK/tests/test_summarize_stream.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run `pytest tests/test_summarize_stream.py -k keyword -v` and confirm failure**
- [ ] **Step 3: Add `build_keyword_search_request()` with trim/truncate behavior**
- [ ] **Step 4: Re-run the same pytest slice and confirm pass**

### Task 2: Host PB3 Panel Flow

**Files:**
- Modify: `C:/SPARK/spark_app_v2.py`
- Test: `C:/SPARK/tests/test_spark_panel_ui.py`

- [ ] **Step 1: Write the failing PB3 panel tests**
- [ ] **Step 2: Run the PB3 pytest slice and confirm failure**
- [ ] **Step 3: Add `_on_keyword_search()`, PB3 debug handling, feature-specific status text, and clipboard write-back**
- [ ] **Step 4: Re-run the PB3 pytest slice and confirm pass**

### Task 3: Jetson DB Search and Summary Path

**Files:**
- Modify: `C:/SPARK/jetson/db_manager.py`
- Modify: `C:/SPARK/jetson/pico_llm_bridge.py`
- Test: `C:/SPARK/tests/test_pico_llm_bridge.py`

- [ ] **Step 1: Write the failing Jetson tests for matched-entry prompt building and no-match behavior**
- [ ] **Step 2: Run `pytest tests/test_pico_llm_bridge.py -k keyword -v` and confirm failure**
- [ ] **Step 3: Add a DB helper for recent text matches and wire `keyword_search` into the bridge**
- [ ] **Step 4: Re-run the same pytest slice and confirm pass**

### Task 4: Pico FEATURE_3 Forwarding

**Files:**
- Modify: `C:/SPARK/pico/bridge_app.py`
- Test: `C:/SPARK/tests/test_pico_bridge_app.py`

- [ ] **Step 1: Write the failing FEATURE_3 forwarding test**
- [ ] **Step 2: Run `pytest tests/test_pico_bridge_app.py -k feature_3 -v` and confirm failure**
- [ ] **Step 3: Forward `FEATURE_3` through the Jetson transport path**
- [ ] **Step 4: Re-run the same pytest slice and confirm pass**

### Task 5: Verification and Deployment

**Files:**
- Deploy: `C:/SPARK/pico/*`

- [ ] **Step 1: Run targeted regression tests for summarize stream, panel UI, Pico bridge, and Jetson bridge**
- [ ] **Step 2: Run the full relevant pytest files**
- [ ] **Step 3: Deploy `pico/` changes with `python tools/pico/deploy_to_pico.py`**
- [ ] **Step 4: Restart `spark_app_v2.py` and verify the updated app process is running**
