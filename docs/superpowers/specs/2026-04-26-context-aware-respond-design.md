# Context-Aware RESPOND Design

## User Requirements

- RESPOND is usually used inside chat-style apps such as Slack or iMessage.
- RESPOND should support replying to previous visible messages or proactively sending an update based on the recent work session.
- The feature should not branch only on whether the current text box has text.
- Even when the text box is empty, the visible app context may contain a question, request, or relevant message that should receive a smart response.
- If the visible app context has something to answer, RESPOND should draft a reply to that context.
- If there is no visible thing to answer, RESPOND should draft a neutral proactive update or quick report about recent work.
- If the user has already typed text in the current text box, RESPOND should continue or refine that draft.
- RESPOND should use the current app/session as the starting point or anchor.
- RESPOND should also use recent app sessions, not only the current active app session, because chat windows often do not contain the full work context.
- Recent context should use the same fixed 30-minute window as Synthesis.
- When there is a topic anchor, RESPOND should use keyword retrieval like Synthesis.
- Outputs should be neutral, concise, and generally 2-3 sentences.
- The preferred implementation is a two-pass Jetson RESPOND flow: classify visible app context first, then draft.

## Agent Design Decisions

- Keep one user-facing action and one transport command, `respond_selection`, to avoid changing Pico semantics.
- Move the main behavioral decision to Jetson because Jetson owns the persisted session database and has the richest context.
- Always classify the active visible app context, regardless of whether the current text box contains a draft.
- Use four drafting cases after classification:
  - visible thing to answer plus user draft exists
  - visible thing to answer plus no user draft
  - no visible thing to answer plus user draft exists
  - no visible thing to answer plus no user draft
- Use strict JSON for the classification pass so prompt behavior is easier to test and debug.
- Keep the final draft response as plain text, not structured JSON.
- Audit both classifier and draft LLM calls where practical.
- Change host RESPOND draft detection to use focused text only. Do not fall back to full window text as `previous_user_input`, because chat history can be mistaken for text typed by the user.

## Current State

The current host flow in `spark_app_v2.py` fails RESPOND when no draft text is detected. It also falls back from focused text to full window text and then to `processed_text`. That fallback is risky for chat apps, because the visible conversation can be sent as `previous_user_input`.

The current Jetson flow in `jetson/pico_llm_bridge.py` treats every `respond_selection` request as a continuation task. It pulls `db.get_active_session()`, builds a prompt from the active session plus `previous_user_input`, and sends one final LLM request.

Synthesis already has useful building blocks that RESPOND should reuse:

- fixed 30-minute session window
- cutoff based on stored session timestamps, not Jetson wall clock
- keyword extraction
- recent matching session retrieval
- bounded related source prompts

## Proposed Behavior

RESPOND remains a single action from the user's perspective. Internally, Jetson runs a two-pass flow.

### Pass 1: Classify Visible Context

The classifier receives the active session as the anchor. It decides whether the visible app context contains a message, question, request, thread, or other item worth responding to.

The classifier returns JSON:

```json
{
  "mode": "reply_to_visible_context",
  "reply_target_summary": "A short summary of the visible thing to answer.",
  "confidence": "high"
}
```

Allowed `mode` values:

- `reply_to_visible_context`
- `proactive_update`

Allowed `confidence` values:

- `high`
- `medium`
- `low`

### Pass 2: Draft Response

The draft pass combines classifier output with current text box state.

If the classifier chooses `reply_to_visible_context` and `previous_user_input` is non-empty, the model continues or refines the user's partial answer. It should use the visible ask and recent related work context.

If the classifier chooses `reply_to_visible_context` and `previous_user_input` is empty, the model drafts a short neutral reply to the visible ask or message.

If the classifier chooses `proactive_update` and `previous_user_input` is non-empty, the model continues the user's standalone draft using recent work context.

If the classifier chooses `proactive_update` and `previous_user_input` is empty, the model drafts a neutral short update or quick report about recent work.

All cases return only the message text. The output should generally be 2-3 sentences.

## Retrieval Strategy

The current active session is always included as the anchor.

For `reply_to_visible_context`, Jetson extracts retrieval keywords from:

- visible active session text
- window title and app metadata
- classifier `reply_target_summary`
- `previous_user_input`, if present

It then retrieves related recent sessions from the last 30 minutes using the Synthesis-style matching and ranking path.

For `proactive_update` with a non-empty draft, Jetson extracts keywords from:

- the user's draft
- active session text and metadata

It retrieves related recent sessions from the same fixed 30-minute window.

For `proactive_update` with no draft, Jetson should not depend on keyword search. It should include a bounded deduped list of recent sessions from the last 30 minutes, with the active session first when available, then newest useful sessions.

If keyword extraction fails or returns no matches, Jetson still drafts from the active session and omits related sources.

## Host And Pico Changes

Pico stays transport-only. It still forwards `FEATURE_4` / `respond_selection` to Jetson.

The host changes RESPOND draft extraction:

- read focused element text
- if focused text is non-empty, send it as `previous_user_input`
- if focused text is empty or unavailable, send `previous_user_input` as an empty string
- do not use full window text as the draft fallback
- do not fail just because focused text is empty

The host may use different capture labels for empty and non-empty focused text, but it should not decide the response mode. Jetson classification owns that decision.

## Prompt Structure

Jetson should introduce separate prompt helpers:

- `RESPOND_CLASSIFIER_SYSTEM_PROMPT`
- `_build_respond_classification_prompt(anchor_session)`
- `RESPOND_DRAFT_SYSTEM_PROMPT`
- `_build_respond_draft_prompt(...)`

The classifier prompt asks for strict JSON and does not produce user-visible text.

The draft prompt includes:

- classification result
- active app/session anchor
- previous written text, if present
- related recent sources, if any
- recent window length
- instruction to return only message text
- soft 2-3 sentence guidance

The final draft pass must not request structured JSON output.

## Error Handling

If Jetson has no database or no active session, RESPOND returns:

```text
[ERROR] Cannot respond without active context.
```

If active context exists but no related sessions are found, RESPOND still drafts from the active session.

If classifier JSON is malformed, Jetson logs the parse failure and falls back deterministically:

- if active visible text is non-empty, use `reply_to_visible_context`
- otherwise use `proactive_update`

If keyword extraction fails, Jetson logs the error and drafts without related sources.

If the classifier or final draft HTTP request fails, Jetson returns `[ERROR] ...` through the existing error packet path.

## Testing Plan

Host tests:

- RESPOND sends empty `previous_user_input` when focused text is empty.
- RESPOND uses focused text when present.
- RESPOND does not use full window text as `previous_user_input`.
- RESPOND no longer fails fast on empty focused text.

Jetson request-building tests:

- classifier prompt includes active session context.
- classifier JSON parser accepts valid modes and confidence values.
- malformed classifier JSON falls back deterministically.
- non-empty draft plus reply mode builds a continue-answer prompt.
- empty draft plus reply mode builds a reply-to-visible-context prompt.
- non-empty draft plus proactive mode builds a standalone continuation prompt.
- empty draft plus proactive mode builds a neutral recent-work update prompt.
- reply mode uses keyword retrieval over recent 30-minute sessions.
- proactive empty mode uses recent deduped sessions without requiring keywords.
- no keyword matches omit related sources and still draft.
- final RESPOND draft still ignores structured JSON mode.

Handler tests:

- no active session sends `[ERROR] Cannot respond without active context.` and skips LLM calls.
- classifier pass runs before draft pass.
- audit logging records classifier and final draft calls where possible.

## Rollout Notes

The repo copy of `jetson/pico_llm_bridge.py` is deployable to the Jetson bridge folder. After implementation, the bridge bundle must be synced and the live Jetson bridge restarted before claiming the hardware path is updated.

The expected deploy target remains:

```text
/mnt/usb_drive/demo/pico_bridge
```
