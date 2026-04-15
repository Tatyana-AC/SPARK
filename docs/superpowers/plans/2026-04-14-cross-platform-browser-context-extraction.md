# Cross-Platform Browser Context Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one OS-aware browser context extraction path to `spark_app_v2.py` that preserves the stronger macOS browser behavior, fixes the current Chrome URL truncation bug, and adds a Windows browser path without changing the downstream context schema.

**Architecture:** Keep the active V2 poll loop and the existing tracker/serial flow intact. Route browser tab metadata and browser text extraction internally by OS: macOS keeps AppleScript plus live-tab JavaScript extraction with stronger Google Docs logic, while Windows uses UI Automation-based tab metadata plus HTTP/trafilatura extraction for fetchable external pages and falls back to the existing accessibility path when browser text cannot be fetched directly.

**Tech Stack:** Python, PyQt6, AppleScript, PyObjC, `pywinauto`, `pywin32`, `requests`, `trafilatura`, `unittest`, `pytest`

---

## Reference Spec

- `docs/superpowers/specs/2026-04-14-cross-platform-browser-context-extraction-design.md`

## File Structure

### Create

- `host_pc/browser_windows.py`
  - Windows-specific active-tab metadata helpers for Chromium-family browsers using Win32/UI Automation heuristics
- `tests/test_browser.py`
  - dispatcher coverage for `host_pc/browser.py`, including full-URL preservation and platform routing
- `tests/test_browser_windows.py`
  - focused Windows browser metadata tests using mocked Win32/UI Automation wrappers

### Modify

- `host_pc/browser.py`
  - keep `BrowserTabInfo` as the public contract
  - remove Chrome URL truncation
  - dispatch to macOS or Windows helpers based on `sys.platform`
  - accept Windows process-style browser names without changing global `WindowInfo.app_name`
- `host_pc/web_content.py`
  - keep the existing browser-extractor entrypoint
  - add a structured extraction-result path internally
  - upgrade the macOS Google Docs extractor to the stronger export-first logic
  - add HTTP/trafilatura fallback routing without regressing visible-tab-first behavior on macOS
  - add a Windows external-web extraction path using the same public extractor surface
- `spark_app_v2.py`
  - switch browser extraction from text-only calls to result-aware calls
  - preserve the current browser -> focused element -> full window fallback order
  - keep tracker updates and serial payloads unchanged
- `requirements.txt`
  - add browser-feature dependencies with correct platform markers
- `README.md`
  - document the OS-aware browser extraction behavior and dependency setup
- `REPO_STRUCTURE.md`
  - update the host package map so `browser.py`, `browser_windows.py`, and `web_content.py` reflect the new contract
- `documentation_reference.md`
  - update the poll-loop and extension-point docs for the new OS-aware browser path
- `tests/test_web_content.py`
  - extend coverage for route selection and failure handling
- `tests/test_spark_panel_ui.py`
  - add panel-level coverage for browser extraction success and browser-to-accessibility fallback behavior
- `tests/test_tracker_persistence.py`
  - add explicit coverage that browser snapshots keep the full URL in `current.url` and `context_key`

### Verify Only

- `host_pc/accessibility/windows_provider.py`
  - confirm the existing active-window UI Automation assumptions match the new Windows browser helper expectations; do not refactor unless implementation proves it necessary
- `host_pc/accessibility/tracker.py`
  - no schema changes expected; verify that browser snapshots still use `tab_title` and full `url`
- `host_pc/serial_sender.py`
  - no payload-shape changes expected; verify the browser path still populates `tab_title`, `url`, and `text` the same way

## Guardrails

- Do not adopt `spark_scraper_integration/spark_app_v3.py` as the active app path.
- Do not copy `spark_scraper_integration/requirements.txt` over the root `requirements.txt`.
- Do not change `WindowInfo.app_name` globally just to normalize browser detection; keep normalization local to browser helpers.
- Keep `WindowContextSnapshot.context_key` behavior unchanged except that browser URLs must now remain full-length.
- Keep browser extraction optional and fail-soft; if browser extraction yields no text, the app must still try accessibility extraction.
- On macOS, keep live-tab extraction as the first browser text path.
- On Windows, only claim browser-text success when the app actually recovered text; otherwise return a structured failure and let the existing fallback chain continue.
- Do not add Google Docs credential handling in this pass.
- Keep any Windows-only imports lazy or import-guarded so `host_pc/browser_windows.py` can be imported by tests on non-Windows runners.

## Task 1: Add Cross-Platform Browser Metadata Dispatch

**Files:**
- Create: `host_pc/browser_windows.py`
- Create: `tests/test_browser.py`
- Create: `tests/test_browser_windows.py`
- Modify: `host_pc/browser.py:1-82`
- Modify: `tests/test_tracker_persistence.py:1-99`
- Verify: `host_pc/accessibility/windows_provider.py:231-247`

- [ ] **Step 1: Write the failing dispatcher and full-URL tests**

Create `tests/test_browser.py` with coverage like:

```python
import unittest
from unittest import mock

from host_pc import browser


class BrowserDispatchTests(unittest.TestCase):
    def test_macos_chrome_url_is_not_truncated(self):
        full_url = "https://example.com/very/long/path?alpha=1&beta=two&gamma=three"

        with (
            mock.patch.object(browser, "sys") as sys_mod,
            mock.patch.object(browser, "_run_applescript") as run_applescript,
        ):
            sys_mod.platform = "darwin"
            run_applescript.side_effect = ["Doc", full_url]

            result = browser.get_browser_tab("Google Chrome")

        self.assertEqual(result.url, full_url)

    def test_windows_browser_names_dispatch_to_windows_helper(self):
        fake = browser.BrowserTabInfo(tab_title="Tab", url="https://example.com")

        with (
            mock.patch.object(browser, "sys") as sys_mod,
            mock.patch.object(browser, "_get_windows_browser_tab", return_value=fake) as get_tab,
        ):
            sys_mod.platform = "win32"

            result = browser.get_browser_tab("chrome")

        self.assertEqual(result, fake)
        get_tab.assert_called_once_with("chrome")

    def test_unsupported_platform_returns_none(self):
        with mock.patch.object(browser, "sys") as sys_mod:
            sys_mod.platform = "linux"
            self.assertIsNone(browser.get_browser_tab("chrome"))
```

Add explicit browser-snapshot coverage to `tests/test_tracker_persistence.py`:

```python
from types import SimpleNamespace

from host_pc.accessibility.base import TextSource


def test_browser_snapshot_context_key_uses_full_url(self):
    full_url = "https://example.com/very/long/path?alpha=1&beta=two&gamma=three"

    self.tracker.update(
        make_window_info(
            title="Example",
            app_name="Google Chrome",
            process_name="Google Chrome",
            pid=303,
        ),
        "browser text",
        TextSource.WEB_CONTENT,
        tab=SimpleNamespace(tab_title="Example", url=full_url),
    )

    current = self.tracker.get_current()

    self.assertEqual(current.url, full_url)
    self.assertEqual(current.context_key, f"Google Chrome|{full_url}")
```

- [ ] **Step 2: Write the failing Windows metadata tests**

Create `tests/test_browser_windows.py` with focused Windows-only helper coverage:

```python
import unittest
from unittest import mock

from host_pc import browser_windows


class WindowsBrowserTabTests(unittest.TestCase):
    def test_returns_none_for_non_browser_app(self):
        self.assertIsNone(browser_windows.get_browser_tab("notepad"))

    # This file imports `browser_windows` at module import time. If the module has
    # top-level Windows-only imports, test collection will fail on non-Windows CI.

    def test_prefers_address_bar_value_for_url(self):
        window = mock.Mock()
        address_bar = mock.Mock()
        address_bar.window_text.return_value = "https://example.com/path"
        address_bar.get_value.return_value = "https://example.com/path"
        window.window_text.return_value = "Example Domain - Google Chrome"

        with (
            mock.patch.object(browser_windows, "_connect_to_active_window", return_value=window),
            mock.patch.object(browser_windows, "_find_address_bar", return_value=address_bar),
            mock.patch.object(browser_windows, "_find_tab_title", return_value="Example Domain"),
        ):
            result = browser_windows.get_browser_tab("chrome")

        self.assertEqual(result.url, "https://example.com/path")
        self.assertEqual(result.tab_title, "Example Domain")

    def test_returns_none_when_window_connection_fails(self):
        with mock.patch.object(browser_windows, "_connect_to_active_window", return_value=None):
            self.assertIsNone(browser_windows.get_browser_tab("msedge"))

    def test_import_safe_when_windows_dependencies_are_missing(self):
        with mock.patch.object(browser_windows, "_connect_to_active_window", return_value=None):
            self.assertIsNone(browser_windows.get_browser_tab("chrome"))
```

- [ ] **Step 3: Run the new tests to verify RED**

Run:

```bash
python -m pytest tests/test_browser.py tests/test_browser_windows.py tests/test_tracker_persistence.py -q
```

Expected: FAIL because `host_pc/browser_windows.py` and the platform dispatch helpers do not exist yet.

- [ ] **Step 4: Implement the Windows browser helper module**

Create `host_pc/browser_windows.py` with one small helper surface:

```python
from typing import Optional

from .browser import BrowserTabInfo

WINDOWS_BROWSER_ALIASES = {
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "brave": "Brave Browser",
}


def _load_windows_libraries():
    try:
        import win32gui
        from pywinauto import Application
    except ImportError:
        return None, None
    return win32gui, Application


def get_browser_tab(app_name: str) -> Optional[BrowserTabInfo]:
    normalized = (app_name or "").strip().casefold()
    if normalized not in WINDOWS_BROWSER_ALIASES:
        return None

    window = _connect_to_active_window()
    if window is None:
        return None

    url = _read_address_bar_url(window)
    title = _read_tab_title(window)
    if not title and not url:
        return None
    return BrowserTabInfo(tab_title=title or "", url=url or "")
```

Implementation notes:

```text
- keep normalization local to this module; do not mutate `WindowInfo.app_name`
- keep all Windows-only dependency imports inside helper functions or a guarded initializer like `_load_windows_libraries()` so importing `host_pc/browser_windows.py` never fails on macOS/Linux
- use the same Win32/UIA libraries already implied by `host_pc/accessibility/windows_provider.py`
- prefer address-bar value extraction before generic window text
- preserve browser-looking address-bar values such as `http://`, `https://`, `file://`, `chrome://`, and `edge://` as tab metadata when present, but treat only external `http/https` values as fetchable browser-text URLs later in `host_pc/web_content.py`
- fail closed and return `None` on import/init problems
```

- [ ] **Step 5: Rework `host_pc/browser.py` into a platform dispatcher**

Update `host_pc/browser.py` to:

```python
import sys


def _get_macos_browser_tab(app_name: str) -> Optional[BrowserTabInfo]:
    ...


def _get_windows_browser_tab(app_name: str) -> Optional[BrowserTabInfo]:
    from .browser_windows import get_browser_tab as get_windows_browser_tab
    return get_windows_browser_tab(app_name)


def get_browser_tab(app_name: str) -> Optional[BrowserTabInfo]:
    if sys.platform == "darwin":
        return _get_macos_browser_tab(app_name)
    if sys.platform == "win32":
        return _get_windows_browser_tab(app_name)
    return None
```

Required edits:

```text
- keep the existing AppleScript helper logic under `_get_macos_browser_tab`
- delete the current `if app_name == "Google Chrome": url = url[:60]` truncation block entirely
- keep `BrowserTabInfo` unchanged
- keep the file import-safe on non-Windows hosts by deferring the Windows helper import
```

- [ ] **Step 6: Run the browser metadata tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_browser.py tests/test_browser_windows.py tests/test_tracker_persistence.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add host_pc/browser.py host_pc/browser_windows.py tests/test_browser.py tests/test_browser_windows.py tests/test_tracker_persistence.py
git commit -m "feat: add cross-platform browser tab metadata routing"
```

## Task 2: Add OS-Aware Browser Text Extraction With macOS Live-Tab Priority

**Files:**
- Modify: `host_pc/web_content.py:1-165`
- Modify: `tests/test_web_content.py:1-41`
- Verify: `spark_scraper_integration/scraper_engine.py:147-354`

- [ ] **Step 1: Write the failing extraction-routing tests**

Expand `tests/test_web_content.py` with coverage like:

```python
import unittest
from unittest import mock

from host_pc import web_content


class WebContentExtractorTests(unittest.TestCase):
    def test_google_docs_script_uses_export_first_strategy(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(extractor, "_run_js", return_value="doc text") as run_js:
            result = extractor.extract_page(
                "https://docs.google.com/document/d/123/edit",
                "Google Chrome",
                platform="darwin",
            )

        self.assertEqual(result.text, "doc text")
        self.assertIn("/export?format=txt", run_js.call_args.args[0])

    def test_windows_external_url_uses_http_fallback(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(extractor, "_extract_http_text", return_value=("site text", "Example")) as extract_http:
            result = extractor.extract_page("https://example.com", "chrome", platform="win32")

        self.assertEqual(result.text, "site text")
        self.assertEqual(result.source, "http_fallback")
        extract_http.assert_called_once_with("https://example.com")

    def test_windows_local_url_returns_no_browser_text(self):
        extractor = web_content.WebContentExtractor()
        result = extractor.extract_page("http://localhost:3000", "chrome", platform="win32")

        self.assertIsNone(result.text)
        self.assertEqual(result.error, "browser text unavailable for local Windows pages")

    def test_windows_file_url_returns_no_browser_text(self):
        extractor = web_content.WebContentExtractor()
        result = extractor.extract_page("file:///Users/test/demo.html", "chrome", platform="win32")

        self.assertIsNone(result.text)
        self.assertEqual(result.error, "browser text unavailable for local Windows pages")

    def test_google_docs_retries_dom_after_empty_export_result(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(
            extractor,
            "_run_js",
            side_effect=[None, "dom fallback text"],
        ) as run_js:
            result = extractor.extract_page(
                "https://docs.google.com/document/d/123/edit",
                "Google Chrome",
                platform="darwin",
            )

        self.assertEqual(result.text, "dom fallback text")
        self.assertEqual(run_js.call_count, 2)
        self.assertIn("/export?format=txt", run_js.call_args_list[0].args[0])
        self.assertIn("kix-lineview-text-block", run_js.call_args_list[1].args[0])

    def test_get_page_text_stays_backward_compatible(self):
        extractor = web_content.WebContentExtractor()

        with mock.patch.object(extractor, "extract_page") as extract_page:
            extract_page.return_value = web_content.BrowserExtractionResult(
                text="body text",
                source="live_js",
                title=None,
                error=None,
            )

            self.assertEqual(extractor.get_page_text("https://example.com", "chrome"), "body text")
```

- [ ] **Step 2: Run the updated web-content tests to verify RED**

Run:

```bash
python -m pytest tests/test_web_content.py -q
```

Expected: FAIL because `extract_page(...)`, `BrowserExtractionResult`, and the new routing behavior do not exist yet.

- [ ] **Step 3: Add a structured extraction result and routing surface**

Update `host_pc/web_content.py` with a small result object and a new primary API:

```python
from dataclasses import dataclass
import sys


@dataclass
class BrowserExtractionResult:
    text: str | None
    source: str | None
    title: str | None = None
    error: str | None = None


class WebContentExtractor:
    def extract_page(self, url: str, app_name: str, platform: str | None = None) -> BrowserExtractionResult:
        platform = platform or sys.platform
        if platform == "darwin":
            return self._extract_macos_page(url, app_name)
        if platform == "win32":
            return self._extract_windows_page(url, app_name)
        return BrowserExtractionResult(text=None, source=None, error=f"unsupported platform: {platform}")

    def get_page_text(self, url: str, app_name: str) -> str | None:
        return self.extract_page(url, app_name).text
```

Implementation notes:

```text
- keep `get_page_text(...)` as a compatibility wrapper for any unconverted callers/tests
- do not introduce a new public module just to hold the result dataclass
- keep the extractor object lightweight and stateless
```

- [ ] **Step 4: Upgrade the macOS browser path with stronger Google Docs logic**

Port the Google Docs script strategy from `spark_scraper_integration/scraper_engine.py` into `host_pc/web_content.py` and keep the existing browser-JS path structure.

Required code shape:

```python
def _extract_google_docs_live_text(self, app_name: str) -> str | None:
    export_text = self._run_js(_JS_GOOGLE_DOCS_EXPORT, app_name)
    if export_text:
        return export_text
    return self._run_js(_JS_GOOGLE_DOCS_DOM_FALLBACK, app_name)


def _extract_macos_page(self, url: str, app_name: str) -> BrowserExtractionResult:
    if app_name not in SUPPORTED_BROWSERS:
        return BrowserExtractionResult(text=None, source=None, error="unsupported browser")

    if _is_google_docs(url):
        text = self._extract_google_docs_live_text(app_name)
    else:
        js = self._pick_js(url)
        text = self._run_js(js, app_name)

    if text:
        return BrowserExtractionResult(text=text, source="live_js")

    if _is_external_web(url):
        http_text, title = self._extract_http_text(url)
        if http_text:
            return BrowserExtractionResult(text=http_text, source="http_fallback", title=title)

    return BrowserExtractionResult(text=None, source=None, error="browser extraction returned no text")
```

Required route rules:

```text
- Google Docs: use the stronger `/export?format=txt` JavaScript first, then DOM fallbacks
- Google Sheets: keep rendered-grid JS extraction
- general external web: try live JS first, then HTTP/trafilatura fallback
- localhost/file/no-url: keep live browser JS only on macOS
- require one focused test proving that when the Google Docs export call yields no usable text, a second DOM fallback call still returns content
```

- [ ] **Step 5: Add the Windows extraction route**

Implement a small Windows-specific branch in `host_pc/web_content.py`:

```python
def _extract_windows_page(self, url: str, app_name: str) -> BrowserExtractionResult:
    if not _is_supported_windows_browser(app_name):
        return BrowserExtractionResult(text=None, source=None, error="unsupported browser")
    if not _is_external_web(url):
        return BrowserExtractionResult(
            text=None,
            source=None,
            error="browser text unavailable for local Windows pages",
        )

    text, title = self._extract_http_text(url)
    if text:
        return BrowserExtractionResult(text=text, source="http_fallback", title=title)
    return BrowserExtractionResult(text=None, source=None, error="http fallback returned no text")
```

Implementation notes:

```text
- reuse one `_extract_http_text(url)` helper for both OS paths
- make `_extract_http_text` own the `requests` + `trafilatura` import/error handling
- make `_is_external_web(url)` explicitly exclude `localhost`, loopback hosts, and `file://` URLs
- keep network fetches out of unit tests by mocking `_extract_http_text`
- do not promise live DOM extraction on Windows in this first pass
```

- [ ] **Step 6: Run the updated web-content tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_web_content.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add host_pc/web_content.py tests/test_web_content.py
git commit -m "feat: add os-aware browser text extraction"
```

## Task 3: Rewire the V2 Poll Loop Without Regressing Accessibility Fallbacks

**Files:**
- Modify: `spark_app_v2.py:518-520`
- Modify: `spark_app_v2.py:1075-1100`
- Modify: `tests/test_spark_panel_ui.py`

- [ ] **Step 1: Write the failing panel tests for structured browser results**

Add or update tests in `tests/test_spark_panel_ui.py` like:

```python
def test_browser_result_with_text_uses_web_content_source(self):
    panel = self._make_panel()
    panel.web_extractor.extract_page = mock.Mock(
        return_value=spark_app_v2.BrowserExtractionResult(
            text="page text",
            source="live_js",
            title=None,
            error=None,
        )
    )

    ...

    tracker.update.assert_called_once()
    self.assertEqual(tracker.update.call_args.args[2], TextSource.WEB_CONTENT)


def test_browser_failure_falls_back_to_focused_element_text(self):
    panel = self._make_panel()
    panel.web_extractor.extract_page = mock.Mock(
        return_value=spark_app_v2.BrowserExtractionResult(
            text=None,
            source=None,
            title=None,
            error="browser extraction returned no text",
        )
    )
    panel.manager.get_focused_element_text.return_value = "focused text"

    ...

    tracker.update.assert_called_once()
    self.assertEqual(tracker.update.call_args.args[1], "focused text")


def test_browser_failure_still_tries_window_text_after_empty_focused_text(self):
    panel = self._make_panel()
    panel.web_extractor.extract_page = mock.Mock(
        return_value=spark_app_v2.BrowserExtractionResult(text=None, source=None, title=None, error="no text")
    )
    panel.manager.get_focused_element_text.return_value = None
    panel.manager.get_window_text.return_value = "window text"

    ...

    tracker.update.assert_called_once()
    self.assertEqual(tracker.update.call_args.args[1], "window text")
```

- [ ] **Step 2: Run the panel tests to verify RED**

Run:

```bash
python -m pytest tests/test_spark_panel_ui.py -q
```

Expected: FAIL because the panel still calls `get_page_text(...)` and does not know about `BrowserExtractionResult`.

- [ ] **Step 3: Import and use the structured browser extractor result in `spark_app_v2.py`**

Update imports and the browser block in `_on_poll_tick()` to follow this shape:

```python
browser_result = None

if tab and tab.url:
    try:
        browser_result = self.web_extractor.extract_page(tab.url, info.app_name)
        if browser_result.text:
            text = browser_result.text
            source = TextSource.WEB_CONTENT
    except Exception as exc:
        logger.warning("[POLL] browser extraction failed for %s: %s", info.app_name, exc)

if not text:
    text = self.manager.get_focused_element_text()
    ...

if not text:
    text = self.manager.get_window_text()
    ...
```

Required behavior notes:

```text
- keep browser extraction ahead of AX fallbacks
- keep AX fallbacks available for browser windows when browser extraction returns no text
- do not switch to the `spark_app_v3.py` behavior that bypasses AX fallback for browsers
- keep `tracker.update(info, text, source, tab=tab)` unchanged
- only set status text for browser extraction errors if that does not mask later fallback success
```

- [ ] **Step 4: Run the panel tests to verify GREEN**

Run:

```bash
python -m pytest tests/test_spark_panel_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add spark_app_v2.py tests/test_spark_panel_ui.py
git commit -m "refactor: preserve browser fallback order across platforms"
```

## Task 4: Add Dependency Markers And Update Runtime Docs

**Files:**
- Modify: `requirements.txt:1-13`
- Modify: `README.md:120-135`
- Modify: `REPO_STRUCTURE.md:19-30`
- Modify: `documentation_reference.md:11-27`
- Modify: `documentation_reference.md:79-118`

- [ ] **Step 1: Write the failing dependency/doc assertions**

Add lightweight doc or requirements assertions only if the repo already has a pattern for them. If not, treat this step as a manual diff checklist instead of inventing doc tests.

Manual checklist:

```text
- root requirements include `trafilatura`
- root requirements include Windows markers for `pywinauto` and `pywin32`
- README documents macOS vs Windows browser behavior separately
- REPO_STRUCTURE and documentation_reference describe `host_pc/browser_windows.py`
```

- [ ] **Step 2: Update `requirements.txt` with platform-safe additions**

Edit the root file to include:

```text
trafilatura>=1.12.0
pywinauto>=0.6.8; sys_platform == "win32"
pywin32>=306; sys_platform == "win32"
```

Rules:

```text
- keep the existing PyObjC `sys_platform == "darwin"` markers intact
- do not add the Google Docs API packages yet
- do not remove `pytest`
```

- [ ] **Step 3: Update `README.md` for the new OS-aware browser path**

Add concise notes covering:

```text
- `spark_app_v2.py` remains the active app path
- macOS browser path uses live-tab extraction for supported Safari/Chrome-family tabs and can fall back to HTTP extraction for normal sites
- Windows browser path uses browser-tab metadata plus HTTP extraction for external pages, then falls back to accessibility when browser text is not directly fetchable
- Windows setup now expects the UI Automation dependencies from root requirements
```

- [ ] **Step 4: Update structure/reference docs**

Edit `REPO_STRUCTURE.md` and `documentation_reference.md` so they describe:

```text
- `host_pc/browser.py` as the OS-dispatched browser metadata entrypoint
- `host_pc/browser_windows.py` as the Windows tab metadata helper
- `host_pc/web_content.py` as the OS-aware browser text extractor
- the unchanged poll-loop fallback order in `spark_app_v2.py`
```

- [ ] **Step 5: Verify dependency installation metadata and docs by inspection**

Run:

```bash
python -m pip install -r requirements.txt --dry-run
```

If `--dry-run` is unavailable in the target pip version, use:

```bash
python -m pip install -r requirements.txt
```

Expected: the dependency set resolves on the current platform without trying to install the macOS-only packages on Windows or the Windows-only packages on macOS.

- [ ] **Step 6: Commit Task 4**

```bash
git add requirements.txt README.md REPO_STRUCTURE.md documentation_reference.md
git commit -m "docs: document cross-platform browser extraction"
```

## Task 5: Run Focused Verification And Manual Smoke Checks

**Files:**
- Verify: `host_pc/browser.py`
- Verify: `host_pc/browser_windows.py`
- Verify: `host_pc/web_content.py`
- Verify: `spark_app_v2.py`
- Verify: `tests/test_browser.py`
- Verify: `tests/test_browser_windows.py`
- Verify: `tests/test_web_content.py`
- Verify: `tests/test_spark_panel_ui.py`
- Verify: `tests/test_windows_provider.py`

- [ ] **Step 1: Run the focused automated test set**

Run:

```bash
python -m pytest tests/test_browser.py tests/test_browser_windows.py tests/test_web_content.py tests/test_spark_panel_ui.py tests/test_windows_provider.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the broader host-side regression slice**

Run:

```bash
python -m pytest tests/test_serial_sender.py tests/test_context_stream_e2e.py tests/test_protocol_packets.py -q
```

Expected: PASS, proving the browser-path changes did not alter host payload shape or protocol expectations.

- [ ] **Step 3: Manual smoke test the macOS browser path**

Run the app on macOS and verify these cases manually:

```text
1. Safari general website -> browser text captured from visible page or HTTP fallback
2. Google Chrome general website -> browser text captured and full URL preserved in context
3. Google Docs in Chrome/Safari -> text captured via export-first live-tab logic
4. Google Sheets in Chrome/Safari -> visible grid text still captured
5. localhost page in Chrome/Safari -> live-tab JS path still works
```

Expected: browser extraction remains stronger than plain AX extraction and the app still falls back to AX if browser extraction yields no text.

- [ ] **Step 4: Manual smoke test the Windows browser path**

Run the app on Windows and verify these cases manually:

```text
1. Chrome external website -> tab title and URL are captured, body text comes from HTTP fallback
2. Edge external website -> same as Chrome
3. Google Docs in Chrome/Edge -> metadata is captured, browser text may fail, AX fallback still runs
4. localhost page in Chrome/Edge -> browser text may fail, AX fallback still runs
5. Non-browser app -> no browser regression; focused/window accessibility still works
```

Expected: Windows now contributes browser metadata and external-page text without regressing the existing accessibility path.

- [ ] **Step 5: Capture follow-up issues explicitly**

If manual smoke reveals gaps, log them as concrete follow-up items instead of widening this change mid-flight.

Expected follow-ups to keep separate unless they are blocking:

```text
- broader Windows browser support beyond Chromium
- deeper Windows Google Docs capture parity
- optional Google Docs API credentials flow
```

- [ ] **Step 6: Commit Task 5**

```bash
git add host_pc/browser.py host_pc/browser_windows.py host_pc/web_content.py spark_app_v2.py requirements.txt README.md REPO_STRUCTURE.md documentation_reference.md tests/test_browser.py tests/test_browser_windows.py tests/test_web_content.py tests/test_spark_panel_ui.py
git commit -m "feat: add cross-platform browser context extraction"
```
