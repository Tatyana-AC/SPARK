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
- The synthesis request should include the current active app identity explicitly so Jetson does not race on "whatever is active now": user clarified after live debugging.
- `context_key` alone is enough as the anchor identifier; if multiple stored sessions share that key, Jetson should use the most recent one: user selected this identifier strategy.

## Agent Design Decisions

- Add a new JSON command, `synthesize_session`, with a fixed `window_minutes` value of `30`: serves the new synthesis behavior and PB1 requirement. This keeps `summarize` as a lower-level active-session primitive.
- Treat the active app as the required anchor source and recent app contexts as optional supporting sources: serves the active-anchor requirement and avoids unrelated recent-window summaries.
- Use a two-round synthesis flow: first extract anchor keywords/entities with abbreviation expansion from the anchor app only, then query Jetson DB with those keywords and synthesize from the anchor plus the retrieved contexts: serves the user's keyword-search idea directly.
- Query and rank recent context on Jetson, where the durable session database already lives: serves session synthesis without adding a host-local persistence layer.
- Keep the existing Raw HID upload and Pico-to-Jetson transport shape for host-originated synthesis requests: serves the PB1 requirement without introducing a new packet format.
- Compute `anchor_context_key` on the host using the same rule Jetson already uses (`app_name|url` when URL exists, otherwise `app_name|window_title`): serves the race-free anchor requirement while keeping Jetson as the source of truth for stored context.
- Resolve synthesis anchors on Jetson by exact `context_key` match, newest-first by `COALESCE(host_observed_at, updated_at) DESC, id DESC`: serves the user's "most recent matching instance" requirement.
- Make PB1 host-mediated instead of Pico-fixed for synthesis semantics: serves the PB1 requirement while ensuring PB1 and the visible Synthesis action use the same anchor selection rule.
- Keep `summarize` tests and code paths as internal/debug coverage while changing visible Synthesis and PB1 tests to assert `synthesize_session`: serves the user's requirement to keep code but remove user-facing active-only summary.

## Goal

Make SPARK's Synthesis action produce an anchored summary of the user's current work session. The active app is the anchor topic, and SPARK uses related context from the last fixed 30 minutes of recent app sessions when those sessions help explain or extend the active work.

For example, if the active app is a Wikipedia page about the Boston Tea Party and a recent Notes window contains Boston Tea Party notes, Synthesis should combine both sources into one grounded synthesis.

## Scope

- Add a new internal command:

```json
{
  "command": "synthesize_session",
  "window_minutes": 30,
  "anchor_context_key": "Google Chrome|https://en.wikipedia.org/wiki/Boston_Tea_Party"
}
```

- Route the visible Synthesis action through `synthesize_session`.
- Route physical PB1 through a host-mediated `synthesize_session` request carrying `anchor_context_key`.
- Keep `summarize` as an internal active-session command with existing behavior.
- Query Jetson DB for sessions observed in the last 30 minutes.
- Resolve the anchor by `anchor_context_key`, taking the most recent matching stored session.
- Run a first LLM pass on the resolved anchor to extract retrieval keywords.
- Query Jetson DB for recent sessions matching those extracted keywords.
- Build a multi-source synthesis prompt from the active app plus the retrieved related sessions.
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

1. Host inspects the currently active app and computes `anchor_context_key` using the same rule as Jetson.
2. Host sends `{"command":"synthesize_session","window_minutes":30,"anchor_context_key":"..."}` through the existing feature request path.
3. Pico forwards the request through the existing Jetson transport path.
4. Jetson resolves the anchor by exact `context_key` match, ordered newest-first.
5. Jetson loads recent sessions from the fixed last 30 minutes.
6. Jetson runs a first LLM pass on the anchor to extract keyword/entity queries, including abbreviation expansion when useful.
7. Jetson queries recent stored sessions for those extracted keywords and dedupes the retrieved matches by context key.
8. Jetson builds a synthesis prompt that clearly labels anchor and related sources.
9. Jetson runs a second LLM pass to synthesize from the anchor plus the retrieved contexts.
10. Jetson streams the final LLM result back through the existing response path.

If no related recent sessions clear the threshold, the response should say that the synthesis is based only on the active app.

If no stored session matches `anchor_context_key`, Jetson should return an explicit no-anchor warning or error. It must not silently fall back to the currently active session.

## Host Behavior

Add a request builder for session synthesis, likely alongside the existing request builders:

```python
build_context_key(app_name: str, window_title: str, url: str | None) -> str
build_synthesize_session_request(anchor_context_key: str, window_minutes: int = 30)
```

The visible Synthesis action should:

- inspect the current active app
- compute `anchor_context_key`
- fail explicitly if there is not enough active-app data to build that key
- send the enriched `synthesize_session` request

The old active-app-only summarize command should not be reachable from a user-facing button.

The host-side PB1 debug event path should become a true synthesis trigger, not just response polling for a Pico-originated synthesis request. The host should react to `button:1` by computing the same `anchor_context_key` and sending the same `synthesize_session` request as the visible Synthesis action.

User-facing status and capture labels should use Synthesis/session language, not "Summarize active context" or "Summarize Window".

## Pico Behavior

PB1 should no longer own a fixed synthesis command payload. Instead:

- PB1 should continue to surface a host-visible button event
- the host should turn that button event into the enriched `synthesize_session` request
- the existing `FEATURE_1` forwarding path remains the transport path for the resulting host-originated request

This makes PB1 and the visible Synthesis action semantically identical and removes the active-session race that appears when Jetson tries to infer the anchor later.

Because this affects Pico deploy/runtime support, implementation must deploy the updated Pico runtime to the mounted `CIRCUITPY` board before the work is called complete, unless the board is unavailable or the user explicitly skips deployment.

## Jetson Behavior

Add command handling for `synthesize_session` in the bridge prompt builder.

Database additions:

- Add a method to fetch sessions observed since a cutoff timestamp, ordered newest-first.
- Add a method to fetch the newest session row for a given `context_key`.
- Reuse `host_observed_at` where present and fall back to `updated_at`.
- Deduplicate candidate sessions by `context_key`, keeping the newest useful row.

Related-context retrieval should start deterministic:

- Always include the request-resolved anchor session as the anchor.
- Exclude the anchor session from related candidates after anchor selection.
- Use a first-pass keyword extraction prompt on the anchor only.
- Expand abbreviations when useful, for example `EIC` and `East India Company`.
- Query recent Jetson sessions with those extracted keywords using the existing keyword-search style text match.
- Deduplicate retrieved related candidates by `context_key`.
- Cap related sources to a small number, such as 3 to 5, to keep the prompt focused.

The existing `summarize` command should keep its current behavior of summarizing only the active session.

## Round 1 Retrieval Keywords

The first synthesis round should use the anchor app only and return a concise keyword list for retrieval.

Expected keyword behavior:

- include specific entities, concepts, laws, organizations, and events
- expand abbreviations into both forms when useful
- avoid generic UI/browser terms
- avoid broad filler words that would match unrelated technical pages

The keyword extraction prompt should be grounded in:

- active app name
- active window title
- active URL when available
- active captured text
- the request-provided `anchor_context_key`, used only to resolve the anchor row

## Synthesis Prompt

The second-round prompt should distinguish anchor and related sources:

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

If `anchor_context_key` is missing, host should fail before sending a synthesis request.

If `anchor_context_key` does not resolve to any stored session on Jetson, synthesis should follow the existing no-context error style rather than hallucinating a session or falling back to a different active session.

If the active app has weak extraction, Jetson can use title and URL as the anchor, but the output should make clear that little visible text was available.

## Testing

- Request builder tests:
  - `build_context_key()` matches Jetson's current `context_key` rule exactly.
  - `build_synthesize_session_request(anchor_context_key=...)` emits `synthesize_session` with the anchor key.
  - default `window_minutes` is `30`.
  - empty anchor key is rejected.
  - `build_summarize_command()` still emits `summarize`.

- Host/UI tests:
  - visible Synthesis action sends `synthesize_session` with `anchor_context_key`.
  - no visible UI path sends active-app-only `summarize`.
  - PB1 host-handled path sends the same request shape as the visible Synthesis action.
  - labels and status strings use Synthesis/session wording.

- Pico tests:
  - PB1 still emits the host-visible trigger path needed for synthesis.
  - `FEATURE_1` forwarding remains transport-compatible for host-originated synthesis requests.

- Jetson DB tests:
  - recent-session query returns only rows from the last 30 minutes.
  - ordering uses host-observed recency.
  - dedupe keeps the newest row per context key.
  - exact `context_key` lookup returns the most recent matching row.

- Jetson prompt tests:
  - `summarize` still builds active-session prompt.
  - `synthesize_session` resolves the anchor by `anchor_context_key`.
  - if multiple rows share that key, the newest one wins.
  - unrelated recent sessions are excluded.
  - no related sessions falls back to anchor-only synthesis.
  - no matching anchor row returns the existing no-context path.

## Documentation Updates

Update active docs that describe PB1 or `Summarize Window` so they reflect:

- PB1 = Synthesis
- Synthesis = active-app-anchored 30-minute session synthesis
- the synthesis request carries `anchor_context_key`
- Jetson resolves the anchor as the most recent matching stored session
- `summarize` remains an internal active-session command, not a user-facing UI action
