# Anchored Session Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Priority rule:** Tasks tagged `[USER-REQ]` implement non-negotiable user requirements. Tasks tagged `[AGENT-DECISION]` implement flexible agent design decisions. If a conflict arises during implementation, agent decisions yield to user requirements. If a user requirement cannot be met, stop and surface to the user.

**Goal:** Replace user-facing/PB1 active-app summary behavior with active-app-anchored 30-minute session synthesis while preserving the old `summarize` command as an internal primitive.

**Architecture:** Keep the existing Host -> Pico -> Jetson transport. Add a new `synthesize_session` JSON command, make PB1 and any visible Synthesis path send that command, and implement Jetson-side recent-session selection/ranking from the existing SQLite context store.

**Tech Stack:** Python, PyQt6, CircuitPython-compatible Pico modules, SQLite, pytest/unittest, existing Raw HID and UART framing.

---

## Reference Spec

- `docs/specs/2026-04-24-anchored-session-synthesis-design.md`

## File Structure

- Modify: `host_pc/summarize_stream.py`
  - Owns JSON request builders for host-triggered feature requests.
  - Add `build_synthesize_session_request(window_minutes: int = 30)`.
  - Keep `build_summarize_command()` unchanged for internal/debug use.
- Modify: `spark_app_v2.py`
  - Owns the SPARK panel action wiring, feature request dispatch, and user-facing labels/status text.
  - Route Synthesis/FEATURE_1 through `synthesize_session`.
  - Remove user-facing active-summary wording.
- Modify: `pico/bridge_app.py`
  - Owns Pico-side app-command forwarding and PB1 button-triggered request text.
  - Change PB1 fixed command text from `summarize` to `synthesize_session`.
- Modify: `jetson/db_manager.py`
  - Owns durable context storage and DB queries.
  - Add recent-session query support for a fixed lookback cutoff.
- Modify: `jetson/pico_llm_bridge.py`
  - Owns Jetson command parsing, prompt construction, LLM payload building, and button-press fallback behavior.
  - Add `synthesize_session` command handling, source-bundle prompt helpers, and PB1 fallback payload.
- Modify: `README.md`, `docs/pico/README.md`, `docs/pico/HARDWARE_SMOKE_TEST.md`
  - Replace user-facing active summary wording with Synthesis/session wording.
- Test: `tests/test_summarize_stream.py`
- Test: `tests/test_spark_panel_ui.py`
- Test: `tests/test_pico_bridge_app.py`
- Test: `tests/test_jetson_db.py`
- Test: `tests/test_pico_llm_bridge.py`
- Test: `tests/test_context_stream_e2e.py`

## Task 1: Add The Session Synthesis Request Builder `[USER-REQ]`

**Requirement:** "The implementation should use a new internal command for session synthesis instead of overloading the existing active-app summarize command" and "the first implementation should use a fixed 30-minute recent-context window."

**Files:**
- Modify: `host_pc/summarize_stream.py`
- Test: `tests/test_summarize_stream.py`

- [ ] **Step 1: Write failing request-builder tests**

Add tests:

```python
def test_build_synthesize_session_request_uses_fixed_default_window(self):
    from host_pc.summarize_stream import build_synthesize_session_request

    request = json.loads(build_synthesize_session_request())

    self.assertEqual(request["command"], "synthesize_session")
    self.assertEqual(request["window_minutes"], 30)
    self.assertEqual(len(request), 2)


def test_build_synthesize_session_request_rejects_non_positive_windows(self):
    from host_pc.summarize_stream import build_synthesize_session_request

    with self.assertRaises(ValueError):
        build_synthesize_session_request(0)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_summarize_stream.py -q
```

Expected: FAIL because `build_synthesize_session_request` does not exist.

- [ ] **Step 3: Implement minimal request builder**

Add:

```python
def build_synthesize_session_request(window_minutes: int = 30) -> str:
    """Build an anchored session synthesis request."""
    window_minutes = int(window_minutes)
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    return json.dumps(
        {
            "command": "synthesize_session",
            "window_minutes": window_minutes,
        }
    )
```

Do not change `build_summarize_command()`.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_summarize_stream.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add host_pc/summarize_stream.py tests/test_summarize_stream.py
git commit -m "feat: add session synthesis request builder"
```

## Task 2: Route Host Synthesis Through The New Command `[USER-REQ]`

**Requirement:** "Active-app-only `summarize` should remain available in code and protocol paths, but should not be exposed anywhere in the user-facing UI."

**Files:**
- Modify: `spark_app_v2.py`
- Test: `tests/test_spark_panel_ui.py`

- [ ] **Step 1: Write failing host UI tests**

Replace the active-summary `_on_summarize` test with a synthesis-specific test:

```python
def test_synthesis_action_sends_session_synthesis_command(self):
    panel = self._make_panel()
    panel._start_feature_request = mock.Mock()

    with mock.patch.object(spark_app_v2, "build_synthesize_session_request", return_value="SYNTH_REQUEST") as build:
        panel._on_summarize()

    build.assert_called_once_with()
    panel._start_feature_request.assert_called_once()
    args, kwargs = panel._start_feature_request.call_args
    self.assertEqual(kwargs.get("app_command", args[0]), spark_app_v2.AppCommand.FEATURE_1)
    self.assertEqual(kwargs.get("request", args[1] if len(args) > 1 else None), "SYNTH_REQUEST")
    self.assertIn("SYNTHESIS", kwargs.get("capture_label", ""))
    self.assertIn("synthesis", kwargs.get("status_text", "").lower())
```

Add a guard that no visible action button uses active-summary language:

```python
def test_no_visible_button_exposes_active_app_summary(self):
    panel = self._make_panel()

    visible_titles = [
        btn._title_lbl.text()
        for btn in panel.findChildren(spark_app_v2.ActionButton)
        if not btn.isHidden()
    ]

    self.assertNotIn("Summarize Window", visible_titles)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_spark_panel_ui.py -q
```

Expected: FAIL because `spark_app_v2` still imports/calls `build_summarize_command()` in `_on_summarize`.

- [ ] **Step 3: Update host import and action wording**

In `spark_app_v2.py`:

- Import `build_synthesize_session_request`.
- Keep `build_summarize_command` import only if still needed by internal/dev code. If unused after this task, remove the import.
- Change the hidden legacy button label from `Summarize Window` to `Synthesis`.
- Change `_on_summarize()` to use `build_synthesize_session_request()`.

Target implementation:

```python
def _on_summarize(self):
    """Send anchored session synthesis command; Jetson builds the source bundle."""
    request = build_synthesize_session_request()
    self._start_feature_request(
        AppCommand.FEATURE_1,
        request=request,
        capture_label="[SYNTHESIS] Anchor active app and recent context",
        status_text="Sending session synthesis request to Jetson...",
    )
```

- [ ] **Step 4: Update FEATURE_1 status wording**

In `_on_summarize_succeeded()` and `_on_summarize_progress()`, keep FEATURE_2/3/4 behavior unchanged, but change the default FEATURE_1 text:

```python
self._set_status("Jetson synthesis complete - output updated", GREEN)
```

and:

```python
self._set_status("Streaming synthesis from Jetson...", ORANGE)
```

Use ASCII ellipses/hyphens if editing nearby strings that currently use Unicode punctuation is not necessary.

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_spark_panel_ui.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add spark_app_v2.py tests/test_spark_panel_ui.py
git commit -m "feat: route host synthesis through session command"
```

## Task 3: Route Pico PB1 Through Session Synthesis `[USER-REQ]`

**Requirement:** "Physical Push Button 1 must trigger the new session synthesis behavior, not active-app-only summary."

**Files:**
- Modify: `pico/bridge_app.py`
- Test: `tests/test_pico_bridge_app.py`

- [ ] **Step 1: Write failing Pico PB1 tests**

Update the PB1 test name and expectation:

```python
def test_button_0_uses_session_synthesis_payload(self):
    from pico.bridge_app import BridgeApp
    from pico.upload_protocol import AppCommand
    from host_pc.summarize_stream import build_synthesize_session_request

    payload = build_synthesize_session_request()
    transport = types.SimpleNamespace(start_request=mock.Mock())
    app = BridgeApp(
        jetson_transport=transport,
        runtime_status=self._make_runtime_status(),
    )

    result = app.handle_button_press(0)

    transport.start_request.assert_called_once_with(payload.encode("utf-8"))
    self.assertEqual(result["accepted_text"], payload)
    self.assertEqual(result["app_command"], int(AppCommand.FEATURE_1))
```

Keep the existing test proving host-uploaded `FEATURE_1` forwards arbitrary payloads unchanged.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_bridge_app.py -q
```

Expected: FAIL because PB1 still forwards `{"command": "summarize"}`.

- [ ] **Step 3: Change Pico fixed PB1 command text**

In `pico/bridge_app.py`, replace:

```python
SUMMARIZE_COMMAND_TEXT = '{"command": "summarize"}'
```

with:

```python
SYNTHESIZE_SESSION_COMMAND_TEXT = '{"command":"synthesize_session","window_minutes":30}'
```

Then update `handle_button_press(0)` to forward `SYNTHESIZE_SESSION_COMMAND_TEXT`.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_bridge_app.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pico/bridge_app.py tests/test_pico_bridge_app.py
git commit -m "feat: route pico pb1 to session synthesis"
```

## Task 4: Add Recent Session Query Support `[USER-REQ]`

**Requirement:** "The first implementation should use a fixed 30-minute recent-context window" and "the system should consider relevant context from other recent apps when those apps relate to the active app's topic."

**Files:**
- Modify: `jetson/db_manager.py`
- Test: `tests/test_jetson_db.py`

- [ ] **Step 1: Write failing DB tests**

Add tests for cutoff filtering, host-observed ordering, and context-key dedupe:

```python
def test_recent_sessions_since_uses_host_observed_cutoff(self):
    self.db.on_context_new(make_payload(window_title="old", timestamp=100.0, text="old"))
    self.db.on_context_new(make_payload(window_title="new", pid=43, timestamp=500.0, text="new"))

    rows = self.db.get_recent_sessions_since(200.0)

    self.assertEqual([row["window_title"] for row in rows], ["new"])


def test_recent_sessions_since_dedupes_context_key_to_newest(self):
    self.db.on_context_new(make_payload(
        app_name="Chrome",
        process_name="chrome.exe",
        pid=1,
        window_title="Boston Tea Party",
        url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
        text="old text",
        timestamp=100.0,
    ))
    self.db.on_context_new(make_payload(
        app_name="Notes",
        process_name="notes.exe",
        pid=2,
        window_title="Essay",
        text="Tea Act notes",
        timestamp=200.0,
    ))
    self.db.on_context_new(make_payload(
        app_name="Chrome",
        process_name="chrome.exe",
        pid=1,
        window_title="Boston Tea Party",
        url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
        text="new text",
        timestamp=300.0,
    ))

    rows = self.db.get_recent_sessions_since(0.0, dedupe=True)

    self.assertEqual([row["text"] for row in rows], ["new text", "Tea Act notes"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_jetson_db.py -q
```

Expected: FAIL because `get_recent_sessions_since` does not exist.

- [ ] **Step 3: Implement recent-session query**

Add to `JetsonDB`:

```python
def get_recent_sessions_since(self, cutoff_timestamp: float, *, limit: int = 20, dedupe: bool = True):
    rows = self._conn.execute(
        f"""
        SELECT *
        FROM sessions
        WHERE COALESCE(host_observed_at, updated_at) >= ?
        ORDER BY {_SESSION_RECENCY_ORDER}
        LIMIT ?
        """,
        (float(cutoff_timestamp), int(limit) * 3 if dedupe else int(limit)),
    ).fetchall()
    if not dedupe:
        return rows[:limit]

    seen = set()
    deduped = []
    for row in rows:
        key = row["context_key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_jetson_db.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jetson/db_manager.py tests/test_jetson_db.py
git commit -m "feat: query recent jetson sessions"
```

## Task 5: Build Anchored Synthesis Prompting `[USER-REQ]`

**Requirement:** "The active app should be the anchor topic for synthesis" and "the system should consider relevant context from other recent apps when those apps relate to the active app's topic."

**Files:**
- Modify: `jetson/pico_llm_bridge.py`
- Test: `tests/test_pico_llm_bridge.py`

- [ ] **Step 1: Write failing prompt tests**

Add tests:

```python
def test_synthesize_session_prompt_includes_active_anchor_and_related_notes(self):
    self.db.on_context_new(_make_context_payload(
        app_name="Notes",
        window_title="History notes",
        pid=2001,
        url=None,
        text="Notes mention the Tea Act and East India Company.",
        timestamp=1000.0,
    ))
    self.db.on_context_new(_make_context_payload(
        app_name="System Settings",
        window_title="Displays",
        pid=2002,
        url=None,
        text="Brightness and display arrangement.",
        timestamp=1100.0,
    ))
    self.db.on_context_new(_make_context_payload(
        app_name="Chrome",
        window_title="Boston Tea Party - Wikipedia",
        pid=2003,
        url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
        text="The Boston Tea Party was a protest involving the Tea Act and East India Company.",
        timestamp=1200.0,
    ))

    raw = json.dumps({"command": "synthesize_session", "window_minutes": 30})
    with mock.patch("jetson.pico_llm_bridge.time.time", return_value=1200.0):
        system, prompt = build_llm_request(raw, SYSTEM_PROMPT, db=self.db)

    self.assertIn("session synthesis", system.lower())
    self.assertIn("ANCHOR SOURCE", prompt)
    self.assertIn("Boston Tea Party - Wikipedia", prompt)
    self.assertIn("RELATED RECENT SOURCES", prompt)
    self.assertIn("History notes", prompt)
    self.assertNotIn("Brightness and display arrangement", prompt)
```

```python
def test_synthesize_session_without_related_context_is_anchor_only(self):
    self.db.on_context_new(_make_context_payload(
        app_name="Chrome",
        window_title="Boston Tea Party - Wikipedia",
        text="Boston Tea Party article text",
        timestamp=1200.0,
    ))

    with mock.patch("jetson.pico_llm_bridge.time.time", return_value=1200.0):
        _, prompt = build_llm_request(
            json.dumps({"command": "synthesize_session", "window_minutes": 30}),
            SYSTEM_PROMPT,
            db=self.db,
        )

    self.assertIn("No related recent context cleared the relevance threshold", prompt)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -q
```

Expected: FAIL because `synthesize_session` is not handled.

- [ ] **Step 3: Add local anchor/relevance helpers**

Implement deterministic v1 helpers in `jetson/pico_llm_bridge.py`:

Add `import re` near the other standard-library imports if it is not already present.

```python
SYNTHESIS_SYSTEM_PROMPT = (
    "You perform anchored session synthesis for SPARK. "
    "The active app is the anchor. Use only related recent context that helps explain or extend the active work."
)

_SYNTHESIS_MAX_RELATED = 5
_SYNTHESIS_SOURCE_CHARS = 1200
```

Add simple token extraction:

```python
def _extract_relevance_terms(*parts: str) -> set[str]:
    text = " ".join(part or "" for part in parts).lower()
    raw_terms = re.findall(r"[a-z0-9][a-z0-9-]{2,}", text)
    stop = {"the", "and", "for", "with", "from", "this", "that", "window", "https", "www"}
    return {term for term in raw_terms if term not in stop}
```

Add scoring:

```python
def _score_related_session(anchor_terms: set[str], row) -> int:
    haystack = " ".join(
        str(row[name] or "")
        for name in ("app_name", "window_title", "tab_title", "url", "text")
    ).lower()
    return sum(1 for term in anchor_terms if term in haystack)
```

Add prompt builder:

```python
def _build_synthesize_session_prompt(anchor, related_rows, *, window_minutes: int) -> str:
    # Build labeled ANCHOR SOURCE and RELATED RECENT SOURCES sections.
    # Trim text fields to _SYNTHESIS_SOURCE_CHARS.
```

The prompt must include:

- instruction that active app is anchor
- fixed "last 30 minutes" wording
- anchor app/title/url/text
- related app/title/url/text
- no-related-context fallback line

- [ ] **Step 4: Add `synthesize_session` command handling**

In `build_llm_request()` before `summarize`:

```python
if command == "synthesize_session":
    if db is None:
        return SYNTHESIS_SYSTEM_PROMPT, "(no database available)"
    session = db.get_active_session()
    if session is None:
        return SYNTHESIS_SYSTEM_PROMPT, "(no active session)"
    window_minutes = int(request.get("window_minutes") or 30)
    cutoff = time.time() - (window_minutes * 60)
    candidates = db.get_recent_sessions_since(cutoff, limit=20, dedupe=True)
    anchor_terms = _extract_relevance_terms(
        session["app_name"],
        session["window_title"],
        session["tab_title"],
        session["url"],
        session["text"],
    )
    related = []
    for row in candidates:
        if int(row["id"]) == int(session["id"]):
            continue
        score = _score_related_session(anchor_terms, row)
        if score > 0:
            related.append((score, row))
    related.sort(key=lambda item: item[0], reverse=True)
    user_prompt = _build_synthesize_session_prompt(
        session,
        [row for _, row in related[:_SYNTHESIS_MAX_RELATED]],
        window_minutes=window_minutes,
    )
    return SYNTHESIS_SYSTEM_PROMPT, user_prompt
```

If tests need deterministic time, patch `jetson.pico_llm_bridge.time.time`.

- [ ] **Step 5: Keep structured response disabled for synthesis**

In `handle_summarize_request()`, wherever reformat/respond/keyword bypass structured JSON response mode, include `synthesize_session`. Synthesis should return plain text, not the old summary JSON schema.

- [ ] **Step 6: Run tests to verify pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add jetson/pico_llm_bridge.py tests/test_pico_llm_bridge.py
git commit -m "feat: build anchored session synthesis prompts"
```

## Task 6: Update Button-Press Fallback And End-To-End Coverage `[USER-REQ]`

**Requirement:** "Physical Push Button 1 must trigger the new session synthesis behavior, not active-app-only summary."

**Files:**
- Modify: `jetson/pico_llm_bridge.py`
- Test: `tests/test_context_stream_e2e.py`
- Test: `tests/test_pico_llm_bridge.py`

- [ ] **Step 1: Write failing fallback tests**

Add a bridge-level helper test:

```python
from jetson.pico_llm_bridge import _button_press_request_text


def test_button_press_fallback_uses_synthesize_session_request(self):
    request = json.loads(_button_press_request_text(0))

    self.assertEqual(
        request,
        {
            "command": "synthesize_session",
            "window_minutes": 30,
        },
    )
```

This test should fail until `_button_press_request_text()` exists. Use that helper inside the `PKT_BUTTON_PRESS` branch so direct Jetson-side button packets cannot keep the old `summarize` semantics.

- [ ] **Step 2: Add composed prompt test**

In `tests/test_context_stream_e2e.py`, add a composed DB-backed prompt test:

```python
def test_synthesize_session_includes_anchor_and_related_recent_context(self):
    self.sender.send_context_new(_make_snapshot(
        app_name="Notes",
        title="History notes",
        text="Essay notes about Tea Act and East India Company",
        url=None,
        pid=2001,
        timestamp=1000.0,
    ))
    self._relay()
    self.sender.send_context_new(_make_snapshot(
        app_name="Firefox",
        title="Boston Tea Party - Wikipedia",
        text="Boston Tea Party article with Tea Act details",
        url="https://en.wikipedia.org/wiki/Boston_Tea_Party",
        pid=2002,
        timestamp=1200.0,
    ))
    self._relay()

    with mock.patch("jetson.pico_llm_bridge.time.time", return_value=1200.0):
        _, prompt = build_llm_request(
            '{"command":"synthesize_session","window_minutes":30}',
            "sys",
            db=self.db,
        )

    self.assertIn("ANCHOR SOURCE", prompt)
    self.assertIn("Boston Tea Party - Wikipedia", prompt)
    self.assertIn("RELATED RECENT SOURCES", prompt)
    self.assertIn("History notes", prompt)
```

Add `from unittest import mock` to the file if needed.

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_context_stream_e2e.py tests/test_pico_llm_bridge.py -q
```

Expected: FAIL until fallback/helper and synthesis command are fully wired.

- [ ] **Step 4: Implement fallback helper**

In `jetson/pico_llm_bridge.py`, add:

```python
SYNTHESIZE_SESSION_COMMAND_TEXT = '{"command":"synthesize_session","window_minutes":30}'
```

Use it in the `PKT_BUTTON_PRESS` branch instead of `{"command": "summarize"}`.

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_context_stream_e2e.py tests/test_pico_llm_bridge.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add jetson/pico_llm_bridge.py tests/test_context_stream_e2e.py tests/test_pico_llm_bridge.py
git commit -m "feat: use synthesis for pb1 fallback"
```

## Task 7: Update Active Documentation `[USER-REQ]`

**Requirement:** "Active-app-only `summarize` should remain available in code and protocol paths, but should not be exposed anywhere in the user-facing UI."

**Files:**
- Modify: `README.md`
- Modify: `docs/pico/README.md`
- Modify: `docs/pico/HARDWARE_SMOKE_TEST.md`

- [ ] **Step 1: Write a failing docs/reference check**

Run:

```bash
rg -n "Summarize Window|summarize requests|active application context|active-window" README.md docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md
```

Expected before docs update: matches still mention active-window/user-facing summarize wording.

- [ ] **Step 2: Update active docs**

Rewrite public docs to say:

- PB1/Synthesis sends `synthesize_session`.
- Synthesis anchors on the active app and uses related context from the fixed last 30 minutes.
- `summarize` remains an internal active-session command for tests/debugging.
- `FEATURE_1` is still the transport command, but its public PB1/default payload is session synthesis.

Keep references to "summarize response chunks" only where they describe the existing wire packet names (`build_summarize_chunk`, `summarize_done`) rather than product behavior.

- [ ] **Step 3: Verify docs references**

Run:

```bash
rg -n "Summarize Window|summarize requests|active application context|active-window" README.md docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md
```

Expected: no user-facing stale product wording remains. Packet/protocol helper names may still appear outside these docs if they are literal API names.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/pico/README.md docs/pico/HARDWARE_SMOKE_TEST.md
git commit -m "docs: describe anchored session synthesis"
```

## Task 8: Run Focused Verification And Deploy Pico Runtime `[USER-REQ]`

**Requirement:** "Physical Push Button 1 must trigger the new session synthesis behavior" and AGENTS.md requires Pico deploy after changing Pico deploy/runtime support files.

**Files:**
- Verify: all touched code/tests
- Deploy: mounted `/Volumes/CIRCUITPY`

- [ ] **Step 1: Run focused test suite**

Run:

```bash
./.venv/bin/python -m pytest \
  tests/test_summarize_stream.py \
  tests/test_spark_panel_ui.py \
  tests/test_pico_bridge_app.py \
  tests/test_jetson_db.py \
  tests/test_pico_llm_bridge.py \
  tests/test_context_stream_e2e.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Verify no user-facing stale docs remain**

Run:

```bash
rg -n "Summarize Window|Summarize active context|Quick overview of visible text" README.md docs spark_app_v2.py tests
```

Expected: no stale user-facing matches. Internal test names/comments may mention `summarize` only when asserting the old internal command remains.

- [ ] **Step 3: Confirm `CIRCUITPY` is mounted read-write**

Run:

```bash
diskutil info /Volumes/CIRCUITPY
```

Expected: mounted and writable. If read-only or unavailable, stop and tell the user to reconnect/reset the Pico so it remounts read-write.

- [ ] **Step 4: Deploy Pico runtime**

Run from repo root:

```bash
./.venv/bin/python tools/pico/deploy_to_pico.py --target /Volumes/CIRCUITPY
```

Expected: deploy succeeds and copies the updated `pico/bridge_app.py` runtime support.

- [ ] **Step 5: Run optional hardware smoke if the device is available**

Run the existing smoke helper or use `docs/pico/HARDWARE_SMOKE_TEST.md` instructions to trigger PB1.

Expected:

- PB1 emits `button:1`.
- PB1 starts a Jetson request containing `synthesize_session`.
- The returned text streams into `RELEASE OUTPUT`.

- [ ] **Step 6: Commit verification docs if changed**

Only commit if this task required documentation updates beyond Task 7:

```bash
git add <changed-docs>
git commit -m "docs: record session synthesis validation"
```

## Final Review Checklist

- [ ] `synthesize_session` exists and defaults to 30 minutes.
- [ ] PB1 sends `synthesize_session`, not `summarize`.
- [ ] Host Synthesis sends `synthesize_session`, not `summarize`.
- [ ] `summarize` still exists and still summarizes only the active DB session.
- [ ] No user-facing UI exposes active-app-only summary.
- [ ] Jetson synthesis prompt includes active anchor first.
- [ ] Related context is limited to the fixed last 30 minutes.
- [ ] Unrelated recent contexts are excluded.
- [ ] Pico runtime is deployed or an explicit board-unavailable blocker is reported.
