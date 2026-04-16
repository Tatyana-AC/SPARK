# Windows Browser Extraction Design

## Summary

Improve Windows browser context capture in the active `spark_app_v2.py` path by combining three layers:

1. more reliable active-tab URL extraction for Chrome/Edge/Brave
2. a best-effort live-tab text path for browser pages where Windows can expose page content directly
3. a cleaner fallback path that filters browser UI noise when live extraction is unavailable

The design keeps the existing poll-loop contract, tracker schema, and host-to-Pico/Jetson payload format unchanged.

## Context

The current browser capture flow has two separable parts:

- browser metadata: `host_pc/browser.py` and `host_pc/browser_windows.py` try to recover tab title and URL
- browser text: `host_pc/web_content.py` extracts page text

The macOS path is stronger because it can:

- read browser tab metadata directly with AppleScript
- inject JavaScript into the live front tab for Google Docs, Google Sheets, and general pages
- fall back to HTTP extraction when a normal external page is fetchable

The Windows path is currently much weaker:

- URL extraction relies on UI Automation heuristics against the address bar
- browser text extraction only performs HTTP extraction when a fetchable external URL is available
- if browser extraction yields no usable text, the poll loop falls back to accessibility text, which can be polluted by bookmark bars, extension buttons, plugin UI, and browser chrome

The dropped `spark_scraper_integration/` folder is useful as a reference for product intent and fallback structure, but it is not the active runtime path and should not be merged wholesale.

## Problem Statement

On Windows, browser context capture is not reliable enough for real browsing workflows. URLs are often missing, which prevents the extractor from using page-aware logic. When URL extraction fails, the app falls back to noisy accessibility text that often contains bookmarks, plugins, and browser shell content instead of the actual page.

## Goals

- Improve active-tab URL extraction for supported Windows browsers.
- Add a stronger Windows live-tab text attempt for authenticated and dynamic pages where feasible.
- Reduce browser UI noise when accessibility fallback is used.
- Keep `spark_app_v2.py` as the active app entrypoint.
- Keep the poll-loop order and payload schema unchanged.
- Preserve the current macOS path as the reference level of behavior without trying to copy AppleScript-specific implementation onto Windows.

## Non-Goals

- Replacing `spark_app_v2.py` with `spark_scraper_integration/spark_app_v3.py`.
- Introducing a separate browser daemon, extension, or native messaging host in the first pass.
- Changing the tracker schema, Jetson DB schema, or serial packet structure.
- Full Firefox support in the first pass.
- Achieving exact feature parity with macOS AppleScript JavaScript injection.

## Approaches Considered

### 1. Recommended: hybrid Windows browser extraction

Keep one poll-loop contract, but improve the Windows internals across three layers:

- stronger browser metadata and URL extraction
- best-effort live-tab/page-surface extraction where Windows can expose it
- filtered accessibility fallback when live extraction is unavailable

This is the best balance because it meaningfully improves dynamic/authenticated pages without betting the entire feature on one fragile browser automation path.

### 2. URL-only improvement plus current fallback

Only make address-bar URL detection more reliable and continue using HTTP extraction or raw accessibility fallback.

This is low-risk but does not address the main quality issue when accessibility fallback becomes noisy.

### 3. Full live-tab automation path only

Invest primarily in a more aggressive Windows browser automation/extraction path and minimize fallback logic.

This could produce strong results when it works, but it is much more brittle and risky for a first pass because browser UI trees and page surfaces vary heavily across Chrome-family browsers and page types.

## Chosen Approach

Implement the hybrid Windows path.

## Design

### 1. Browser Metadata Layer

`host_pc/browser_windows.py` remains the Windows metadata helper, but it should become more robust than the current single-pass address-bar heuristic.

A single canonical browser-name normalization helper, for example `host_pc/browser_common.py`, should be shared across the Windows browser stack so these variants behave consistently:

- `chrome`
- `google chrome`
- `msedge`
- `microsoft edge`
- `brave`
- `brave browser`

That normalization contract should be used by:

- poll-loop browser detection
- Windows metadata lookup
- Windows browser text extraction support checks

Required behavior:

- continue supporting `chrome`, `msedge`, and `brave`
- keep returning `BrowserTabInfo(tab_title, url)` through `host_pc/browser.py`
- attempt multiple address-bar candidate strategies instead of relying on the first matching `Edit` or `ComboBox`
- score candidates by stronger signals such as:
  - explicit name/automation-id address markers
  - known browser-address patterns
  - proximity to the active top-level browser window
  - ability to yield a plausible browser URL
- reject values that are obviously search strings or non-URL shell text unless they match accepted browser-scheme patterns

The metadata layer should fail soft. If it cannot recover a trustworthy URL, it should still return a usable title when possible.

### 2. Windows Live-Tab Text Attempt

`host_pc/web_content.py` should gain a Windows-specific best-effort live-tab extraction path before falling back to HTTP fetch or raw accessibility text.

This is not AppleScript-style JS injection. Instead, it should use Windows-native browser-surface inspection through a concrete helper module, for example a new `host_pc/web_content_windows.py`, that keeps the extraction logic isolated and testable.

The extraction API must be explicitly bound to the poll-selected window identity. The current `extract_page(url, app_name)` shape is not sufficient on its own for Windows live-tab and filtered fallback logic because it loses the selected foreground target. The Windows browser extraction entrypoint should therefore accept the current poll target identity, such as `WindowInfo` and/or a concrete window handle/process identity, so all browser-surface and fallback inspection is tied to the same active window chosen by the poll loop.

The Windows live-tab helper should:

- connect only to the active browser window already selected by the poll loop
- probe the UI Automation tree for document/content-bearing regions first
- collect candidate text containers from likely page-content descendants rather than traversing the entire browser shell indiscriminately
- score candidates using content heuristics before returning success
- stop after a bounded time budget instead of exhaustively walking every descendant

The public `extract_page(...)` contract should remain unchanged and still return a structured `BrowserExtractionResult`.

`BrowserExtractionResult` should be extended with an explicit usefulness signal rather than relying only on `text` truthiness. For example, it should expose one or both of:

- `is_useful: bool`
- `quality_score: float`

The poll loop should use that explicit contract for browser extraction decisions.

Required behavior:

- attempt a page-surface/text-bearing browser region extraction for supported browsers before giving up to HTTP-only behavior
- treat live extraction as best-effort and fail soft when it cannot produce useful content
- preserve existing HTTP extraction for normal external URLs as a separate fallback path
- keep browser extraction ahead of general accessibility fallbacks in the poll loop

The live-tab attempt should be explicitly judged on usefulness, not merely “some text was found.” Browser UI text alone should not count as success.

Minimum usefulness rules:

- require a minimum content length after normalization
- reject candidate text dominated by repeated short UI labels
- reject candidate text where banned browser-shell tokens exceed a configured ratio threshold
- reject candidate text that matches known address-bar/bookmark/menu patterns more strongly than content patterns

The exact thresholds should be centralized constants so the tests can lock them down and adjust them explicitly.

The design should define these as concrete, testable constants rather than vague heuristics, for example:

- `MIN_CONTENT_LEN`
- `MAX_UI_LABEL_RATIO`
- `MAX_REPEAT_RATIO`
- `MIN_TOKEN_DIVERSITY`
- `BROWSER_NOISE_TOKENS`

The exact values can be finalized during implementation planning, but the implementation must use one shared scoring formula rather than per-call ad hoc rules.

### 3. Filtered Fallback Path

When browser extraction still cannot produce useful page text, Windows should fall back more intelligently than the current raw accessibility behavior.

Required behavior:

- prefer document/content regions and meaningful text containers over whole-window text
- reject or heavily down-rank text that is predominantly browser chrome noise, such as:
  - bookmarks bar labels
  - extension/plugin buttons
  - menu labels
  - address-bar shell text
  - repeated navigation shell strings
- preserve a fallback path so the app still captures something when page-aware extraction fails

This should improve the quality of DB rows even when URL extraction or live extraction is incomplete.

The noise filter should be designed as a scoring layer rather than a single blocklist so it can:

- down-rank shell-heavy candidates
- keep mixed but still useful content when the page exposes both content and some browser chrome
- prefer the best available content-bearing candidate instead of returning nothing too aggressively

Ownership of this filter should be explicit. The Windows browser/content layer should expose scored fallback entrypoints rather than leaving `spark_app_v2.py` to call raw accessibility methods directly. For example, the browser/content stack may provide Windows-specific focused and window fallback helpers that return scored candidates with the same usefulness decision rules as the live-tab path.

### 4. Poll Loop Contract

The poll loop in `spark_app_v2.py` should keep the same overall contract:

1. read active window info
2. enrich with browser tab metadata when supported
3. call the browser extraction entrypoint with the selected poll target identity plus browser metadata
4. if browser extraction yields no usable text, fall back to focused element text
5. if needed, fall back again to window text
6. update the tracker and serial sender as today

The implementation may improve the internal browser/fallback decision rules, but it must not replace the poll loop with a separate incompatible path.

Decision matrix for Windows browsers:

1. recover `tab_title` and `url` if possible
2. if the active app is a supported Windows browser and `tab` metadata exists, attempt the Windows live-tab extraction entrypoint even if `url` is empty
3. if live-tab extraction fails and `url` is a fetchable external URL, attempt HTTP extraction
4. if browser extraction still yields no useful text, run the Windows filtered focused-element fallback
5. if that still yields no useful text, run the Windows filtered window-text fallback

This order is part of the design and should be covered by panel-level tests.

The fallback decision should be based on a usefulness flag or equivalent scored outcome, not merely `bool(text)`.

This requires an explicit poll-path change from the current URL-gated browser extraction logic: supported Windows browsers should reach the Windows browser extraction entrypoint when `tab` metadata exists, even if `tab.url` is empty.

The poll loop should also own a strict source adapter boundary. Regardless of any internal Windows extraction sub-source labels, persisted tracker/DB payloads should continue mapping browser-derived text to the existing browser/web `TextSource` value so downstream serialization remains compatible.

### 5. Data Quality Rules

The new Windows browser path should prefer correctness over over-eager capture.

Required behavior:

- do not populate `url` unless it is actually a plausible browser URL
- do not claim a browser extraction success if the captured text is mostly browser shell noise
- keep title and URL extraction logically separate so a missing URL does not erase a good title
- preserve existing context schema fields (`tab_title`, `url`, `text`, `source`) rather than introducing a new payload shape

URL acceptance policy:

- metadata layer may recover browser schemes such as `http`, `https`, `file`, `chrome`, and `edge`
- HTTP extraction remains limited to normal external `http/https` URLs
- localhost, loopback, and file-backed URLs should not be treated as fetchable HTTP targets
- obvious search queries and shell labels should not be promoted into `url`
- if a recovered value is not trustworthy as a URL, keep it empty rather than populating bad metadata

Source compatibility:

- keep serialized snapshot `source` strictly compatible with existing `TextSource` values used by the tracker, DB, and downstream readers
- browser-derived text should continue serializing as the existing browser/web source value rather than inventing new persisted source strings in this pass
- if Windows-specific extraction subtypes are useful, keep them in internal extraction metadata only unless the enum, DB readers, and migration path are extended deliberately in a separate change
- add an explicit adapter at the poll/tracker boundary so internal `BrowserExtractionResult` source labels cannot leak directly into persisted snapshot `source`

### 6. Testing

Required automated coverage:

- Windows browser metadata tests for stronger address-bar candidate selection and URL validation
- browser extraction tests for:
  - live-text success path when page content is available
  - HTTP fallback path when a fetchable external URL exists
  - noise rejection when only browser chrome text is found
- panel-level poll tests proving the improved browser path still falls back cleanly when needed
- regression tests showing bookmarks/plugin shell text does not outrank meaningful page text
- normalization tests proving supported Windows browser name variants behave identically across metadata and extraction layers

Testability requirements:

- keep Windows UI extraction logic behind helper functions or classes that accept mocked UIA-like controls
- add synthetic candidate fixtures for address-bar ranking, content-region ranking, and noise rejection
- avoid requiring real browser processes for the bulk of automated coverage
- keep only a small optional integration smoke layer for real-browser behavior

Performance guardrails:

- each Windows browser extraction pass should have explicit time budgets
- candidate collection should short-circuit once a high-confidence content region is found
- noisy full-window traversals should fail fast rather than block the poll loop
- panel-level tests should continue asserting the poll loop fails soft when browser extraction is slow or empty

Failure and dependency rules:

- missing optional Windows UI libraries must fail soft and return an explicit unsupported/unavailable result
- each Windows extraction stage should have an explicit timeout budget
- timeout or dependency failures must not crash the poll loop
- timeout or dependency failures must continue into the next fallback stage rather than ending capture entirely

## Risks And Limits

- Windows cannot match macOS AppleScript injection exactly, so some authenticated/dynamic pages will still rely on best-effort extraction rather than guaranteed DOM access.
- Browser UI Automation structures can vary across browser versions.
- Some pages may still resist clean live extraction without a browser extension or separate automation channel, which is intentionally out of scope for this pass.

## Success Criteria

- `url` is populated more consistently for supported Windows browsers.
- Dynamic/authenticated pages like YouTube and Google Docs produce better browser rows more often.
- Accessibility fallback rows contain substantially less bookmark/extension/browser-shell noise.
- The active `spark_app_v2.py` runtime keeps the same external polling and payload contracts.
