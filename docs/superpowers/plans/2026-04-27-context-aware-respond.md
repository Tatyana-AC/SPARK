# Context-Aware RESPOND Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild RESPOND so Jetson first classifies the visible app context, then drafts either a reply, draft continuation, or neutral recent-work update using the fixed 30-minute session window.

**Architecture:** Keep the existing host/Pico transport command, `respond_selection`, and move the behavior branch into Jetson where the active session DB and recent-session retrieval already live. Host sends focused compose text only; Jetson always classifies the active visible context, retrieves recent context according to mode, and sends one final plain-text draft back over the existing streaming response path.

**Tech Stack:** Python, PyQt host app, CircuitPython Pico transport, Jetson SQLite `JetsonDB`, llama.cpp OpenAI-compatible `/v1/chat/completions`, `pytest`.

---

## File Structure

- Modify `spark_app_v2.py`: change `_on_respond()` to use focused element text only and allow empty drafts.
- Modify `host_pc/summarize_stream.py`: keep `build_respond_request()` as the JSON envelope; no schema change is required.
- Do not modify `jetson/db_manager.py`: use existing `get_recent_sessions_since(...)`, `get_recent_sessions_matching_text_since(...)`, and `get_active_session()` APIs.
- Modify `jetson/pico_llm_bridge.py`: add RESPOND classifier prompts, parser, retrieval helpers, draft prompt builder, and handler orchestration.
- Modify `tests/test_spark_panel_ui.py`: host behavior tests for focused-only draft extraction and empty-draft requests.
- Modify `tests/test_pico_llm_bridge.py`: Jetson unit tests for classification, four prompt modes, retrieval, fallbacks, and handler call ordering.
- Deploy after implementation: sync `jetson/` bundle to `/mnt/usb_drive/demo/pico_bridge` and restart `pico_llm_bridge.py`.

---

### Task 1: Host RESPOND Sends Focused Text Only

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `tests/test_spark_panel_ui.py`

- [ ] **Step 1: Write failing test for empty focused text sending empty draft**

Add this test beside the existing RESPOND tests in `tests/test_spark_panel_ui.py`:

```python
def test_respond_sends_empty_draft_when_focused_text_is_empty(self):
    manager = mock.Mock()
    manager.get_active_window_info.return_value = types.SimpleNamespace(bundle_id="com.test.app", title="Messages")
    manager.get_focused_element_text.return_value = "   "
    manager.get_window_text.return_value = "Other person: can you send me an update?"

    panel = self._make_panel()
    panel.manager = manager
    panel.processed_text = "old captured text"

    with (
        mock.patch.object(spark_app_v2, "build_respond_request") as build_respond,
        mock.patch.object(panel, "_start_feature_request") as start_feature_request,
    ):
        build_respond.return_value = "RESPOND_REQUEST"
        panel._on_respond()

    manager.get_focused_element_text.assert_called_once_with()
    manager.get_window_text.assert_not_called()
    build_respond.assert_called_once_with("")
    start_feature_request.assert_called_once()
```

- [ ] **Step 2: Write failing test that window text is not used as draft**

Update the existing `test_respond_falls_back_to_window_text_when_focused_text_is_empty` so it expects no fallback:

```python
def test_respond_does_not_use_window_text_as_draft(self):
    manager = mock.Mock()
    manager.get_active_window_info.return_value = types.SimpleNamespace(bundle_id="com.test.app", title="Slack")
    manager.get_focused_element_text.return_value = ""
    manager.get_window_text.return_value = "Teammate: what changed in RESPOND?"

    panel = self._make_panel()
    panel.manager = manager
    panel.processed_text = "old captured text"

    with (
        mock.patch.object(spark_app_v2, "build_respond_request") as build_respond,
        mock.patch.object(panel, "_start_feature_request") as start_feature_request,
    ):
        build_respond.return_value = "RESPOND_REQUEST"
        panel._on_respond()

    manager.get_focused_element_text.assert_called_once_with()
    manager.get_window_text.assert_not_called()
    build_respond.assert_called_once_with("")
    start_feature_request.assert_called_once()
```

- [ ] **Step 3: Run host tests to verify RED**

Run:

```bash
./.venv/bin/python -m pytest tests/test_spark_panel_ui.py -k respond -q
```

Expected: the new/updated RESPOND tests fail because `_on_respond()` still calls `get_window_text()` and fails when no draft exists.

- [ ] **Step 4: Implement focused-only RESPOND extraction**

Replace the draft extraction block in `spark_app_v2.py::_on_respond()` with:

```python
draft_text = self.manager.get_focused_element_text()
if not (draft_text and draft_text.strip()):
    draft_text = ""

request = build_respond_request(draft_text)
capture_label = (
    "[RESPOND] Continue current draft"
    if draft_text.strip()
    else "[RESPOND] Draft context-aware reply"
)
self._start_feature_request(
    AppCommand.FEATURE_4,
    request=request,
    capture_label=capture_label,
    status_text="Sending respond request to Jetson…",
)
```

Remove the previous `get_window_text()`, `processed_text`, and "No draft text detected" branches from `_on_respond()`.

- [ ] **Step 5: Run host RESPOND tests to verify GREEN**

Run:

```bash
./.venv/bin/python -m pytest tests/test_spark_panel_ui.py -k respond -q
```

Expected: all RESPOND host tests pass.

- [ ] **Step 6: Commit host behavior**

```bash
git add spark_app_v2.py tests/test_spark_panel_ui.py
git commit -m "feat: let respond run without focused draft text"
```

---

### Task 2: Jetson RESPOND Classifier

**Files:**
- Modify: `jetson/pico_llm_bridge.py`
- Modify: `tests/test_pico_llm_bridge.py`

- [ ] **Step 1: Write failing tests for classifier prompt and parser**

Add these tests to `BuildLlmRequestTests` in `tests/test_pico_llm_bridge.py`:

```python
def test_respond_classification_prompt_includes_active_context(self):
    self.db.on_context_new(_make_context_payload(text="Alex: can you send a quick update on the Jetson work?"))
    session = self.db.get_active_session()

    prompt = _build_respond_classification_prompt(session)

    self.assertIn("Classify whether the visible app context contains something to respond to.", prompt)
    self.assertIn("Active application:\nFirefox", prompt)
    self.assertIn("Window title:\nGitHub - SPARK", prompt)
    self.assertIn("Alex: can you send a quick update", prompt)


def test_parse_respond_classification_accepts_valid_json(self):
    parsed = _parse_respond_classification(
        '{"mode":"reply_to_visible_context","reply_target_summary":"Alex asked for an update.","confidence":"high"}',
        active_text="Alex asked for an update.",
    )

    self.assertEqual(parsed["mode"], "reply_to_visible_context")
    self.assertEqual(parsed["reply_target_summary"], "Alex asked for an update.")
    self.assertEqual(parsed["confidence"], "high")


def test_parse_respond_classification_falls_back_from_bad_json_with_visible_text(self):
    parsed = _parse_respond_classification("not json", active_text="Can you send an update?")

    self.assertEqual(parsed["mode"], "reply_to_visible_context")
    self.assertEqual(parsed["confidence"], "low")


def test_parse_respond_classification_falls_back_to_proactive_without_visible_text(self):
    parsed = _parse_respond_classification("not json", active_text="   ")

    self.assertEqual(parsed["mode"], "proactive_update")
    self.assertEqual(parsed["confidence"], "low")
```

Add imports near the top:

```python
from jetson.pico_llm_bridge import (
    _build_respond_classification_prompt,
    _parse_respond_classification,
)
```

- [ ] **Step 2: Run classifier tests to verify RED**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -k respond_classification -q
```

Expected: tests fail because classifier helpers do not exist.

- [ ] **Step 3: Implement classifier constants and parser**

Add near the other RESPOND constants in `jetson/pico_llm_bridge.py`:

```python
RESPOND_CLASSIFIER_SYSTEM_PROMPT = (
    "You classify whether the visible app context contains something the user should respond to. "
    "Return JSON only."
)

RESPOND_CLASSIFICATION_JSON_SCHEMA = {
    "name": "respond_classification",
    "schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["reply_to_visible_context", "proactive_update"],
            },
            "reply_target_summary": {"type": "string"},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
        },
        "required": ["mode", "reply_target_summary", "confidence"],
        "additionalProperties": False,
    },
}
```

Add helper functions near `_build_respond_prompt()`:

```python
def _build_respond_classification_prompt(anchor) -> str:
    return "\n".join(
        [
            "Classify whether the visible app context contains something to respond to.",
            "Choose reply_to_visible_context when the visible text includes a question, request, prompt, message, or thread that calls for a reply.",
            "Choose proactive_update when there is no visible thing to answer and RESPOND should draft a neutral recent-work update instead.",
            "Return JSON only.",
            "",
            "Active application:",
            (anchor["app_name"] or "").strip() or "(unknown app)",
            "Window title:",
            (anchor["window_title"] or "").strip() or "(untitled window)",
            "Tab title:",
            (anchor["tab_title"] or "").strip() or "(untitled tab)",
            "URL:",
            (anchor["url"] or "").strip() or "(no url)",
            "Visible text:",
            _trim_synthesis_text(anchor["text"] or ""),
        ]
    ).strip()


def _fallback_respond_classification(active_text: str) -> dict:
    active_text = (active_text or "").strip()
    return {
        "mode": "reply_to_visible_context" if active_text else "proactive_update",
        "reply_target_summary": active_text[:240],
        "confidence": "low",
    }


def _parse_respond_classification(raw: str, *, active_text: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        logger.warning("RESPOND classification was not valid JSON")
        return _fallback_respond_classification(active_text)

    if not isinstance(payload, dict):
        return _fallback_respond_classification(active_text)

    mode = payload.get("mode")
    confidence = payload.get("confidence")
    summary = payload.get("reply_target_summary")
    if mode not in {"reply_to_visible_context", "proactive_update"}:
        return _fallback_respond_classification(active_text)
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    if not isinstance(summary, str):
        summary = ""

    return {
        "mode": mode,
        "reply_target_summary": summary.strip(),
        "confidence": confidence,
    }
```

- [ ] **Step 4: Run classifier tests to verify GREEN**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -k respond_classification -q
```

Expected: classifier tests pass.

- [ ] **Step 5: Commit classifier helpers**

```bash
git add jetson/pico_llm_bridge.py tests/test_pico_llm_bridge.py
git commit -m "feat: add respond context classifier"
```

---

### Task 3: Jetson RESPOND Retrieval And Draft Prompt Builders

**Files:**
- Modify: `jetson/pico_llm_bridge.py`
- Modify: `tests/test_pico_llm_bridge.py`

- [ ] **Step 1: Write failing tests for four draft modes**

Add tests:

```python
def test_respond_draft_prompt_reply_with_existing_draft_includes_related_sources(self):
    self.db.on_context_new(_make_context_payload(text="Alex: can you send an update on RESPOND?", timestamp=3000.0))
    session = self.db.get_active_session()
    self.db.on_context_new(_make_context_payload(app_name="Codex", window_title="SPARK", text="Implemented Jetson prompt changes.", timestamp=2995.0))
    related = [
        row
        for row in self.db.get_recent_sessions(limit=5)
        if row["text"] == "Implemented Jetson prompt changes."
    ]
    classification = {
        "mode": "reply_to_visible_context",
        "reply_target_summary": "Alex asked for a RESPOND update.",
        "confidence": "high",
    }

    prompt = _build_respond_draft_prompt(
        session,
        classification,
        previous_user_input="Sure, quick update:",
        related_rows=related,
        window_minutes=30,
    )

    self.assertIn("Mode:\nreply_to_visible_context", prompt)
    self.assertIn("Previous written text in current text box:\nSure, quick update:", prompt)
    self.assertIn("Reply target summary:\nAlex asked for a RESPOND update.", prompt)
    self.assertIn("RELATED RECENT SOURCES", prompt)
    self.assertIn("Implemented Jetson prompt changes.", prompt)


def test_respond_draft_prompt_empty_reply_mode_writes_reply_to_visible_context(self):
    self.db.on_context_new(_make_context_payload(text="Alex: what did you finish?"))
    session = self.db.get_active_session()
    classification = {
        "mode": "reply_to_visible_context",
        "reply_target_summary": "Alex asked what was finished.",
        "confidence": "medium",
    }

    prompt = _build_respond_draft_prompt(
        session,
        classification,
        previous_user_input="",
        related_rows=[],
        window_minutes=30,
    )

    self.assertIn("Draft a short neutral reply to the visible message or request.", prompt)
    self.assertNotIn("RELATED RECENT SOURCES", prompt)


def test_respond_draft_prompt_empty_proactive_mode_uses_recent_sources(self):
    self.db.on_context_new(_make_context_payload(text="Blank compose window", timestamp=3000.0))
    session = self.db.get_active_session()
    self.db.on_context_new(_make_context_payload(app_name="Terminal", window_title="pytest", text="Ran Jetson tests.", timestamp=2995.0))
    recent = [
        row
        for row in self.db.get_recent_sessions(limit=5)
        if row["text"] == "Ran Jetson tests."
    ]
    classification = {
        "mode": "proactive_update",
        "reply_target_summary": "",
        "confidence": "high",
    }

    prompt = _build_respond_draft_prompt(
        session,
        classification,
        previous_user_input="",
        related_rows=recent,
        window_minutes=30,
    )

    self.assertIn("Draft a neutral short update or quick report about recent work.", prompt)
    self.assertIn("RECENT SOURCES", prompt)
    self.assertIn("Ran Jetson tests.", prompt)
```

- [ ] **Step 2: Write failing test for proactive empty recent-session collection**

```python
def test_collect_respond_recent_rows_uses_active_first_then_recent_deduped(self):
    self.db.on_context_new(_make_context_payload(app_name="Slack", window_title="Draft", text="Blank chat draft", timestamp=3000.0))
    anchor = self.db.get_active_session()
    self.db.on_context_new(_make_context_payload(app_name="Codex", window_title="Plan", text="Planned RESPOND redesign", timestamp=2990.0))
    self.db.on_context_new(_make_context_payload(app_name="Safari", window_title="Old", text="Old unrelated page", timestamp=100.0))

    rows = _collect_respond_recent_rows(self.db, anchor, window_minutes=30, limit=5)

    self.assertEqual(rows[0]["id"], anchor["id"])
    self.assertTrue(any(row["text"] == "Planned RESPOND redesign" for row in rows))
    self.assertFalse(any(row["text"] == "Old unrelated page" for row in rows))
```

- [ ] **Step 3: Run prompt/retrieval tests to verify RED**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -k "respond_draft_prompt or collect_respond_recent_rows" -q
```

Expected: tests fail because draft/recent helpers do not exist.

- [ ] **Step 4: Implement draft system prompt, prompt builder, and recent rows helper**

Add near RESPOND constants:

```python
RESPOND_DRAFT_SYSTEM_PROMPT = (
    "You draft concise response text for the user using the active app context and recent work context. "
    "Return only the message text. Keep it concise, generally 2-3 sentences."
)
```

Add helpers:

```python
def _collect_respond_recent_rows(db, anchor, *, window_minutes: int, limit: int = _SYNTHESIS_MAX_RELATED):
    cutoff = _synthesis_cutoff_timestamp(anchor, window_minutes=window_minutes)
    rows = db.get_recent_sessions_since(cutoff, limit=limit + 1, dedupe=True)
    result = []
    seen = set()

    anchor_key = anchor["context_key"]
    result.append(anchor)
    seen.add(anchor_key)

    for row in rows:
        key = row["context_key"]
        if key in seen:
            continue
        result.append(row)
        seen.add(key)
        if len(result) >= limit:
            break
    return result


def _append_respond_sources(lines: list[str], heading: str, rows) -> None:
    if not rows:
        return
    lines.extend(["", heading])
    for idx, row in enumerate(rows, start=1):
        lines.extend(["", f"Source {idx}:"])
        _append_synthesis_source(lines, row)


def _build_respond_draft_prompt(
    anchor,
    classification: dict,
    *,
    previous_user_input: str,
    related_rows,
    window_minutes: int,
) -> str:
    previous_user_input = (previous_user_input or "").strip()
    mode = classification.get("mode") or "proactive_update"
    reply_target_summary = (classification.get("reply_target_summary") or "").strip()

    if mode == "reply_to_visible_context" and previous_user_input:
        task = "Continue or refine the user's partial answer to the visible message or request."
    elif mode == "reply_to_visible_context":
        task = "Draft a short neutral reply to the visible message or request."
    elif previous_user_input:
        task = "Continue the user's standalone draft using recent work context."
    else:
        task = "Draft a neutral short update or quick report about recent work."

    lines = [
        task,
        "Return only the message text.",
        "Keep the response concise, generally 2-3 sentences.",
        "",
        "Mode:",
        mode,
        "Reply target summary:",
        reply_target_summary or "(none)",
        f"Recent work window: {int(window_minutes)} minutes",
        "",
        "Part 1 - Current Draft",
        "Current app:",
        (anchor["app_name"] or "").strip() or "(unknown app)",
        "Previous written text in current text box:",
        previous_user_input or "(empty)",
        "",
        "Part 2 - Context",
        "Window title:",
        (anchor["window_title"] or "").strip() or "(untitled window)",
        "Visible text:",
        _trim_synthesis_text(anchor["text"] or ""),
    ]

    heading = "RELATED RECENT SOURCES" if mode == "reply_to_visible_context" or previous_user_input else "RECENT SOURCES"
    _append_respond_sources(lines, heading, related_rows)
    return "\n".join(lines).strip()
```

- [ ] **Step 5: Run prompt/retrieval tests to verify GREEN**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -k "respond_draft_prompt or collect_respond_recent_rows" -q
```

Expected: tests pass.

- [ ] **Step 6: Commit prompt builders**

```bash
git add jetson/pico_llm_bridge.py tests/test_pico_llm_bridge.py
git commit -m "feat: build context-aware respond prompts"
```

---

### Task 4: Jetson RESPOND Handler Orchestration

**Files:**
- Modify: `jetson/pico_llm_bridge.py`
- Modify: `tests/test_pico_llm_bridge.py`

- [ ] **Step 1: Write failing handler test for classifier before draft**

Add to `ReformatHandlingTests`:

```python
def test_respond_selection_runs_classifier_before_draft_request(self):
    self.db.on_context_new(_make_context_payload(text="Alex: can you send an update?"))
    ser = mock.Mock()
    request = json.dumps({
        "command": "respond_selection",
        "previous_user_input": "",
    })
    calls = []

    def fake_blocking(endpoint, payload, timeout):
        calls.append(("blocking", payload["messages"][0]["content"], payload["messages"][1]["content"]))
        return '{"mode":"reply_to_visible_context","reply_target_summary":"Alex asked for an update.","confidence":"high"}'

    def fake_streaming(endpoint, payload, timeout):
        calls.append(("streaming", payload["messages"][0]["content"], payload["messages"][1]["content"]))
        yield "Here is the update."

    with mock.patch("jetson.pico_llm_bridge.query_llm_blocking", side_effect=fake_blocking):
        with mock.patch("jetson.pico_llm_bridge.query_llm_streaming", side_effect=fake_streaming):
            with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                    handle_summarize_request(ser, request, self._make_args(), db=self.db)

    self.assertEqual(calls[0][0], "blocking")
    self.assertIn("classify whether the visible app context", calls[0][1].lower())
    self.assertEqual(calls[1][0], "streaming")
    self.assertIn("draft concise response text", calls[1][1].lower())
```

- [ ] **Step 2: Write failing handler test for proactive empty mode using recent rows**

```python
def test_respond_selection_empty_proactive_mode_includes_recent_sessions(self):
    self.db.on_context_new(_make_context_payload(app_name="Slack", window_title="Blank", text="Blank compose", timestamp=3000.0))
    self.db.on_context_new(_make_context_payload(app_name="Terminal", window_title="pytest", text="Ran all Jetson bridge tests.", timestamp=2995.0))
    self.db.on_context_new(_make_context_payload(app_name="Slack", window_title="Blank", text="Blank compose", timestamp=3001.0))
    ser = mock.Mock()
    request = json.dumps({
        "command": "respond_selection",
        "previous_user_input": "",
    })
    draft_payloads = []

    with mock.patch(
        "jetson.pico_llm_bridge.query_llm_blocking",
        return_value='{"mode":"proactive_update","reply_target_summary":"","confidence":"high"}',
    ):
        with mock.patch("jetson.pico_llm_bridge.query_llm_streaming", return_value=iter(["Quick update."])) as streaming:
            with mock.patch("jetson.pico_llm_bridge._write_bridge_packet"):
                with mock.patch("jetson.pico_llm_bridge.time.sleep"):
                    handle_summarize_request(ser, request, self._make_args(), db=self.db)

    draft_payloads.append(streaming.call_args.args[1])
    self.assertIn("Ran all Jetson bridge tests.", draft_payloads[0]["messages"][1]["content"])
```

- [ ] **Step 3: Run handler tests to verify RED**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -k "respond_selection_runs_classifier or empty_proactive_mode" -q
```

Expected: tests fail because RESPOND still goes directly to one draft request.

- [ ] **Step 4: Implement `_prepare_respond_llm_request()`**

Add helper near `build_llm_request()`:

```python
def _prepare_respond_llm_request(request: dict, args, *, db) -> tuple[str, str, dict | None]:
    if db is None:
        return RESPOND_DRAFT_SYSTEM_PROMPT, "(no database available)", None
    anchor = db.get_active_session()
    if anchor is None:
        return RESPOND_DRAFT_SYSTEM_PROMPT, "(no active session)", None

    classification_prompt = _build_respond_classification_prompt(anchor)
    classifier_endpoint, classifier_payload = _prepare_respond_classification_http_request(
        args.llm_url,
        classification_prompt,
    )
    raw_classification = query_llm_blocking(classifier_endpoint, classifier_payload, args.timeout)
    classification = _parse_respond_classification(raw_classification, active_text=anchor["text"] or "")

    previous_user_input = (request.get("previous_user_input", "") or "").strip()
    window_minutes = int(request.get("window_minutes") or 30)
    cutoff = _synthesis_cutoff_timestamp(anchor, window_minutes=window_minutes)

    if classification["mode"] == "proactive_update" and not previous_user_input:
        related_rows = _collect_respond_recent_rows(db, anchor, window_minutes=window_minutes)
    else:
        keyword_prompt = _build_respond_keyword_prompt(anchor, classification, previous_user_input)
        keyword_endpoint, keyword_payload = _prepare_keyword_extraction_http_request(args.llm_url, keyword_prompt)
        try:
            keyword_raw = query_llm_blocking(keyword_endpoint, keyword_payload, args.timeout)
            keywords = _parse_synthesis_keywords(keyword_raw)
        except Exception:
            logger.exception("Keyword extraction request failed for respond_selection")
            keywords = []
        related_rows = _collect_synthesis_related_rows(
            db,
            anchor,
            keywords=keywords,
            cutoff_timestamp=cutoff,
        )

    prompt = _build_respond_draft_prompt(
        anchor,
        classification,
        previous_user_input=previous_user_input,
        related_rows=related_rows,
        window_minutes=window_minutes,
    )
    return RESPOND_DRAFT_SYSTEM_PROMPT, prompt, {
        "classification": classification,
        "classifier_request_payload": classifier_payload,
    }
```

Add the missing classification HTTP helper:

```python
def _prepare_respond_classification_http_request(url: str, prompt: str) -> tuple[str, dict]:
    endpoint = f"{url}/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": RESPOND_CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": RESPOND_CLASSIFICATION_JSON_SCHEMA,
        },
    }
    return endpoint, payload
```

Add keyword prompt helper:

```python
def _build_respond_keyword_prompt(anchor, classification: dict, previous_user_input: str) -> str:
    return "\n".join(
        [
            "Extract retrieval keywords for drafting a RESPOND message.",
            "Return topic-bearing entities, concepts, people, projects, apps, files, and concrete work items only.",
            f"Return 3 to {_SYNTHESIS_MAX_KEYWORDS} keywords.",
            "",
            "Reply mode:",
            classification.get("mode", "proactive_update"),
            "Reply target summary:",
            classification.get("reply_target_summary", "") or "(none)",
            "Previous written text:",
            (previous_user_input or "").strip() or "(empty)",
            "",
            "ANCHOR SOURCE",
        ]
    ) + "\n" + _build_synthesis_keyword_prompt(anchor)
```

- [ ] **Step 5: Wire `handle_summarize_request()` respond branch**

In `handle_summarize_request()`, replace the initial branch that computes `llm_system_prompt` and `llm_prompt` with this structure. The `synthesize_session` body is the current implementation moved under `elif command == "synthesize_session":`.

```python
respond_audit_metadata = None
if command == "respond_selection":
    llm_system_prompt, llm_prompt, respond_audit_metadata = _prepare_respond_llm_request(
        request,
        args,
        db=db,
    )
elif command == "synthesize_session":
    if db is None:
        llm_system_prompt, llm_prompt = SYNTHESIS_SYSTEM_PROMPT, "(no database available)"
    else:
        anchor_context_key = request.get("anchor_context_key")
        anchor = db.get_latest_session_for_context_key(anchor_context_key)
        if anchor is None:
            llm_system_prompt, llm_prompt = (
                SYNTHESIS_SYSTEM_PROMPT,
                _missing_synthesis_anchor_message(anchor_context_key),
            )
        else:
            window_minutes = int(request.get("window_minutes") or 30)
            cutoff = _synthesis_cutoff_timestamp(anchor, window_minutes=window_minutes)
            keyword_prompt = _build_synthesis_keyword_prompt(anchor)
            keyword_endpoint, keyword_payload = _prepare_keyword_extraction_http_request(
                args.llm_url,
                keyword_prompt,
            )
            try:
                keyword_raw = query_llm_blocking(keyword_endpoint, keyword_payload, args.timeout)
            except Exception:
                logger.exception("Keyword extraction request failed for synthesize_session")
                keyword_raw = ""
            keywords = _parse_synthesis_keywords(keyword_raw)
            request = dict(request)
            request["keywords"] = keywords
            llm_system_prompt, llm_prompt = build_llm_request(
                json.dumps(request),
                args.system_prompt,
                db=db,
                _request=request,
            )
else:
    llm_system_prompt, llm_prompt = build_llm_request(
        request_text,
        args.system_prompt,
        db=db,
        _request=request,
    )
```

Keep `respond_selection` in the existing structured-exclusion set:

```python
structured = args.structured and command not in {
    "reformat_selection",
    "respond_selection",
    "keyword_search",
    "synthesize_session",
}
```

- [ ] **Step 6: Extend audit logging for classifier call**

After the existing final draft `_append_llm_audit_record(...)` success block, add:

```python
if respond_audit_metadata and respond_audit_metadata.get("classifier_request_payload"):
    _append_llm_audit_record(
        args.audit_log,
        command="respond_classification",
        endpoint=f"{args.llm_url}/v1/chat/completions",
        request_payload=respond_audit_metadata["classifier_request_payload"],
        response_text=json.dumps(respond_audit_metadata.get("classification", {})),
    )
```

- [ ] **Step 7: Run handler tests to verify GREEN**

Run:

```bash
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -k "respond_selection" -q
```

Expected: all RESPOND Jetson handler tests pass.

- [ ] **Step 8: Commit handler orchestration**

```bash
git add jetson/pico_llm_bridge.py tests/test_pico_llm_bridge.py
git commit -m "feat: orchestrate context-aware respond on jetson"
```

---

### Task 5: Full Verification And Jetson Deployment

**Files:**
- Modify: no source changes expected unless tests reveal defects.

- [ ] **Step 1: Run focused host and Jetson suites**

Run:

```bash
./.venv/bin/python -m pytest tests/test_spark_panel_ui.py -k respond -q
./.venv/bin/python -m pytest tests/test_pico_llm_bridge.py -q
```

Expected:

```text
RESPOND host tests pass
All Jetson bridge tests pass
```

- [ ] **Step 2: Run broader regression slice**

Run:

```bash
./.venv/bin/python -m pytest tests/test_summarize_stream.py tests/test_pico_bridge_app.py tests/test_spark_panel_ui.py tests/test_pico_llm_bridge.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Sync Jetson bridge bundle and restart bridge**

Run:

```bash
bash -lc 'source ./setup_spark_macos.sh; assert_host_tooling_ready; sync_jetson_bridge_bundle; restart_jetson_bridge'
```

Expected output includes:

```text
Jetson deploy:           Synced 6 file(s) to sidac@192.168.55.1:/mnt/usb_drive/demo/pico_bridge/
bridge restart status:
one process line containing pico_llm_bridge.py --port /dev/ttyTHS0
```

- [ ] **Step 4: Verify deployed Jetson source contains new RESPOND helpers**

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 sidac@192.168.55.1 "grep -n 'RESPOND_CLASSIFIER_SYSTEM_PROMPT\\|_build_respond_draft_prompt\\|reply_to_visible_context' /mnt/usb_drive/demo/pico_bridge/pico_llm_bridge.py"
```

Expected: grep prints matching lines from the deployed bridge.

- [ ] **Step 5: Commit final verification notes if code changed during verification**

If Task 5 required source fixes, commit them:

```bash
git add jetson/pico_llm_bridge.py tests/test_pico_llm_bridge.py spark_app_v2.py tests/test_spark_panel_ui.py
git commit -m "test: verify context-aware respond flow"
```

If no files changed, do not create an empty commit.

---

## Self-Review

- Spec coverage: the plan covers host empty-draft behavior, focused-only draft extraction, Jetson classification, four draft cases, 30-minute recent sessions, keyword retrieval, proactive update fallback, plain-text final responses, auditability, and live Jetson deployment.
- Placeholder scan: no `TBD`, `TODO`, or unspecified test steps remain in this plan.
- Type consistency: all new helper names use the `respond` prefix and live in `jetson/pico_llm_bridge.py`; host changes stay inside `_on_respond()`.
