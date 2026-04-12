# Full-Stack Log Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single local watcher that merges SPARK app, Pico-derived app logs, Jetson bridge logs, and Jetson LLM logs into one prefixed stream while reporting missing, quiet, and recovered component states.

**Architecture:** Add a stable rotating app log in `spark_app_v2.py`, then implement a passive watcher in `watch_full_stack.py` that tails local and mounted log files, runs SSH-backed Jetson process checks, and emits normalized `[APP]`, `[PICO]`, `[JETSON-BRIDGE]`, `[JETSON-LLM]`, and `[CHECK]` lines. Keep the watcher arrival-ordered, state-driven, and tolerant of disappearing sources.

**Tech Stack:** Python 3, standard library (`logging`, `logging.handlers`, `subprocess`, `threading`, `queue`, `pathlib`), existing repo logging conventions, pytest/unittest.

---

## File Map

- Modify: `spark_app_v2.py`
  Add a rotating file handler using the required formatter `%(asctime)s %(name)s %(levelname)s %(message)s` without removing terminal logging.
- Create: `watch_full_stack.py`
  Main watcher CLI, merged event sink, app-log tailing, Jetson log tailing, SSH health checks, state tracking, and quiet detection.
- Create: `tests/test_watch_full_stack.py`
  Unit tests for source mapping, state transitions, quiet gating, expectation allowlist behavior, and startup/file-tail semantics.
- Possibly reuse as reference only: `watch_pico_cdc_debug.py`
  Do not re-open Pico CDC in default mode; only borrow naming/style ideas if useful.
- Reference: `docs/superpowers/specs/2026-04-10-full-stack-log-watcher-design.md`

## Task 1: Add Stable App File Logging

**Files:**
- Modify: `spark_app_v2.py`
- Test: `tests/test_watch_full_stack.py`

- [ ] **Step 1: Write the failing test for app log setup**

```python
def test_configure_app_file_logging_adds_rotating_handler(tmp_path):
    import logging
    import spark_app_v2

    logger = logging.getLogger()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    log_path = tmp_path / "spark_app_v2.log"
    spark_app_v2.configure_app_logging(log_path=log_path)

    file_handlers = [h for h in logging.getLogger().handlers if getattr(h, "baseFilename", None)]
    assert any(str(log_path) == h.baseFilename for h in file_handlers)


def test_configure_app_file_logging_keeps_existing_stream_handler(tmp_path):
    import logging
    import spark_app_v2

    root = logging.getLogger()
    stream = logging.StreamHandler()
    root.addHandler(stream)

    spark_app_v2.configure_app_logging(log_path=tmp_path / "spark_app_v2.log")

    assert stream in logging.getLogger().handlers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_watch_full_stack.py::test_configure_app_file_logging_adds_rotating_handler -v`
Expected: FAIL because `configure_app_logging` does not exist yet.

- [ ] **Step 3: Write minimal implementation in `spark_app_v2.py`**

```python
from logging.handlers import RotatingFileHandler
from pathlib import Path

def configure_app_logging(*, log_path: Path | str | None = None):
    path = Path(log_path or Path("logs") / "spark_app_v2.log")
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    handler = RotatingFileHandler(path, maxBytes=512_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(formatter)
    if not any(getattr(h, "baseFilename", None) == str(path) for h in root.handlers):
        root.addHandler(handler)
```

- [ ] **Step 4: Call the logging setup once at startup**

Add a single startup call immediately after the existing `logging.basicConfig(...)` block so terminal logging remains intact and the file handler is attached before app runtime logs begin. Do not replace `basicConfig()` and do not add a second stream handler.

- [ ] **Step 5: Run focused test to verify it passes**

Run: `pytest tests/test_watch_full_stack.py::test_configure_app_file_logging_adds_rotating_handler -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add spark_app_v2.py tests/test_watch_full_stack.py
git commit -m "feat: add spark app file logging"
```

## Task 2: Build App Log Parsing and Source Mapping

**Files:**
- Create: `watch_full_stack.py`
- Test: `tests/test_watch_full_stack.py`

- [ ] **Step 1: Write failing tests for source mapping**

```python
def test_map_app_log_line_routes_pico_debug_to_pico():
    from watch_full_stack import map_app_log_line

    source, message = map_app_log_line("2026-04-10 12:44:40,604 pico.debug INFO [PICO] heartbeat")

    assert source == "PICO"
    assert message == "[PICO] heartbeat"


def test_map_app_log_line_defaults_to_app():
    from watch_full_stack import map_app_log_line

    source, message = map_app_log_line("2026-04-10 12:44:40,604 spark_app_v2 INFO app started")

    assert source == "APP"
    assert message == "app started"


def test_map_app_log_line_uses_required_file_format_contract():
    from watch_full_stack import map_app_log_line

    source, message = map_app_log_line("2026-04-10 12:44:40,604 host_pc.raw_hid INFO Opened SPARK Raw HID device")

    assert source == "APP"
    assert message == "Opened SPARK Raw HID device"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watch_full_stack.py::test_map_app_log_line_routes_pico_debug_to_pico tests/test_watch_full_stack.py::test_map_app_log_line_defaults_to_app -v`
Expected: FAIL because `watch_full_stack.py` does not exist yet.

- [ ] **Step 3: Write minimal parser implementation**

```python
def map_app_log_line(line: str) -> tuple[str, str]:
    parts = line.rstrip("\n").split(" ", 4)
    if len(parts) < 5:
        return "APP", line.rstrip("\n")
    timestamp_date, timestamp_time, logger_name, level, message = parts
    if logger_name == "pico.debug":
        return "PICO", message
    return "APP", message
```

Keep this parser tied to the exact file log formatter from Task 1: `%(asctime)s %(name)s %(levelname)s %(message)s`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_watch_full_stack.py::test_map_app_log_line_routes_pico_debug_to_pico tests/test_watch_full_stack.py::test_map_app_log_line_defaults_to_app -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add watch_full_stack.py tests/test_watch_full_stack.py
git commit -m "feat: add app log source mapping for watcher"
```

## Task 3: Implement File Tail Sources

**Files:**
- Create: `watch_full_stack.py`
- Test: `tests/test_watch_full_stack.py`

- [ ] **Step 1: Write failing tests for EOF startup and file recreation**

```python
def test_file_tail_source_starts_at_eof(tmp_path):
    from watch_full_stack import FileTailSource

    path = tmp_path / "bridge.log"
    path.write_text("old line\n", encoding="utf-8")
    source = FileTailSource(path, source_label="JETSON-BRIDGE")

    assert source.poll() == []


def test_file_tail_source_recovers_after_truncate(tmp_path):
    from watch_full_stack import FileTailSource

    path = tmp_path / "bridge.log"
    path.write_text("old\n", encoding="utf-8")
    source = FileTailSource(path, source_label="JETSON-BRIDGE")
    source.poll()

    path.write_text("new\n", encoding="utf-8")
    events = source.poll()

    assert [e.message for e in events] == ["new"]


def test_file_tail_source_recovers_after_recreate(tmp_path):
    from watch_full_stack import FileTailSource

    path = tmp_path / "bridge.log"
    path.write_text("old\n", encoding="utf-8")
    source = FileTailSource(path, source_label="JETSON-BRIDGE")
    source.poll()

    path.unlink()
    assert source.poll() == []

    path.write_text("recreated\n", encoding="utf-8")
    assert source.poll() == []
    path.write_text("recreated\nnext\n", encoding="utf-8")
    events = source.poll()

    assert [e.message for e in events] == ["next"]


def test_file_tail_source_recovers_after_rotate_replace(tmp_path):
    from watch_full_stack import FileTailSource

    path = tmp_path / "spark_app_v2.log"
    rotated = tmp_path / "spark_app_v2.log.1"
    path.write_text("old\n", encoding="utf-8")
    source = FileTailSource(path, source_label="APP")
    source.poll()

    path.replace(rotated)
    path.write_text("fresh\n", encoding="utf-8")
    assert source.poll() == []
    path.write_text("fresh\nnext\n", encoding="utf-8")
    events = source.poll()

    assert [e.message for e in events] == ["next"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watch_full_stack.py::test_file_tail_source_starts_at_eof tests/test_watch_full_stack.py::test_file_tail_source_recovers_after_truncate tests/test_watch_full_stack.py::test_file_tail_source_recovers_after_recreate tests/test_watch_full_stack.py::test_file_tail_source_recovers_after_rotate_replace -v`
Expected: FAIL

- [ ] **Step 3: Implement `FileTailSource`**

```python
class FileTailSource:
    def __init__(self, path, *, source_label, mapper=None):
        self.path = Path(path)
        self.source_label = source_label
        self.mapper = mapper or (lambda line: (source_label, line.rstrip("\n")))
        self._offset = None
        self._inode = None

    def poll(self):
        if not self.path.exists():
            self._offset = None
            self._inode = None
            return []
        stat = self.path.stat()
        if self._offset is None or stat.st_size < self._offset:
            self._offset = stat.st_size
            self._inode = (stat.st_mtime_ns, stat.st_size)
            return []
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self._offset)
            lines = handle.readlines()
            self._offset = handle.tell()
        return [make_log_event(*self.mapper(line)) for line in lines]
```

Acceptance criteria for `FileTailSource`:
- initial open seeks to EOF and emits no backlog
- truncation reopens cleanly and emits only new post-truncate lines
- delete/recreate reopens cleanly and treats the recreated file like a fresh startup source at EOF
- rotate/replace reopens cleanly when the active path now points at a different file identity even if file size did not shrink
- the same behavior applies to the rotating app log and the Jetson tailed logs

Implementation note: do not rely only on file size shrinkage. Track file identity using stable stat data available on the current platform, and treat identity change at the watched path as a reopen-at-EOF event.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest tests/test_watch_full_stack.py::test_file_tail_source_starts_at_eof tests/test_watch_full_stack.py::test_file_tail_source_recovers_after_truncate tests/test_watch_full_stack.py::test_file_tail_source_recovers_after_recreate tests/test_watch_full_stack.py::test_file_tail_source_recovers_after_rotate_replace -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add watch_full_stack.py tests/test_watch_full_stack.py
git commit -m "feat: add watcher file tail sources"
```

## Task 4: Implement Health State Tracking

**Files:**
- Create: `watch_full_stack.py`
- Test: `tests/test_watch_full_stack.py`

- [ ] **Step 1: Write failing tests for missing, recovered, quiet, and active-again transitions**

```python
def test_state_tracker_emits_missing_once_then_recovered():
    from watch_full_stack import StateTracker

    tracker = StateTracker()

    assert tracker.update_required_state("JETSON bridge process", present=False) == ["[CHECK] JETSON bridge process missing"]
    assert tracker.update_required_state("JETSON bridge process", present=False) == []
    assert tracker.update_required_state("JETSON bridge process", present=True) == ["[CHECK] JETSON bridge recovered"]


def test_quiet_only_applies_after_first_event():
    from watch_full_stack import StateTracker

    tracker = StateTracker(quiet_seconds=30)

    assert tracker.check_quiet("PICO", now=31.0) == []


def test_quiet_is_suppressed_while_source_is_missing():
    from watch_full_stack import StateTracker

    tracker = StateTracker(quiet_seconds=30)
    tracker.update_required_state("JETSON-BRIDGE", present=False)

    assert tracker.check_quiet("JETSON-BRIDGE", now=31.0) == []


def test_quiet_is_tracked_per_logical_source_label():
    from watch_full_stack import StateTracker

    tracker = StateTracker(quiet_seconds=30)
    tracker.record_activity("APP", now=0.0)

    assert tracker.check_quiet("PICO", now=31.0) == []
    assert tracker.check_quiet("APP", now=31.0) == ["[CHECK] APP quiet for 30s"]


def test_quiet_starts_only_after_source_reports_startup_catchup_complete():
    from watch_full_stack import StateTracker

    tracker = StateTracker(quiet_seconds=30)
    tracker.mark_source_seen("JETSON-BRIDGE", now=0.0, catchup_complete=False)

    assert tracker.check_quiet("JETSON-BRIDGE", now=31.0) == []

    tracker.mark_source_seen("JETSON-BRIDGE", now=0.0, catchup_complete=True)
    assert tracker.check_quiet("JETSON-BRIDGE", now=31.0) == ["[CHECK] JETSON-BRIDGE quiet for 30s"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watch_full_stack.py::test_state_tracker_emits_missing_once_then_recovered tests/test_watch_full_stack.py::test_quiet_only_applies_after_first_event -v`
Expected: FAIL

- [ ] **Step 3: Implement `StateTracker`**

```python
class StateTracker:
    def __init__(self, quiet_seconds=30.0):
        self.quiet_seconds = quiet_seconds
        self._required = {}
        self._last_activity = {}
        self._quiet = set()

    def record_activity(self, label, now):
        self._last_activity[label] = now
        if label in self._quiet:
            self._quiet.remove(label)
            return [f"[CHECK] {label} active again"]
        return []
```

Include explicit handling for:
- per-logical-source quiet state
- no quiet before first event
- SSH-unknown Jetson process state
- quiet eligibility starting only after a source reports startup catch-up complete
- quiet suppression while missing

Keep expectation suppression out of `StateTracker`. `StateTracker` should only manage state transitions for sources/components that the caller has already decided are required.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest tests/test_watch_full_stack.py::test_state_tracker_emits_missing_once_then_recovered tests/test_watch_full_stack.py::test_quiet_only_applies_after_first_event -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add watch_full_stack.py tests/test_watch_full_stack.py
git commit -m "feat: add watcher state tracking"
```

## Task 5: Implement Process and Path Health Checks

**Files:**
- Create: `watch_full_stack.py`
- Test: `tests/test_watch_full_stack.py`

- [ ] **Step 1: Write failing tests for check semantics**

```python
def test_component_allowlist_suppresses_missing_warning_for_non_required_component():
    from watch_full_stack import WatchConfig, evaluate_component_requirement

    config = WatchConfig(expected_components={"app", "jetson-bridge"})

    assert evaluate_component_requirement(config, "jetson-llm") is False


def test_default_expectation_mode_requires_all_major_components():
    from watch_full_stack import WatchConfig, expected_components_for_cli

    config = WatchConfig.from_cli(expect_app=False, expect_jetson_bridge=False, expect_jetson_llm=False)

    assert expected_components_for_cli(config) == {"app", "jetson-bridge", "jetson-llm"}


def test_any_expect_flag_switches_to_allowlist_mode():
    from watch_full_stack import WatchConfig, expected_components_for_cli

    config = WatchConfig.from_cli(expect_app=True, expect_jetson_bridge=False, expect_jetson_llm=False)

    assert expected_components_for_cli(config) == {"app"}


def test_parse_pgrep_output_counts_multiple_matches():
    from watch_full_stack import process_present_from_output

    present, count = process_present_from_output("123 python3 ...\n124 python3 ...\n")

    assert present is True
    assert count == 2


def test_ssh_failure_sets_jetson_process_state_unknown_and_suppresses_missing_transition():
    from watch_full_stack import evaluate_jetson_process_state

    state, events = evaluate_jetson_process_state(last_state="present", ssh_error="timeout")

    assert state == "unknown"
    assert events == ["[CHECK] SSH check failed: timeout"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watch_full_stack.py::test_component_allowlist_suppresses_missing_warning_for_non_required_component tests/test_watch_full_stack.py::test_parse_pgrep_output_counts_multiple_matches -v`
Expected: FAIL

- [ ] **Step 3: Implement health check helpers**

Include helpers for:
- expectation-mode selection: no flags means all major components required, any flag means allowlist mode
- `evaluate_component_requirement(...)` is the single layer that decides whether a component is required for health warnings
- local process detection using a case-insensitive `spark_app_v2.py` substring match
- SSH process checks using `ssh <target> pgrep -af ...`
- readable path checks for app log and `Z:\` logs
- Jetson process state becoming `unknown` on SSH failure
- duplicate process match counts in startup summary data

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest tests/test_watch_full_stack.py::test_component_allowlist_suppresses_missing_warning_for_non_required_component tests/test_watch_full_stack.py::test_parse_pgrep_output_counts_multiple_matches -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add watch_full_stack.py tests/test_watch_full_stack.py
git commit -m "feat: add watcher health checks"
```

## Task 6: Wire the Main Watch Loop, Startup Summary, and CLI

**Files:**
- Create: `watch_full_stack.py`
- Test: `tests/test_watch_full_stack.py`

- [ ] **Step 1: Write failing integration-style tests for merged output and startup summary**

```python
def test_watch_loop_merges_log_and_check_events_in_arrival_order():
    from watch_full_stack import LogEvent, drain_events

    events = [
        LogEvent(source="PICO", message="heartbeat", timestamp="12:44:40"),
        LogEvent(source="CHECK", message="JETSON bridge recovered", timestamp="12:44:41"),
    ]

    assert drain_events(events) == [
        "[12:44:40] [PICO] heartbeat",
        "[12:44:41] [CHECK] JETSON bridge recovered",
    ]


def test_build_startup_summary_reports_duplicate_process_counts():
    from watch_full_stack import build_startup_summary

    summary = build_startup_summary(
        app_present=True,
        app_log_readable=True,
        jetson_bridge_present=True,
        jetson_bridge_count=2,
        jetson_bridge_log_readable=True,
        jetson_llm_present=True,
        jetson_llm_count=1,
        jetson_llm_log_readable=True,
    )

    assert any("JETSON bridge process present (matches=2)" in line for line in summary)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_watch_full_stack.py::test_watch_loop_merges_log_and_check_events_in_arrival_order tests/test_watch_full_stack.py::test_build_startup_summary_reports_duplicate_process_counts -v`
Expected: FAIL

- [ ] **Step 3: Implement the CLI and watch loop**

Minimum CLI contract:
- `--quiet-seconds`
- `--check-interval`
- `--app-log`
- `--bridge-log`
- `--llm-log`
- `--ssh-target`
- `--expect-app`
- `--expect-jetson-bridge`
- `--expect-jetson-llm`

Required default discovery values for the no-flag path:
- app log: `logs\spark_app_v2.log`
- bridge log: `Z:\demo\pico_bridge\bridge.log`
- llm log: `Z:\demo\llama_demo\server.log`
- ssh target: `192.168.55.1`

Main loop responsibilities:
- print startup summary
- open sources at EOF
- poll tail sources
- poll health checks on interval
- feed all events through one renderer
- continue when individual checks fail
- preserve best-effort arrival order when draining ready events
- report duplicate process counts in the startup summary

- [ ] **Step 4: Run focused test to verify it passes**

Run: `pytest tests/test_watch_full_stack.py::test_watch_loop_merges_log_and_check_events_in_arrival_order tests/test_watch_full_stack.py::test_build_startup_summary_reports_duplicate_process_counts -v`
Expected: PASS

- [ ] **Step 5: Run the full watcher test file**

Run: `pytest tests/test_watch_full_stack.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add watch_full_stack.py tests/test_watch_full_stack.py
git commit -m "feat: add full-stack log watcher"
```

## Task 7: Verify the End-to-End Flow Manually

**Files:**
- Verify: `spark_app_v2.py`
- Verify: `watch_full_stack.py`
- Verify: `Z:\demo\pico_bridge\bridge.log`
- Verify: `Z:\demo\llama_demo\server.log`

- [ ] **Step 1: Run the focused automated test set**

Run: `pytest tests/test_watch_full_stack.py tests/test_watch_pico_cdc_debug.py -v`
Expected: PASS

- [ ] **Step 2: Start the app and watcher manually**

Run in separate terminals:

```powershell
python .\spark_app_v2.py
python .\watch_full_stack.py
```

Expected startup summary should show:
- app process present
- app log readable
- Jetson bridge process present
- Jetson bridge log readable
- Jetson llm process present
- Jetson llm log readable

- [ ] **Step 3: Press `PB1` and confirm merged output**

Expected watcher behavior:
- `[PICO]` lines appear from the app log
- `[JETSON-BRIDGE]` lines appear from `bridge.log`
- `[JETSON-LLM]` lines appear if llama logs during request handling

- [ ] **Step 4: Stop one component intentionally and verify status transitions**

Examples:
- stop the Jetson bridge and expect `missing`
- restart it and expect `recovered`

- [ ] **Step 5: Commit**

```bash
git add spark_app_v2.py watch_full_stack.py tests/test_watch_full_stack.py
git commit -m "test: verify full-stack log watcher"
```

## Task 8: Update Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/WINDOWS_PICO_JETSON_BRINGUP.md`

- [ ] **Step 1: Write failing doc checklist**

Checklist to satisfy:
- watcher command documented
- default source paths documented
- note that watcher observes existing processes and does not launch them
- mention expectation flags and app log dependency

- [ ] **Step 2: Add minimal documentation**

Add one short usage block to `README.md` and one short debugging section to `docs/WINDOWS_PICO_JETSON_BRINGUP.md`.

- [ ] **Step 3: Sanity-read the updated docs**

Verify commands and paths match the implementation exactly.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/WINDOWS_PICO_JETSON_BRINGUP.md
git commit -m "docs: add full-stack watcher usage"
```

## Final Verification

- [ ] Run: `pytest tests/test_watch_full_stack.py tests/test_watch_pico_cdc_debug.py tests/test_pico_llm_bridge.py tests/test_jetson_protocol.py -v`
- [ ] Run the watcher manually against the real stack once more
- [ ] Confirm `spark_app_v2.py` still logs to terminal and to `logs\spark_app_v2.log`
- [ ] Confirm no Pico deploy is needed for this feature because no `pico/` files change
