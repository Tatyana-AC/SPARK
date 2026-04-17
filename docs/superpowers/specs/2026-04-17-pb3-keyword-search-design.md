# PB3 Keyword Search Design

## Goal

Implement a `KEYWORD SEARCH` action on physical pushbutton 3 so SPARK can search Jetson's recent context history by selected text and summarize the 3 most recent matches.

## Scope

- Add a host-side request builder for a new `keyword_search` command.
- Trigger that request from the SPARK panel only when text is actively selected.
- Query Jetson DB for the 3 most recent rows whose `text` contains the selected text.
- Summarize those matches through the existing Jetson LLM path.
- Show the final output in `RELEASE OUTPUT` and copy it to the clipboard.

## Non-Goals

- No fallback to focused text, window text, or processed text.
- No new USB/HID or UART packet format.
- No separate raw-results UI for the matching rows.

## Design

### Host behavior

`spark_app_v2.py` will add `_on_keyword_search()` alongside `_on_reformat()` and `_on_respond()`.

Behavior:

1. Reject the action when the active window fails the privacy guard.
2. Read `AccessibilityManager.get_selected_text()`.
3. If the selection is empty, surface a user-facing error and do not send a request.
4. Send a new request payload over Raw HID using `AppCommand.FEATURE_3`.
5. On success, update `RELEASE OUTPUT` and copy the final text to the clipboard.

PB3 hardware presses will be surfaced through the existing Pico debug-message path, matching PB2 and PB4.

### Request shape

The host request payload will be JSON:

```json
{
  "command": "keyword_search",
  "selected_text": "irrational"
}
```

### Jetson behavior

`jetson/pico_llm_bridge.py` will recognize `keyword_search` and query Jetson DB for the 3 most recent matching entries.

Prompt inputs:

- selected keyword text from host
- the 3 matched session rows, ordered newest-first

Prompt expectations:

- summarize only those matched entries
- stay grounded in the matched text
- return plain text, not structured JSON

If there are no matches, Jetson should skip the LLM call and return:

```text
No recent entries matched "<keyword>".
```

### Pico behavior

`pico/bridge_app.py` will forward `FEATURE_3` through the same Jetson transport path already used for `FEATURE_2` and `FEATURE_4`.

## Testing

- request-builder tests for `build_keyword_search_request()`
- panel tests for selection-only behavior, PB3 debug dispatch, feature-specific status text, and clipboard write-back
- Jetson bridge tests for matched-entry prompt construction, no-match behavior, and structured-mode bypass
- Pico bridge tests for `FEATURE_3` forwarding

