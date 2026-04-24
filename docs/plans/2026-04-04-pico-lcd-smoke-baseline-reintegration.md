# Pico LCD Smoke Baseline Reintegration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the known-good standalone LCD demo from commit `766b8d8`, then identify the smallest reintegration step that destabilizes the Pico before redesigning the runtime LCD path.

**Architecture:** Start from the exact standalone smoke-test baseline instead of replaying the later failed LCD integration commits. Add shared modules and active-runtime subsystems one at a time, with a real-hardware gate after each rung, so the first failing boundary is measured instead of guessed.

**Tech Stack:** CircuitPython, `displayio`, ILI9341, Raw HID, `usb_cdc`, UART, Python `unittest`, `pytest`, manual `CIRCUITPY` deployment on Windows

---

## Context

- Commit `766b8d8` likely had a working standalone LCD demo in `pico/lcd_smoke_test.py`.
- The first real attempt to wire LCD control into the active Pico runtime was `a55b769`.
- Later hardware investigation showed the integrated runtime crashes on runtime LCD feedback even though the standalone smoke test worked: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`.
- Current branch `sida` no longer ships any LCD firmware files, and `tools/pico/deploy_to_pico.py` exact-syncs them away.

## Working Hypothesis

The standalone smoke test worked because it was a single-purpose LCD program. The crashes appeared only after later commits embedded LCD feedback into the full SPARK Pico runtime alongside `usb_cdc`, Raw HID, UART, and Jetson transport work.

This plan is designed to prove or disprove that hypothesis empirically.

## File Map

- `pico/lcd_smoke_test.py`
  - Recreate the exact `766b8d8` standalone baseline in an isolated worktree or branch.
- `pico/lcd_ui.py`
  - Reintroduce only after the exact smoke baseline is reproduced and stable.
- `pico/pin_config.py`
  - Reintroduce only after the exact smoke baseline is reproduced and stable.
- `pico/code.py`
  - Reintegrate LCD behavior incrementally, one subsystem boundary at a time.
- `tools/pico/deploy_to_pico.py`
  - Leave untouched until hardware validation proves the integrated LCD path is stable.
- `tests/test_pico_lcd_ui.py`
  - Recreate when `pico/lcd_ui.py` comes back.
- `tests/test_pico_code.py`
  - Extend only as each reintegration rung becomes intentional runtime behavior.
- `tests/test_pico_deploy_to_pico.py`
  - Update only after LCD assets are intentionally part of the shipped runtime again.
- `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`
  - Append new hardware findings after each meaningful reintegration rung.

## Guardrails

- Do not cherry-pick or merge `a55b769`, `a89a07e`, or `52fb53d` wholesale.
- Do not start with the current default `python tools/pico/deploy_to_pico.py` flow; it removes LCD files from `CIRCUITPY`.
- Do not change deploy manifests until a hardware-stable integrated LCD path exists.
- Stop at the first rung that destabilizes the board. Record the finding before changing anything else.
- Keep the current transport-only runtime on `sida` as the safety baseline until the LCD path is proven.

## Task 1: Reproduce the Exact `766b8d8` Standalone Demo

**Files:**
- Create: isolated worktree or branch for historical LCD recovery
- Create: `pico/lcd_smoke_test.py` from `766b8d8`
- Reference: `docs/BRANCH_HANDOFF_2026-03-29.md`

- [ ] **Step 1: Create an isolated worktree or branch for LCD recovery**

Run one of these:

```bash
git worktree add ..\SPARK-pico-lcd-recovery -b pico-lcd-recovery sida
```

or, if staying in the current worktree intentionally:

```bash
git checkout -b pico-lcd-recovery
```

- [ ] **Step 2: Materialize the exact smoke-test file from `766b8d8`**

Run in the recovery worktree:

```bash
git show 766b8d8:pico/lcd_smoke_test.py > pico/lcd_smoke_test.py
```

If PowerShell redirection causes encoding trouble, use:

```powershell
git show 766b8d8:pico/lcd_smoke_test.py | Set-Content -Encoding utf8 "pico/lcd_smoke_test.py"
```

Expected result: `pico/lcd_smoke_test.py` exactly matches the historical standalone demo.

- [ ] **Step 3: Gather the required CircuitPython LCD libraries without changing the current deploy tool**

Required on `CIRCUITPY/lib/` for the historical baseline:

```text
adafruit_ili9341.mpy or adafruit_ili9341.py
adafruit_display_text/
adafruit_bus_device/
```

`docs/BRANCH_HANDOFF_2026-03-29.md` documented the original baseline as `adafruit_ili9341.mpy`. Use the form that matches the installed CircuitPython bundle on the board, but keep the rest of the smoke baseline exact.

- [ ] **Step 4: Deploy the smoke test manually to the Pico**

Copy only the standalone demo as the active runtime:

```powershell
Copy-Item pico\lcd_smoke_test.py D:\code.py
```

Then copy the LCD libraries into `D:\lib\` if they are not already present.

- [ ] **Step 5: Physically reset the Pico before evaluating behavior**

Expected: the board boots into the standalone LCD demo, not the repo's normal transport runtime.

- [ ] **Step 6: Verify the standalone hardware baseline**

Pass criteria:

```text
- idle screen renders correctly
- PB1-PB4 map to the expected cells
- repeated presses do not wedge USB
- no unplug/replug is needed during normal button testing
```

- [ ] **Step 7: Record whether the exact historical baseline still works**

If it fails here, stop and document wiring, library-version, or environment drift before attempting reintegration.

- [ ] **Step 8: Commit the recovery baseline worktree state**

```bash
git add pico/lcd_smoke_test.py
git commit -m "test: restore pico lcd smoke baseline from 766b8d8"
```

## Task 2: Capture the Smallest Diff Between the Working Demo and First Integration

**Files:**
- Reference: `pico/code.py`
- Reference: `pico/lcd_smoke_test.py`
- Reference: `pico/lcd_ui.py` from `a55b769`
- Reference: `pico/pin_config.py` from `a55b769`
- Update: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`

- [ ] **Step 1: Diff `766b8d8` against `a55b769` only for LCD-owned paths**

Run:

```bash
git diff --unified=80 766b8d8 a55b769 -- pico/code.py pico/lcd_smoke_test.py pico/lcd_ui.py pico/pin_config.py
```

Expected: a focused list of LCD reintegration changes instead of a full-branch diff.

- [ ] **Step 2: Write down the exact new responsibilities added by `a55b769`**

Capture at least these transitions:

```text
- self-contained smoke test -> shared lcd_ui module
- fixed button pins in smoke file -> shared pin_config module
- standalone LCD loop -> LCD calls inside active runtime loop
- no integrated LCD path -> lcd_ui.handle_press()/tick() in code.py
```

- [ ] **Step 3: Append a short note to the investigation doc with the measured baseline result**

Include whether `766b8d8` still reproduces successfully on current hardware.

- [ ] **Step 4: Commit the updated investigation note**

```bash
git add docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md
git commit -m "docs: record pico lcd smoke baseline result"
```

## Task 3: Reintroduce Shared LCD Modules Without Touching the Active Runtime

**Files:**
- Create: `pico/lcd_ui.py`
- Create: `pico/pin_config.py`
- Modify: `pico/lcd_smoke_test.py`
- Create: `tests/test_pico_lcd_ui.py`

- [ ] **Step 1: Write the failing unit tests for a shared standalone LCD module**

Cover at minimum:

```text
- idle screen object construction
- button press activates the expected cell
- timeout clears the pressed state
- no integration-only runtime helpers are required
```

- [ ] **Step 2: Run the new LCD tests to verify RED**

Run:

```bash
python -m pytest tests/test_pico_lcd_ui.py -q
```

- [ ] **Step 3: Extract the smoke-test logic into `pico/lcd_ui.py` and `pico/pin_config.py`**

Constraint: preserve the visual behavior of the working standalone demo exactly.

- [ ] **Step 4: Update `pico/lcd_smoke_test.py` to use the shared module**

Constraint: do not modify `pico/code.py` yet.

- [ ] **Step 5: Run the LCD tests again to verify GREEN**

Run:

```bash
python -m pytest tests/test_pico_lcd_ui.py -q
```

- [ ] **Step 6: Redeploy only the standalone smoke path and rerun the same hardware check**

Expected: behavior matches the exact historical demo.

- [ ] **Step 7: Commit the shared standalone LCD module extraction**

```bash
git add pico/lcd_ui.py pico/pin_config.py pico/lcd_smoke_test.py tests/test_pico_lcd_ui.py
git commit -m "refactor: share pico lcd smoke test module"
```

## Task 4: Add Runtime Diagnostics Around the LCD Baseline, Still Outside the Full Runtime

**Files:**
- Modify: `pico/lcd_smoke_test.py`
- Modify: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`

- [ ] **Step 1: Add only minimal diagnostics needed to observe hangs**

Examples:

```text
- serial console print before and after button handling
- optional heartbeat print at a low rate
```

Constraint: do not add Raw HID, CDC bridge, or Jetson transport yet.

- [ ] **Step 2: Redeploy and verify the standalone LCD path still stays stable under repeated button presses**

- [ ] **Step 3: Document whether diagnostics alone change behavior**

If diagnostics destabilize the standalone demo, stop and investigate before touching `pico/code.py`.

## Task 5: Reintroduce the Active Runtime One Subsystem at a Time

**Files:**
- Modify: `pico/code.py`
- Modify: `tests/test_pico_code.py`
- Modify: `docs/PICO_LCD_RUNTIME_INVESTIGATION_2026-04-03.md`

- [ ] **Step 0: Manually deploy runtime LCD experiments instead of using the default exact-sync helper**

For every Task 5 hardware rung, copy the active runtime files manually to `CIRCUITPY`.

Minimum file set once LCD support is being tested inside `pico/code.py`:

```powershell
Copy-Item pico\code.py D:\code.py
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

If a rung does not need one of those files yet, it may be omitted intentionally, but do not run `python tools/pico/deploy_to_pico.py` during Tasks 1-6.

- [ ] **Step 0.1: Recopy LCD runtime libraries manually for any board that was exact-synced previously**

Ensure these remain present in `D:\lib\` while LCD runtime experiments are active:

```text
adafruit_ili9341.mpy or adafruit_ili9341.py
adafruit_display_text/
adafruit_bus_device/
```

- [ ] **Step 0.2: Physically reset the Pico after every `code.py` redeploy before judging behavior**

Reason: the investigation showed that the runtime may continue serving the old code until reset when autoreload is disabled.

- [ ] **Step 1: Add LCD initialization to `pico/code.py` with no button handling**

Expected runtime behavior:

```text
- idle screen appears
- no button press changes the UI yet
- transport runtime otherwise stays healthy
```

- [ ] **Step 2: Run unit tests for the runtime surface**

Run:

```bash
python -m pytest tests/test_pico_code.py -q
```

- [ ] **Step 3: Hardware-test the idle-screen-only runtime build**

Before testing, perform Step 0 and Step 0.2 for this rung.

Pass criteria:

```text
- board boots normally
- heartbeats or equivalent diagnostics remain healthy
- HID ping still works
- no crash occurs without pressing buttons
```

- [ ] **Step 4: Add button queue draining with logging only, no visual LCD mutation**

Expected runtime behavior:

```text
- button presses are observed in diagnostics
- no LCD visual feedback occurs yet
- no host-side side effects occur yet
```

- [ ] **Step 5: Hardware-test the button-logging-only runtime build**

Before testing, perform Step 0 and Step 0.2 for this rung.

If the board crashes here, the problem is broader than LCD drawing.

- [ ] **Step 6: Add visual feedback back into the runtime using the shared LCD API**

Constraint: this is the first point where runtime LCD mutation is allowed back into `pico/code.py`.

- [ ] **Step 7: Hardware-test this exact rung repeatedly**

Before testing, perform Step 0 and Step 0.2 for this rung.

If the board crashes here while the earlier rungs stayed stable, treat this as the confirmed LCD/runtime interaction boundary.

- [ ] **Step 8: Only after visual feedback is stable, add host and Jetson mixed-traffic pressure**

Before testing, perform Step 0 and Step 0.2 for this rung.

Exercise:

```text
- button presses during idle runtime
- HID ping during and after button presses
- CDC traffic while pressing buttons
- UART/Jetson summarize path while pressing buttons
```

- [ ] **Step 9: Commit only the highest stable rung**

Do not commit a knowingly unstable runtime rung except as a local throwaway checkpoint.

## Task 6: Redesign Only If the Reintegration Ladder Finds the Same Failure Boundary

**Files:**
- Modify: `pico/lcd_ui.py`
- Modify: `tests/test_pico_lcd_ui.py`
- Modify: `pico/code.py`

- [ ] **Step 1: If runtime visual feedback still causes the first failure, switch to the static-tree redesign**

Reference: `docs/specs/2026-04-04-pico-lcd-redesign-design.md`

- [ ] **Step 2: Write failing tests that lock down static-tree invariants**

At minimum assert:

```text
- no root_group append/remove after startup
- no runtime object replacement for pressed-state transitions
- same-cell re-press refreshes timeout without structural edits
```

- [ ] **Step 3: Implement the smallest renderer/state split that satisfies those tests**

- [ ] **Step 4: Re-run the same hardware ladder starting from the visual-feedback rung**

Expected: if the redesign is correct, the earlier failure rung becomes stable without requiring deploy-manifest changes first.

## Task 7: Reintroduce Deploy and Documentation Support Last

**Files:**
- Modify: `tools/pico/deploy_to_pico.py`
- Modify: `tests/test_pico_deploy_to_pico.py`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`
- Modify: `README.md`
- Modify: `REPO_STRUCTURE.md`

- [ ] **Step 1: Restore LCD files and libraries to the deploy manifest only after the runtime rung is hardware-stable**

- [ ] **Step 2: Add deploy tests for the restored LCD assets**

Run:

```bash
python -m pytest tests/test_pico_deploy_to_pico.py -q
```

- [ ] **Step 3: Update active docs to describe the now-supported LCD path accurately**

- [ ] **Step 4: Verify exact-sync behavior does not delete required LCD assets after they are intentionally reintroduced**

- [ ] **Step 5: Commit deploy and documentation changes**

```bash
git add tools/pico/deploy_to_pico.py tests/test_pico_deploy_to_pico.py docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md README.md REPO_STRUCTURE.md
git commit -m "feat: restore supported pico lcd deployment path"
```

## Stop Conditions

- Stop immediately if the exact `766b8d8` standalone demo no longer works.
- Stop immediately if a rung crashes the Pico for the first time; record the result before changing any other variable.
- Stop immediately if a deploy helper change is needed before a stable runtime LCD rung exists.

## Verification Checklist

- `python -m pytest tests/test_pico_lcd_ui.py -q`
- `python -m pytest tests/test_pico_code.py -q`
- `python -m pytest tests/test_pico_deploy_to_pico.py -q`
- exact `766b8d8` smoke test booted manually on hardware
- repeated PB1-PB4 presses tested on hardware after each runtime rung
- HID ping tested before and after each runtime rung that changes `pico/code.py`
- CDC or Jetson traffic tested only after the visual-feedback rung is stable

## Expected Outcome

By following this plan, the team should learn one of three concrete things instead of repeating broad failed merges:

1. the original `766b8d8` demo no longer reproduces, so the problem is environmental rather than architectural
2. the demo still works, but the first failure appears only when active-runtime subsystems are added around it
3. even a carefully staged runtime reintegration fails at the visual-feedback boundary, which justifies moving to the static-tree LCD redesign before touching deploy support
