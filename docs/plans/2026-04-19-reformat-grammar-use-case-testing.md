# REFORMAT Grammar Use-Case Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live Feature 2 REFORMAT benchmark that feeds 100 grammatically incorrect sentences through the existing Pico -> Jetson path, stores the returned text, and evaluates whether each response is grammatically correct without relying on a prewritten expected sentence.

**Architecture:** Reuse the existing live use-case benchmark pattern from `use-case testing/respond_latency_feature4.py`. The new benchmark will load a 100-item JSON dataset, send each incorrect sentence as both active context and `reformat_selection` input, capture the streamed Jetson response, persist per-case results, and evaluate grammar quality with `language_tool_python` plus lightweight normalization heuristics.

**Tech Stack:** Python, pytest, `language_tool_python`, existing SPARK serial protocol helpers.

---

### Task 1: Add dataset coverage

**Files:**
- Create: `tests/test_use_case_reformat_grammar.py`
- Create: `use-case testing/feature2_reformat_incorrect_sentences.json`

- [ ] **Step 1: Write the failing dataset test**

Verify the loader accepts exactly 100 string items and rejects invalid counts.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_use_case_reformat_grammar.py -k dataset -v`

- [ ] **Step 3: Add the 100 incorrect sentences**

Create an ASCII-only JSON array with 100 natural-language sentences that are intentionally grammatically incorrect.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_use_case_reformat_grammar.py -k dataset -v`

### Task 2: Add evaluator and live harness

**Files:**
- Create: `tests/test_use_case_reformat_grammar.py`
- Create: `use-case testing/reformat_grammar_feature2.py`

- [ ] **Step 1: Write failing evaluator and recorder tests**

Cover dataset validation, response recorder timing, grammar-evaluation result shape, and persisted-output naming helpers without touching live hardware.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_use_case_reformat_grammar.py -v`

- [ ] **Step 3: Write minimal implementation**

Implement the live harness with CLI options parallel to the existing RESPOND benchmark, plus result persistence and grammar evaluation.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_use_case_reformat_grammar.py -v`

### Task 3: Document the new benchmark

**Files:**
- Modify: `use-case testing/README.md`

- [ ] **Step 1: Add benchmark usage docs**

Document dataset purpose, live-run commands, output storage, and that grammar evaluation is heuristic rather than exact-match.

- [ ] **Step 2: Run targeted verification**

Run: `pytest tests/test_use_case_reformat_grammar.py tests/test_use_case_respond_latency.py -v`
