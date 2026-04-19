# Communication-Focused Test Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink the automated test suite to the minimum set that directly protects message framing, transport behavior, DB handoff, return-path parsing, and the real `setup_spark.ps1` smoke loop.

**Architecture:** First trim and sharpen the small set of tests that remain so they assert only communication outcomes. Then delete low-value Python/UI/watcher/setup-detail tests in one sweep. Finish by verifying the reduced suite and the real setup/smoke flow still exercise the critical communication path.

**Tech Stack:** Python `unittest`/`pytest`, PowerShell Pester, existing host/Pico/Jetson protocol and setup scripts.

---

## File Map

- Modify: `tests/test_context_stream_e2e.py`
  Keep as the main composed Python communication test; trim to only host->wire->Jetson DB and DB-backed summarize communication behavior.
- Modify: `tests/test_pico_jetson_transport.py`
  Keep only request-forward, first-response, timeout, and error communication tests.
- Modify: `tests/test_jetson_protocol.py`
  Keep only malformed packet rejection that protects real inbound communication parsing.
- Modify: `tests/test_host_raw_hid_client.py`
  Keep this file or move its surviving assertions elsewhere, but the suite must still retain one successful return-path assertion and one error return-path assertion in a concrete surviving Python file.
- Modify: `tests/setup_spark.Tests.ps1`
  Keep only setup-critical behaviors that determine whether the smoke loop can start from a fresh state.
- Delete: `tests/test_tools/monitoring/watch_full_stack.py`
- Delete: `tests/test_spark_panel_ui.py`
- Delete: low-value Python/unit files identified during execution if they do not protect the four required communication outcomes.
- Verify: `setup_spark.ps1`
  Real acceptance path; do not convert this into a mocked unit surrogate.

## Task 1: Tighten the Anchor Integration Test

**Files:**
- Modify: `tests/test_context_stream_e2e.py`

- [ ] **Step 1: Write a checklist of cases to keep vs delete**

Keep only cases that prove:
- host context/polling-style message reaches Jetson DB
- update reaches Jetson DB
- button event reaches Jetson DB
- summarize-from-DB path uses stored state

Decision rule from the spec:
- if context and polling share the same serialization and handling path in the current code, one representative host-to-Jetson DB case is sufficient
- if they diverge into materially different paths, keep one case for each distinct path

Delete cases that mostly duplicate lower-level framing details already covered elsewhere.

- [ ] **Step 2: Remove one non-essential test case first**

Delete one clearly redundant case and run the file to verify the remaining suite still passes.

- [ ] **Step 3: Run the file to verify no accidental coverage break**

Run: `python -m pytest tests/test_context_stream_e2e.py -v`
Expected: PASS after each trim step.

- [ ] **Step 4: Finish trimming to the minimal anchor set**

Result must still include:
- one host-to-Jetson DB assertion for each materially distinct host message path
- one PB1/button-to-Jetson DB assertion
- one DB-backed summarize assertion

- [ ] **Step 5: Run the file again**

Run: `python -m pytest tests/test_context_stream_e2e.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_context_stream_e2e.py
git commit -m "test: trim context stream integration coverage"
```

## Task 2: Reduce Pico/Jetson Transport Coverage to Real Communication Contracts

**Files:**
- Modify: `tests/test_pico_jetson_transport.py`

- [ ] **Step 1: Write the keep set at the top of the file as a temporary checklist comment while editing**

Required survivors:
- request forwarded
- first response chunk marks response started
- timeout path
- error packet path

Each surviving assertion must prove an observable communication outcome on transport state or durable response state. Do not keep tests whose only proof is that a debug hook or mock callback fired.

If a current surviving test is too indirect or too implementation-specific, rewrite it into a minimal behavior-level communication test before deleting neighboring cases.

Delete everything else in this file.

- [ ] **Step 2: Delete one obviously non-essential test and verify the file still passes**

Run: `python -m pytest tests/test_pico_jetson_transport.py -v`
Expected: PASS

- [ ] **Step 3: Continue deleting until only the required communication-contract tests remain**

Do not keep debug-hook-only or internal retry-detail tests unless removing them would leave one of the required outcomes unprotected.

- [ ] **Step 4: Run the trimmed file**

Run: `python -m pytest tests/test_pico_jetson_transport.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pico_jetson_transport.py
git commit -m "test: trim pico jetson transport coverage"
```

## Task 3: Keep Only Parsing-Rejection Coverage That Protects Communication

**Files:**
- Modify: `tests/test_jetson_protocol.py`

- [ ] **Step 1: Confirm the remaining parser tests map to real communication protection**

Valid survivors:
- malformed packet with bad CRC is rejected
- malformed packet with invalid version/payload is rejected

Minimum parser keep set:
- one bad-CRC rejection test
- one invalid-version rejection test

Do not keep additional parser-detail tests unless removing them would leave inbound communication rejection underprotected.

- [ ] **Step 2: Remove any parser tests that are not directly guarding inbound communication rejection**

If the file already matches the minimal set, leave behavior unchanged and only simplify names/comments if needed.

- [ ] **Step 3: Run the file**

Run: `python -m pytest tests/test_jetson_protocol.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_jetson_protocol.py
git commit -m "test: keep minimal jetson parser rejection coverage"
```

## Task 4: Decide and Trim the Return-Path Test

**Files:**
- Modify: `tests/test_host_raw_hid_client.py`

- [ ] **Step 1: Identify the minimum two required return-path assertions**

The surviving Python return-path coverage must include both:
- one successful response-path assertion
- one error-path assertion

These assertions must exist in a concrete surviving file before any delete sweep. The default target is `tests/test_host_raw_hid_client.py`; only move them if the replacement location is created and passing first.

- [ ] **Step 2: Delete every test in `tests/test_host_raw_hid_client.py` that does not directly protect one of those two outcomes**

If the file cannot be reduced cleanly, create a much smaller replacement in the same file and delete the rest.

- [ ] **Step 3: Run the file**

Run: `python -m pytest tests/test_host_raw_hid_client.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_host_raw_hid_client.py
git commit -m "test: trim host return-path coverage"
```

## Task 5: Trim PowerShell Tests to Setup-Critical Behavior Only

**Files:**
- Modify: `tests/setup_spark.Tests.ps1`

- [ ] **Step 1: Mark the only allowed surviving PowerShell coverage**

Keep only tests for:
- deploy target selection
- fresh app relaunch behavior
- smoke recovery behavior
- mount/path behavior only where setup cannot proceed without it

Delete:
- source-text inspection tests
- heavily mocked tests that do not affect whether smoke can start from a fresh state
- any test that duplicates the real smoke run rather than protecting setup prerequisites

- [ ] **Step 2: Delete one source-text or implementation-detail test first**

Run: `Invoke-Pester -Path "tests\setup_spark.Tests.ps1"`
Expected: PASS

- [ ] **Step 3: Continue trimming until only setup-critical behavior remains**

Important: keep the new visible-app-launch coverage and headless opt-out coverage.

- [ ] **Step 4: Run the PowerShell test file again**

Run: `Invoke-Pester -Path "tests\setup_spark.Tests.ps1"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/setup_spark.Tests.ps1
git commit -m "test: trim setup spark tests to startup-critical behavior"
```

## Task 6: Delete Low-Value Python Test Files in One Sweep

**Files:**
- Delete: `tests/test_tools/monitoring/watch_full_stack.py`
- Delete: `tests/test_spark_panel_ui.py`
- Delete: every additional Python test file outside the named keep set unless it is the concrete surviving return-path file

- [ ] **Step 1: Delete the watcher-specific test file**

Delete: `tests/test_tools/monitoring/watch_full_stack.py`

- [ ] **Step 2: Delete the Spark UI test file**

Delete: `tests/test_spark_panel_ui.py`

- [ ] **Step 3: Search for remaining low-value Python tests and remove them if they do not map to the four required outcomes**

Decision rule:
- if removing the file leaves one of the four outcomes unprotected, rewrite that coverage into one of the named keep-set files or the concrete surviving return-path file first
- otherwise delete it

- [ ] **Step 4: Run the kept Python communication tests only**

Run exact commands for the surviving keep set, for example:

```bash
python -m pytest tests/test_context_stream_e2e.py tests/test_pico_jetson_transport.py tests/test_jetson_protocol.py tests/test_host_raw_hid_client.py -v
```

Adjust the list if the return-path file changes, but keep the command explicit.

Do not leave extra legacy Python test files in place just because they can be argued to weakly cover one outcome. Consolidate surviving coverage into the named keep-set files plus the concrete return-path file only.

- [ ] **Step 5: Commit**

```bash
git add tests
git commit -m "test: delete low-value non-communication tests"
```

## Task 7: Verify the Reduced Suite Against the Real Setup Path

**Files:**
- Verify: `tests/test_context_stream_e2e.py`
- Verify: `tests/test_pico_jetson_transport.py`
- Verify: `tests/test_jetson_protocol.py`
- Verify: the surviving return-path test file
- Verify: `tests/setup_spark.Tests.ps1`
- Verify: `setup_spark.ps1`

- [ ] **Step 1: Run the final kept Python communication suite**

Run the exact kept file list from Task 6 again.
Expected: PASS

- [ ] **Step 2: Run the kept PowerShell suite**

Run: `Invoke-Pester -Path "tests\setup_spark.Tests.ps1"`
Expected: PASS

- [ ] **Step 3: Run the real setup/smoke flow once**

Run: `powershell -ExecutionPolicy Bypass -File "setup_spark.ps1"`
Expected:
- fresh deploy/setup succeeds
- smoke summarize succeeds
- app relaunch behavior remains correct

- [ ] **Step 4: Confirm the remaining suite is materially smaller**

Checklist:
- `tests/test_tools/monitoring/watch_full_stack.py` is gone
- `tests/test_spark_panel_ui.py` is gone
- no watcher-specific Python test files remain
- only the named keep-set Python communication files plus the concrete return-path file remain for this area

- [ ] **Step 5: Commit**

```bash
git add tests setup_spark.ps1
git commit -m "test: verify reduced communication-focused suite"
```

## Final Verification

- [ ] Re-run the final kept Python communication suite
- [ ] Re-run `Invoke-Pester -Path "tests\setup_spark.Tests.ps1"`
- [ ] Re-run `powershell -ExecutionPolicy Bypass -File "setup_spark.ps1"`
- [ ] Confirm no watcher-specific Python suite remains
- [ ] Confirm every surviving automated test maps directly to one of the four required communication outcomes
