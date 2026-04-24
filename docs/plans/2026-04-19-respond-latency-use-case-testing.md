# RESPOND Latency Use-Case Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live hardware harness under `use-case testing/` that measures TTFT and completion time for feature 4 RESPOND using 20-word snippets, plus validation tests and a reusable 100-snippet dataset.

**Architecture:** Keep the live benchmark separate from unit tests. The harness will open the Pico CDC serial link directly, send a `CONTEXT_NEW` packet with the chosen snippet, then send a framed `respond_selection` request and measure from request write to first streamed response text and `SUMMARIZE_DONE`. Unit tests will only cover deterministic helpers such as snippet validation, packet timing aggregation, and result shaping.

**Tech Stack:** Python, pytest, pyserial, existing SPARK packet helpers in `core.protocol`, host helpers in `host_pc.summarize_stream`, and optional Pico port discovery from `host_pc.serial_sender`.

---

### Task 1: Plan File And Folder Layout

**Files:**
- Create: `docs/plans/2026-04-19-respond-latency-use-case-testing.md`
- Create: `use-case testing/README.md`
- Create: `use-case testing/feature4_respond_snippets.json`
- Create: `use-case testing/respond_latency_feature4.py`
- Test: `tests/test_use_case_respond_latency.py`

- [ ] **Step 1: Define the folder structure and responsibilities**
- [ ] **Step 2: Keep the live benchmark isolated from normal pytest runs**
- [ ] **Step 3: Document how to run one snippet or a batch**

### Task 2: Write Failing Tests First

**Files:**
- Test: `tests/test_use_case_respond_latency.py`
- Modify: `use-case testing/respond_latency_feature4.py`

- [ ] **Step 1: Write a failing test that rejects snippets that are not exactly 20 words**
- [ ] **Step 2: Run `pytest tests/test_use_case_respond_latency.py -v` and confirm failure**
- [ ] **Step 3: Write minimal helper code to load and validate snippets**
- [ ] **Step 4: Re-run `pytest tests/test_use_case_respond_latency.py -v` and confirm pass**

### Task 3: Timing Model Helpers

**Files:**
- Test: `tests/test_use_case_respond_latency.py`
- Modify: `use-case testing/respond_latency_feature4.py`

- [ ] **Step 1: Write a failing test for TTFT and completion timing derived from streamed packets**
- [ ] **Step 2: Run the targeted pytest test and confirm failure**
- [ ] **Step 3: Implement the minimal recorder/helper logic**
- [ ] **Step 4: Re-run the targeted pytest test and confirm pass**

### Task 4: Live RESPOND Benchmark Harness

**Files:**
- Modify: `use-case testing/respond_latency_feature4.py`
- Modify: `use-case testing/README.md`

- [ ] **Step 1: Implement serial open, direct context send, and framed RESPOND request send**
- [ ] **Step 2: Parse streamed `SUMMARIZE_CHUNK`, `SUMMARIZE_DONE`, and `ERROR` packets**
- [ ] **Step 3: Print one-result and multi-result summaries with TTFT, total latency, and output text**
- [ ] **Step 4: Document CLI usage and assumptions in the README**

### Task 5: Verification

**Files:**
- Test: `tests/test_use_case_respond_latency.py`
- Verify: `python -m pytest tests/test_use_case_respond_latency.py -v`

- [ ] **Step 1: Run the targeted pytest file and confirm all tests pass**
- [ ] **Step 2: Spot-check the JSON dataset count and word counts through the tests**
- [ ] **Step 3: Report the exact verification command and output status**
