# Cross-Platform Browser Context Extraction Design

## Summary

Upgrade SPARK's browser-context capture so the active `spark_app_v2.py` runtime keeps the stronger macOS browser path, fixes the current Chrome URL truncation bug, and adds a Windows-specific browser path behind OS detection instead of replacing the macOS logic. The app should keep one poll-loop contract and choose the browser metadata/text strategy internally based on the detected platform.

## Context

The current V2 host runtime uses two browser-specific pieces:

- `host_pc/browser.py` reads the active tab title and URL with AppleScript for Safari and Chrome-family browsers on macOS.
- `host_pc/web_content.py` injects JavaScript into the active Safari/Chrome tab to read visible page text, which works much better than the accessibility tree for many browser pages.

That path is already better than plain accessibility extraction on macOS, but it has two gaps:

- `host_pc/browser.py` currently truncates Chrome URLs to 60 characters, which can corrupt routing and context identity.
- The browser stack is effectively macOS-only, while the repo also supports Windows and the active app entrypoint is documented as cross-platform.

The dropped `spark_scraper_integration/` folder is useful as a source of ideas, especially the stronger Google Docs extraction logic and the HTTP article fallback via `trafilatura`, but it should not be merged wholesale. Its `spark_app_v3.py` prototype regresses the current V2 fallback order by skipping accessibility fallback for browser windows, and its scraping engine assumes AppleScript-heavy behavior that is not valid on Windows.

## Problem Statement

SPARK needs one browser-extraction feature that works across both supported desktop OS targets without losing the stronger macOS path. The runtime should keep the current V2 tracker, serial, and context schema unchanged, but choose the browser integration differently per OS so macOS keeps live-tab extraction while Windows gets its own metadata and text path.

## Goals

- Preserve and improve the current macOS browser flow.
- Fix the Chrome URL truncation bug so browser context keys use the full URL.
- Add a Windows browser metadata path that can identify the active tab title and URL for supported browsers.
- Add a Windows browser text path that produces useful page text when an external URL is available.
- Keep `spark_app_v2.py` as the active app entrypoint.
- Keep the poll-loop fallback order intact: browser extraction first, then accessibility fallbacks if needed.
- Keep the host-to-Pico and host-to-Jetson payload schema unchanged.

## Non-Goals

- Replacing `spark_app_v2.py` with `spark_app_v3.py`.
- Copying `spark_scraper_integration/requirements.txt` over the root `requirements.txt`.
- Introducing a Google Docs credentials flow in this first pass.
- Adding full Firefox support.
- Refactoring the tracker, serial sender, or Jetson DB schema.

## Approaches Considered

### 1. Recommended: keep one browser interface and dispatch internally by OS

Keep `get_browser_tab(...)` and the existing web-extractor entrypoint, but make them choose their platform-specific strategy internally. macOS keeps AppleScript plus live-tab JavaScript extraction; Windows adds a UI Automation-based tab metadata path plus HTTP/trafilatura extraction when a real external URL is available.

This is the smallest safe change because the poll loop, tracker, and serial packet shape do not need to know about the OS split.

### 2. Drop in the coworker scraper engine wholesale

This would reuse more of the unzipped code, but it would also bring over macOS-only assumptions, duplicate existing browser logic, and adopt the `spark_app_v3.py` browser-path regression that skips accessibility fallback for browser windows.

### 3. Keep the current browser path and document Windows as unsupported

This avoids implementation risk, but it fails the requirement to add matching Windows functionality in parallel with the macOS behavior.

## Chosen Approach

Use one cross-platform browser integration contract with platform-dispatched internals. Keep the app-facing surface small and stable, but route macOS and Windows differently underneath it.

## Design

### 1. Browser Metadata Contract

`host_pc/browser.py` remains the public browser metadata entrypoint and keeps the existing `BrowserTabInfo` dataclass. It becomes a dispatcher rather than a purely AppleScript file.

Required behavior:

- On macOS, keep the current AppleScript path for Safari and Chrome-family browsers.
- Remove the current Chrome URL truncation so `BrowserTabInfo.url` always carries the full URL.
- On Windows, accept process-style browser app names such as `chrome` and `msedge` without changing `WindowInfo.app_name` globally.
- Return `None` for unsupported browsers and for cases where no usable title/URL can be recovered.

The Windows metadata implementation should live in its own helper module so the platform-specific UI Automation heuristics do not clutter the macOS path.

### 2. Browser Text Extraction Contract

`host_pc/web_content.py` remains the browser text-extraction surface, but it becomes OS-aware and returns structured extraction results internally.

Required behavior:

- macOS keeps live-tab JavaScript extraction as the primary browser path.
- The Google Docs JavaScript should be upgraded to the stronger same-origin `/export?format=txt` strategy from the dropped scraper code, with DOM-based fallbacks retained after it.
- For normal external web pages on macOS, keep live-tab extraction first and add HTTP/trafilatura only as a fallback so the app still prefers what the user can visibly see in the active tab.
- On Windows, use HTTP/trafilatura when a fetchable external `http/https` URL is available.
- On Windows, do not pretend there is live DOM injection. If the page is local, file-backed, or an authenticated browser app that cannot be fetched over plain HTTP, return no browser text and let the existing accessibility fallbacks try to recover text.

This keeps the macOS path strong without inventing fake Windows parity where the runtime cannot actually provide it yet.

### 3. Poll Loop Contract

The poll loop in `spark_app_v2.py` should keep its current shape:

1. read active window info
2. enrich with browser tab metadata when supported
3. try browser extraction when a browser URL is available
4. if browser extraction does not yield text, fall back to focused-element text
5. if needed, fall back again to full-window text
6. update the tracker and serial sender exactly as today

This is a hard compatibility requirement. The `spark_app_v3.py` prototype changed the fallback order for browser windows, and that regression should not be adopted.

### 4. Dependencies

The first implementation pass only needs the HTTP fallback and the Windows UI Automation libraries already implied by the repo's Windows accessibility path.

Required dependency changes:

- add `trafilatura` to the root `requirements.txt`
- add explicit Windows markers for `pywinauto` and `pywin32` so the documented Windows path is installable from the repo root
- keep the current macOS PyObjC markers intact
- do not add the Google API dependencies in this first pass because the credentials flow is out of scope

### 5. Documentation Contract

Repo docs should explicitly describe the OS split:

- macOS: browser metadata + live-tab JavaScript extraction + HTTP fallback for normal web pages
- Windows: browser metadata via UI Automation + HTTP fallback for external web pages + accessibility fallback for pages that cannot be fetched directly

### 6. Testing

The implementation should be test-driven with mocked platform helpers rather than real browser automation in CI.

Required test coverage:

- `host_pc/browser.py` dispatching and full-URL preservation
- Windows browser metadata heuristics for supported and unsupported app names
- `host_pc/web_content.py` route selection for macOS docs/web and Windows HTTP/local cases
- `spark_app_v2.py` poll-loop behavior proving browser extraction failure still falls back to focused/window accessibility text

## Error Handling

- Browser metadata helpers should fail closed and return `None`, not raise into the poll loop.
- Browser text extractors should return a structured failure with an error string instead of throwing for expected conditions such as unsupported platform routing, missing dependencies, or empty browser content.
- `spark_app_v2.py` should only surface browser extraction status text when it is helpful and should not block accessibility fallback if a browser path returns no text.
- The host context schema must remain unchanged even when browser metadata or browser text extraction fails.

## Open Assumptions

- Initial Windows browser scope is Chromium-family browsers already likely to be in use (`chrome`, `msedge`, optionally `brave`).
- Google Docs on Windows is not expected to reach macOS parity in this first pass; the practical contract is URL capture plus the existing accessibility fallback path.
- `spark_scraper_integration/spark_app_v3.py` remains a reference only and is not promoted to the active app path.

## Testing Strategy

- Use mocked unit tests for platform dispatch and external library calls.
- Keep `tests/test_web_content.py` focused on routing and JS/HTTP selection, not live network fetches.
- Add a focused panel test proving that browser extraction failure still falls back to accessibility extraction.
- Do a manual smoke pass on both OSes after unit tests pass.
