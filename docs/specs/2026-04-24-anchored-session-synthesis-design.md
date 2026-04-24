# Anchored Session Synthesis Design

## User Requirements

- The synthesis feature should summarize the user's current work session instead of only summarizing the current active app: user's initial request.
- The active app should be the anchor topic for synthesis: user confirmed after approach discussion.
- The first implementation should use a fixed 30-minute recent-context window: user chose fixed 30 minutes.
- The system should consider relevant context from other recent apps when those apps relate to the active app's topic: user's Boston Tea Party Wikipedia plus Notes example.
- A relevant workflow is to summarize or inspect the current active app, extract keywords, and use those keywords to search other recent apps: user suggested this as a possible approach.
- The implementation should use a new internal command for session synthesis instead of overloading the existing active-app summarize command: user agreed.
- Physical Push Button 1 must trigger the new session synthesis behavior, not active-app-only summary: user specified PB1 behavior.
- Active-app-only `summarize` should remain available in code and protocol paths, but should not be exposed anywhere in the user-facing UI: user specified final UI behavior.

## Agent Design Decisions

- Add a new JSON command, `synthesize_session`, with a fixed `window_minutes` value of `30`: serves the new synthesis behavior and PB1 requirement. This keeps `summarize` as a lower-level active-session primitive.
- Treat the active app as the required anchor source and recent app contexts as optional supporting sources: serves the active-anchor requirement and avoids unrelated recent-window summaries.
- Use a hybrid relevance pass: extract anchor keywords/entities, then combine keyword matches with title/URL/text overlap and recency scoring: serves the user's keyword-search idea while reducing misses from pure exact matching.
- Query and rank recent context on Jetson, where the durable session database already lives: serves session synthesis without adding a host-local persistence layer.
- Keep the existing Raw HID upload and Pico-to-Jetson transport shape: serves the PB1 requirement without introducing a new packet format.
- Keep `summarize` tests and code paths as internal/debug coverage while changing visible Synthesis and PB1 tests to assert `synthesize_session`: serves the user's requirement to keep code but remove user-facing active-only summary.

## Goal

Make SPARK's Synthesis action produce an anchored summary of the user's current work session. The active app is the anchor topic, and SPARK uses related context from the last fixed 30 minutes of recent app sessions when those sessions help explain or extend the active work.

For example, if the active app is a Wikipedia page about the Boston Tea Party and a recent Notes window contains Boston Tea Party notes, Synthesis should combine both sources into one grounded synthesis.

## Scope

- Add a new internal command:

```json
{
  "command": "synthesize_session",
  "window_minutes": 30
}
```

- Route the visible Synthesis action through `synthesize_session`.
- Route physical PB1 through `synthesize_session`.
- Keep `summarize` as an internal active-session command with existing behavior.
- Query Jetson DB for sessions observed in the last 30 minutes.
- Rank recent sessions against the active app anchor.
- Build a multi-source synthesis prompt from the active app plus the strongest related recent sessions.
- Update user-facing labels from active-window summary language to Synthesis/session language.

## Non-Goals

- No configurable time window in v1.
- No embeddings or vector database in v1.
- No new HID, CDC, or UART packet type.
- No user-facing active-app-only summarize button or menu item.
- No attempt to recover content from apps that were never captured by the existing polling/accessibility pipeline.

## Current Behavior

The current host-side summarize builder sends a lightweight command:

```json
{"command": "summarize"}
```

Jetson handles that command by reading only the active DB session and building a prompt that asks for the current active application context. That behavior is useful as a primitive, but it does not match the Synthesis product vision.

PB1 also still maps to active-app summary semantics through existing Pico/Jetson paths. That must change so PB1 means Synthesis.

## Proposed Behavior

When Synthesis is triggered from the UI or PB1:

1. Host sends `{"command":"synthesize_session","window_minutes":30}` through the existing feature request path.
2. Pico forwards the request through the existing Jetson transport path.
3. Jetson loads the active DB session.
4. Jetson loads recent sessions from the fixed last 30 minutes.
5. Jetson builds an anchor brief from the active session.
6. Jetson ranks recent sessions against the anchor.
7. Jetson keeps the strongest related sessions, deduped by context key.
8. Jetson builds a synthesis prompt that clearly labels anchor and related sources.
9. Jetson streams the LLM result back through the existing response path.

If no related recent sessions clear the threshold, the response should say that the synthesis is based only on the active app.

## Host Behavior

Add a request builder for session synthesis, likely alongside the existing request builders:

```python
build_synthesize_session_request(window_minutes: int = 30)
```

The visible Synthesis action should use this builder. The old active-app-only summarize command should not be reachable from a user-facing button.

The host-side PB1 debug event path should continue to start response polling for `button:1`, but the request being processed for PB1 should be the new synthesis command.

User-facing status and capture labels should use Synthesis/session language, not "Summarize active context" or "Summarize Window".

## Pico Behavior

PB1 should use the new fixed command text:

```json
{"command":"synthesize_session","window_minutes":30}
```

The existing `FEATURE_1` forwarding behavior can remain transport-generic. The key semantic change is the command payload associated with PB1/Synthesis.

Because this affects Pico deploy/runtime support, implementation must deploy the updated Pico runtime to the mounted `CIRCUITPY` board before the work is called complete, unless the board is unavailable or the user explicitly skips deployment.

## Jetson Behavior

Add command handling for `synthesize_session` in the bridge prompt builder.

Database additions:

- Add a method to fetch sessions observed since a cutoff timestamp, ordered newest-first.
- Reuse `host_observed_at` where present and fall back to `updated_at`.
- Deduplicate candidate sessions by `context_key`, keeping the newest useful row.

Relevance ranking should start deterministic:

- Always include the active session as the anchor.
- Exclude the active session from related candidates after anchor selection.
- Exclude empty or metadata-only rows unless the title/URL is strongly useful.
- Score related candidates by keyword/entity matches, title/URL overlap, text overlap, and recency.
- Cap related sources to a small number, such as 3 to 5, to keep the prompt focused.

The existing `summarize` command should keep its current behavior of summarizing only the active session.

## Anchor Brief

The anchor brief may be produced with a short LLM pass or a local extractor. The first implementation can choose the simplest reliable option.

Suggested fields:

- topic
- entities
- keywords
- likely user intent
- search queries

The anchor brief should be grounded in:

- active app name
- active window title
- active URL when available
- active captured text

## Synthesis Prompt

The final prompt should distinguish anchor and related sources:

```text
The active app is the anchor. Summarize it first, then use related recent context from the last 30 minutes only when it helps explain or extend the active work.
Do not include unrelated recent windows.
If no related context is found, say that the synthesis is based only on the active app.

ANCHOR SOURCE
...

RELATED RECENT SOURCES
...
```

Expected output:

- current work topic
- synthesis across the anchor and related sources
- related context used
- likely next useful step

## Privacy And Safety

The existing host privacy guard prevents unsafe active windows from being captured or sent. Jetson synthesis should also avoid including rows whose captured text is empty or known to be protected.

If the active session is unavailable, Synthesis should follow the existing no-context error style rather than hallucinating a session.

If the active app has weak extraction, Jetson can use title and URL as the anchor, but the output should make clear that little visible text was available.

## Testing

- Request builder tests:
  - `build_synthesize_session_request()` emits `synthesize_session`.
  - default `window_minutes` is `30`.
  - `build_summarize_command()` still emits `summarize`.

- Host/UI tests:
  - visible Synthesis action sends `synthesize_session`.
  - no visible UI path sends active-app-only `summarize`.
  - PB1 debug path remains wired to response polling.
  - labels and status strings use Synthesis/session wording.

- Pico tests:
  - PB1 command payload is `synthesize_session` with `window_minutes: 30`.
  - `FEATURE_1` forwarding remains transport-compatible.

- Jetson DB tests:
  - recent-session query returns only rows from the last 30 minutes.
  - ordering uses host-observed recency.
  - dedupe keeps the newest row per context key.

- Jetson prompt tests:
  - `summarize` still builds active-session prompt.
  - `synthesize_session` builds an anchored multi-source prompt.
  - unrelated recent sessions are excluded.
  - no related sessions falls back to anchor-only synthesis.
  - no active session returns the existing no-context path.

- End-to-end tests:
  - active Wikipedia page plus related Notes row produces a prompt containing both.
  - active Wikipedia page plus unrelated recent Settings row excludes Settings.
  - PB1 path produces the same synthesis command semantics as the visible Synthesis action.

## Documentation Updates

Update active docs that describe PB1 or `Summarize Window` so they reflect:

- PB1 = Synthesis
- Synthesis = active-app-anchored 30-minute session synthesis
- `summarize` remains an internal active-session command, not a user-facing UI action
