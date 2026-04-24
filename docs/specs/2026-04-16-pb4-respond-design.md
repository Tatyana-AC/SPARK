# PB4 Respond Design

## Goal

Implement the `RESPOND` action on physical pushbutton 4 so the SPARK stack can generate a continuation based on the active app context and the user's most recent input text.

## Scope

- Add a host-side request builder for a new `respond_selection` command.
- Trigger that request from the SPARK panel when PB4 is pressed.
- Use the current text selection as the preferred prior user input.
- Fall back to SPARK's last captured/processed text when no selection is available.
- Build the LLM prompt on Jetson from the active DB-backed context plus the prior user input text.

## Non-Goals

- No new UART packet type.
- No new HID protocol command beyond the existing `FEATURE_4` application command.
- No clipboard write-back for the generated response.

## Design

### Host behavior

`spark_app_v2.py` will add `_on_respond()` alongside `_on_reformat()`.

Behavior:

1. Reject the action when the active window fails the privacy guard.
2. Read `AccessibilityManager.get_focused_element_text()` to capture the in-progress draft automatically.
3. If the focused element text is empty, fall back to `SparkPanel.processed_text`.
4. If both are empty, surface a user-facing error and do not send a request.
5. Send a new request payload over Raw HID using `AppCommand.FEATURE_4`.

PB4 hardware presses will be surfaced through the existing Pico debug-message path, matching the host-triggered style already used for PB2 reformat.

### Request shape

The host request payload will be JSON:

```json
{
  "command": "respond_selection",
  "previous_user_input": "..."
}
```

The input text is trimmed and truncated to the existing upload budget used by other inline text requests.

### Jetson behavior

`jetson/pico_llm_bridge.py` will recognize `respond_selection`.

It will read the active DB session, then build a prompt that includes:

- active application
- window title
- visible text from the active session
- previous user input text from the host payload

The prompt will ask the model to generate only the continuation/response text, with no labels or JSON envelope.

Structured output stays disabled for this mode, matching `reformat_selection`.

### Pico behavior

No new wire contract is needed. `FEATURE_4` is already valid in the upload protocol. PB4 will be handled through the existing debug event stream and the host will decide when to start the new round-trip request.

## Testing

- `tests/test_summarize_stream.py`
  - verify the new request payload shape
  - verify trimming/truncation behavior
- `tests/test_spark_panel_ui.py`
  - verify PB4 post-press triggers `_on_respond()`
  - verify PB4 is ignored while another request is in flight
  - verify `_on_respond()` prefers selection and falls back to processed text
  - verify empty input fails fast
  - verify `FEATURE_4` is sent through `_start_feature_request()`
- `tests/test_pico_llm_bridge.py`
  - verify `respond_selection` prompt generation
  - verify it uses active DB context
  - verify no-context handling returns an error path instead of querying the LLM
