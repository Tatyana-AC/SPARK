# Full-Stack Log Watcher Design

Date: 2026-04-10

## Goal

Create a single local watcher command that combines the active SPARK logs into one best-effort merged terminal stream and reports when expected components are missing or quiet.

The watcher is for debugging. It does not own application startup or replace existing logs. It observes the stack that is already running and adds health/status lines so failures are visible from one terminal.

## Scope

The watcher covers three physical inputs and four logical sources:

- local SPARK app logs
- Jetson bridge log at `Z:\demo\pico_bridge\bridge.log`
- Jetson llama server log at `Z:\demo\llama_demo\server.log`

The local app log is the primary source for both host-side app lines and Pico-related debug lines that are already forwarded into the host logging stack.

The watcher also performs health checks for:

- local `spark_app_v2.py`
- Jetson `pico_llm_bridge.py`
- Jetson `llama-server`
- local app log readability
- Jetson bridge log readability on `Z:\`
- Jetson LLM log readability on `Z:\`

## Non-Goals

- launching `spark_app_v2.py`
- launching the Jetson bridge
- launching `llama-server`
- replacing existing per-component logs
- building a multi-pane UI

## User Experience

The entrypoint is a new script named `tools/monitoring/watch_full_stack.py`.

Default behavior:

- print a startup summary of discovered sources and health checks
- stream all log lines into one terminal
- prefix each line with local timestamp and source label
- emit watcher-generated health lines with a `[CHECK]` prefix
- continue running when individual sources disappear and recover

Normalized output format:

```text
[12:44:40] [PICO] [JETSON] Request forwarded
[12:44:41] [JETSON-BRIDGE] [UART IN] button_press button_id=0
[12:44:42] [CHECK] JETSON bridge missing
```

The watcher adds the timestamp and top-level source prefix only. It does not rewrite the original component message content.

## Source Model

### App

`spark_app_v2.py` continues logging to its own terminal, but it also writes the same output to a local rotating log file.

The watcher reads from that file and maps lines into logical watcher sources such as `[APP]` and `[PICO]` based on logger/category information in the log record.

Reason: a watcher cannot reliably attach to an already-running terminal session, but it can tail a file written by the app.

### Pico

The watcher does not open the Pico CDC port directly in the default mode.

Instead, it treats Pico debug visibility as part of the app log stream and emits those lines as `[PICO]`.

Reason: this stays compatible with the passive "observe the stack already running" workflow and avoids fighting the running app for an exclusive serial handle.

### Jetson Bridge

The watcher tails `Z:\demo\pico_bridge\bridge.log` and emits new lines as `[JETSON-BRIDGE]`.

### Jetson LLM

The watcher tails `Z:\demo\llama_demo\server.log` and emits new lines as `[JETSON-LLM]`.

## Expected-Running Rules

The watcher checks whether each component is expected and available.

By default, all three major components are expected in the normal full-stack debugging workflow: app, Jetson bridge, and Jetson LLM. The watcher can be narrowed to a smaller expected set with explicit CLI flags so intentional partial sessions do not produce constant false missing warnings.

Expectation flag rule:

- if no `--expect-*` flags are provided, all major components are treated as expected by default
- if any `--expect-*` flag is provided, the watcher switches into allowlist mode and only the explicitly named components are treated as required

### Required checks

- `spark_app_v2.py` process is present locally
- `pico_llm_bridge.py` is present in Jetson process list over SSH
- `llama-server` is present in Jetson process list over SSH
- local app log file is present and readable
- Jetson bridge log path is present and readable on `Z:\`
- Jetson LLM log path is present and readable on `Z:\`

Process match rules:

- local app is considered present when a local process command line contains `spark_app_v2.py` case-insensitively
- Jetson bridge is considered present when `pgrep -af pico_llm_bridge.py` returns one or more matches
- Jetson LLM is considered present when `pgrep -af llama-server` returns one or more matches
- multiple matches still count as present, but the startup summary should report the match count so duplicate processes are visible

### Check output

Health lines use `[CHECK]` and are state-based, not spam-based.

Examples:

- `[CHECK] APP missing`
- `[CHECK] APP log missing`
- `[CHECK] JETSON bridge process missing`
- `[CHECK] JETSON bridge log missing`
- `[CHECK] JETSON llm process missing`
- `[CHECK] JETSON llm log missing`
- `[CHECK] JETSON bridge recovered`

Repeated identical failures are suppressed until state changes.

Process health and log visibility are reported separately. The watcher must not collapse them into a single generic "missing" state.

If SSH health checks fail, Jetson process state becomes `unknown` until SSH succeeds again. While process state is unknown, the watcher emits the SSH failure status but suppresses new Jetson process missing/recovered transitions so it does not report stale state as fact.

## Quiet vs Missing

Missing and quiet are different states.

- Missing means the process or file path is not currently available.
- Quiet means the source still exists but has not produced new lines within a configurable interval.

Quiet timers start only after startup catch-up for a source is complete. Quiet is suppressed while the source is already in a missing state.

Examples:

- `[CHECK] JETSON-BRIDGE quiet for 30s`
- `[CHECK] APP quiet for 30s`

Quiet warnings are softer than missing warnings and should not imply a crash by themselves.

When a previously quiet source starts producing lines again, the watcher emits a recovery-style status line such as `[CHECK] JETSON-BRIDGE active again` once, then clears the quiet state.

Quiet is tracked per emitted logical source label, not per physical file tail. For the local app log this means `[APP]` and `[PICO]` have independent quiet and recovery state even though they come from the same tailed file.

A logical source is eligible for quiet detection only after it has emitted at least one line in the current watcher session. This prevents `[PICO] quiet ...` from appearing before any Pico-related activity has ever been observed.

## Architecture

The watcher has five small pieces:

1. `EventSink`
   Accepts normalized events from all sources and prints one merged stream.

2. `AppLogSource`
   Follows the local app log file and maps app-side logger names into watcher source labels.

3. `FileTailSource`
   Follows the Jetson bridge and LLM log files.

4. `HealthChecker`
   Runs periodic checks for expected processes and mounted log paths.

5. `StateTracker`
   Deduplicates missing, recovered, and quiet transitions.

This split keeps the code small and testable while preserving one terminal output.

### App log source mapping

The watcher uses a small explicit mapping table for local app log records:

- logger name `pico.debug` -> `[PICO]`
- every other app-side logger -> `[APP]`

If a local record does not expose a logger name, it falls back to `[APP]`.

## Data Flow

1. Each source produces raw lines.
2. The watcher normalizes each item into:
   - timestamp
   - source label
   - message text
   - event kind (`log` or `check`)
3. The merged sink prints the normalized line immediately in best-effort arrival order.
4. The health checker updates state independently and emits `[CHECK]` transitions when needed.

Ordering rule:

- output ordering is based on local receive time
- original source timestamps remain visible inside the message text when present
- the watcher does not attempt global clock reconciliation across local files, mounted Jetson files, and SSH-derived checks

Startup tail rule:

- all tailed files start at EOF by default and stream only new lines
- the watcher does not replay the full existing backlog on startup
- a source is considered to have completed startup catch-up as soon as its initial open-and-seek-to-EOF succeeds
- quiet timers begin only after that point

## Failure Handling

The watcher must stay alive if one source fails.

### App log missing

- emit `[CHECK] APP log missing`
- keep running
- recover automatically if the file appears later
- if the rotating log is truncated, rotated, or recreated, reopen it and continue streaming from the new active file without requiring a watcher restart

### Jetson share unavailable

- emit missing lines for affected files
- continue app monitoring and process health checks
- recover automatically when `Z:\` becomes available again
- if tailed Jetson log files are truncated, rotated, or recreated on the mounted share, reopen them and continue from the active file without requiring a watcher restart

### SSH health-check failure

- emit `[CHECK] SSH check failed: ...`
- do not stop other streams
- retry on the next interval

## Logging Changes Needed

### `spark_app_v2.py`

Add a rotating file handler in addition to the current terminal logging.

Constraints:

- do not remove terminal logging
- do not change app behavior
- keep the file location stable and easy for the watcher to discover
- include logger name in each file record so the watcher can distinguish app lines from `pico.debug` and other host-side categories

Recommended path:

- `logs/spark_app_v2.log`

Required file log format:

```text
%(asctime)s %(name)s %(levelname)s %(message)s
```

The watcher parses the record by splitting the first logger-name field from the formatted line. This format is part of the contract for watcher compatibility.

## CLI Shape

Initial flags should stay minimal:

- `--quiet-seconds` to tune quiet detection threshold
- `--check-interval` to tune health-check cadence
- `--app-log` to override the app log path if needed
- `--bridge-log` to override Jetson bridge log path if needed
- `--llm-log` to override Jetson server log path if needed
- `--ssh-target` to override the Jetson SSH host if needed
- `--expect-app`, `--expect-jetson-bridge`, and `--expect-jetson-llm` to control which components are considered required for the current session

Expectation flags are allowlist selectors, not additive toggles on top of the default set.

Expectation flags affect health requirements only. They do not disable log tailing for discovered sources.

If a component is omitted from the expected allowlist, the watcher still prints that component's log lines if the source is available, but it suppresses missing and unreadable `[CHECK]` warnings for that component.

Defaults should match the current environment so the common case is just:

```powershell
python .\tools/monitoring/watch_full_stack.py
```

Default discovery values for the no-flag path:

- app log: `logs\spark_app_v2.log`
- Jetson bridge log: `Z:\demo\pico_bridge\bridge.log`
- Jetson LLM log: `Z:\demo\llama_demo\server.log`
- SSH target: `192.168.55.1`

SSH contract:

- the watcher shells out as `ssh <target> <command>`
- `<target>` comes from `--ssh-target`
- the default target is `192.168.55.1`
- if the local environment requires an explicit username, the caller provides it in the target value, for example `sidac@192.168.55.1`
- authentication, keys, and SSH config are owned by the local environment; the watcher does not manage credentials

## Testing

Add unit tests for:

- source prefix formatting
- state transition deduplication
- quiet detection
- file-tail follow behavior
- app-log category mapping, including `pico.debug`
- file rotation, truncation, and recreation handling for the rotating app log
- health-check status transitions

Add a small integration-style test with fake sources to confirm merged output ordering and recovery reporting.

Manual verification flow:

1. Start `spark_app_v2.py`
2. Start `tools/monitoring/watch_full_stack.py`
3. Confirm startup summary shows all expected sources
4. Press `PB1`
5. Observe one combined timeline across app, Pico, Jetson bridge, and Jetson LLM
6. Stop one component intentionally and confirm `[CHECK] missing`
7. Restore it and confirm `[CHECK] recovered`

## Risks

- app log file path ambiguity if logging setup is ad hoc
- Windows handling of `Z:\` mounted Jetson paths may be slower or temporarily stale
- SSH checks can fail independently from log tailing and must not be treated as proof of total Jetson failure
- merged output can become noisy if llama server logs are too verbose; if needed, source-level filtering can be added later without changing the architecture

## Recommendation

Implement the watcher as a passive observer with one merged stream and explicit health-state lines.

This is the smallest change that gives an end-to-end timeline, detects expected-but-missing services, and stays aligned with the current SPARK workflow where the app and Jetson services already run independently.
