# Anchored Session Synthesis Implementation Plan

> **For agentic workers:** execute this plan task-by-task with focused verification after each task. Keep related code changes grouped; do not rely on `get_active_session()` for synthesis anchoring.

**Goal:** Remove the synthesis anchor race by making host-originated synthesis requests carry `anchor_context_key`, then have Jetson resolve the anchor as the most recent matching stored session and run a two-round keyword-extraction plus retrieval synthesis flow.

**Architecture:** Keep Jetson as the source of truth for stored context. The host computes `anchor_context_key` from the currently active app using the same rule as Jetson, sends it in `synthesize_session`, and Jetson resolves the newest matching stored session. Jetson then runs a first LLM pass to extract retrieval keywords from the anchor, queries recent DB sessions using those keywords, and runs a second LLM pass to synthesize from the anchor plus the retrieved related contexts.

**Tech Stack:** Python, PyQt6, CircuitPython-compatible Pico modules, SQLite, pytest/unittest, existing Raw HID and UART framing.

---

## Reference Spec

- `docs/specs/2026-04-24-anchored-session-synthesis-design.md`

## File Structure

- Modify: `host_pc/summarize_stream.py`
  - Add shared `build_context_key(...)`
  - Change `build_synthesize_session_request(...)` to require `anchor_context_key`
- Modify: `spark_app_v2.py`
  - Build `anchor_context_key` for visible Synthesis and PB1 host-triggered synthesis
  - Stop treating `button:1` as only response polling for a Pico-originated request
- Modify: `jetson/db_manager.py`
  - Add lookup by `context_key`, newest-first
- Modify: `jetson/pico_llm_bridge.py`
  - Resolve synthesis anchors by `anchor_context_key`
  - Remove synthesis fallback to `get_active_session()`
  - Replace token-overlap relevance scoring with two-round keyword extraction and DB retrieval
- Modify: `pico/bridge_app.py`
  - Remove PB1 fixed synthesis payload behavior
  - Keep PB1 as a host-visible trigger path only
- Modify: `README.md`, `docs/pico/README.md`, `docs/pico/HARDWARE_SMOKE_TEST.md`
  - Update docs to describe host-computed `anchor_context_key` anchoring
- Test: `tests/test_summarize_stream.py`
- Test: `tests/test_spark_panel_ui.py`
- Test: `tests/test_pico_bridge_app.py`
- Test: `tests/test_jetson_db.py`
- Test: `tests/test_pico_llm_bridge.py`
- Test: `tests/test_watch_full_stack.py`

## Task 1: Share `context_key` Computation Between Host And Jetson `[USER-REQ]`

**Requirement:** the host should compute the same anchor identifier Jetson uses, and `context_key` alone is enough for anchor selection.

**Files:**
- Modify: `host_pc/summarize_stream.py`
- Test: `tests/test_summarize_stream.py`

- [ ] Add failing tests for:
  - `build_context_key("Google Chrome", "Chrome", "https://en.wikipedia.org/wiki/Boston_Tea_Party")` -> `Google Chrome|https://en.wikipedia.org/wiki/Boston_Tea_Party`
  - `build_context_key("Notes", "Notes", None)` -> `Notes|Notes`
  - `build_synthesize_session_request(anchor_context_key="...")` includes `anchor_context_key`
  - empty `anchor_context_key` is rejected
- [ ] Implement:
  - `build_context_key(app_name: str, window_title: str, url: str | None) -> str`
  - `build_synthesize_session_request(anchor_context_key: str, window_minutes: int = 30) -> str`
- [ ] Verify with:

```bash
./.venv/bin/python -m pytest tests/test_summarize_stream.py -q
```

## Task 2: Route Visible Synthesis Through `anchor_context_key` `[USER-REQ]`

**Requirement:** visible Synthesis must anchor on the app active at trigger time, not on whatever Jetson later thinks is active.

**Files:**
- Modify: `spark_app_v2.py`
- Test: `tests/test_spark_panel_ui.py`

- [ ] Add failing tests for:
  - visible Synthesis action computes `anchor_context_key` and sends it in `build_synthesize_session_request(...)`
  - if the active app lacks both URL and usable window title, host fails explicitly instead of sending synthesis
- [ ] Implement:
  - current active app lookup for `_on_summarize()`
  - host-side `anchor_context_key` computation using the shared helper
  - explicit failure path when the host cannot build an anchor key
- [ ] Keep user-facing Synthesis labels/status text unchanged apart from any anchor-error wording needed for clarity
- [ ] Verify with:

```bash
./.venv/bin/python -m pytest tests/test_spark_panel_ui.py -q
```

## Task 3: Make PB1 Host-Mediated `[USER-REQ]`

**Requirement:** PB1 must use the same anchored synthesis semantics as the visible Synthesis action.

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `pico/bridge_app.py`
- Test: `tests/test_spark_panel_ui.py`
- Test: `tests/test_pico_bridge_app.py`

- [ ] Add failing tests for:
  - `button:1` causes the host to send the same `synthesize_session` request shape as `_on_summarize()`
  - Pico PB1 no longer injects a fixed `{"command":"synthesize_session"...}` payload on its own
- [ ] Implement:
  - host-side PB1 synthesis trigger path
  - Pico PB1 behavior reduced to button event / host-visible trigger only
  - preserve transport compatibility for host-originated `FEATURE_1` requests
- [ ] Verify with:

```bash
./.venv/bin/python -m pytest tests/test_pico_bridge_app.py tests/test_spark_panel_ui.py -q
```

## Task 4: Add Exact Anchor Lookup On Jetson `[USER-REQ]`

**Requirement:** if multiple stored sessions share the same `context_key`, Jetson should use the most recent one.

**Files:**
- Modify: `jetson/db_manager.py`
- Test: `tests/test_jetson_db.py`

- [ ] Add failing tests for:
  - lookup by `context_key` returns newest row by `COALESCE(host_observed_at, updated_at) DESC, id DESC`
  - no-match lookup returns `None`
- [ ] Implement:
  - `get_latest_session_for_context_key(context_key: str) -> Optional[sqlite3.Row]`
- [ ] Keep existing recent-session query support intact
- [ ] Verify with:

```bash
./.venv/bin/python -m pytest tests/test_jetson_db.py -q
```

## Task 5: Anchor Synthesis By Request Key, Not Active Session `[USER-REQ]`

**Requirement:** Jetson must not race on mutable active-session state for synthesis anchoring.

**Files:**
- Modify: `jetson/pico_llm_bridge.py`
- Test: `tests/test_pico_llm_bridge.py`

- [ ] Add failing tests for:
  - `synthesize_session` resolves anchor from `anchor_context_key`
  - when multiple rows share that key, the newest one wins
  - if the key does not resolve, Jetson returns explicit no-anchor behavior
  - synthesis does not fall back to `get_active_session()`
- [ ] Implement:
  - request parsing for `anchor_context_key`
  - anchor lookup via `get_latest_session_for_context_key(...)`
  - no-anchor error/warning path
  - two-round synthesis flow:
    - round 1 keyword extraction from anchor-only context
    - DB retrieval over extracted keywords
    - round 2 synthesis from anchor plus retrieved contexts
- [ ] Keep `summarize` behavior unchanged
- [ ] Verify with:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -q
```

## Task 6: Regression Coverage For Keyword-Based Related Retrieval `[AGENT-DECISION]`

**Requirement served:** only relevant recent app context should be included in synthesis.

**Files:**
- Modify: `tests/test_pico_llm_bridge.py`
- Modify: `jetson/pico_llm_bridge.py` if needed

- [ ] Keep / refine tests proving:
  - useful Notes context survives for a history-topic anchor
  - unrelated technical pages do not survive merely because of generic token overlap
  - noisy same-app browser shell rows do not survive keyword retrieval
  - abbreviation-expanded keywords can retrieve the intended rows
- [ ] Verify with:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -q
```

## Task 7: Docs And Operator Guidance `[USER-REQ]`

**Requirement:** docs should describe the real anchoring behavior and PB1 semantics.

**Files:**
- Modify: `README.md`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`

- [ ] Update docs so they say:
  - synthesis request includes `anchor_context_key`
  - Jetson resolves the most recent matching stored session as the anchor
  - PB1 uses the same host-mediated anchored synthesis behavior as the visible Synthesis action
  - `summarize` remains internal/debug-only
- [ ] Remove outdated wording that implies PB1 or Jetson-alone anchor selection is still authoritative

## Verification Sweep

- [ ] Focused test sweep:

```bash
./.venv/bin/python -m pytest \
  tests/test_summarize_stream.py \
  tests/test_spark_panel_ui.py \
  tests/test_pico_bridge_app.py \
  tests/test_jetson_db.py \
  tests/test_pico_llm_bridge.py \
  tests/test_watch_full_stack.py -q
```

- [ ] Sync updated `jetson/pico_llm_bridge.py` to Jetson and restart the bridge
- [ ] If `pico/` behavior changes, deploy the Pico runtime to `/Volumes/CIRCUITPY`
- [ ] Manual validation (user-run):
  - trigger Synthesis on a known anchor page
  - confirm the newest audit-log entry uses that anchor page rather than a later-focused app
  - confirm related context excludes noisy same-app browser shell rows
