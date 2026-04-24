# Windows Browser Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Windows browser context capture so Chrome/Edge/Brave produce more reliable URLs, better live-tab text, and cleaner fallback text in the active `spark_app_v2.py` runtime.

**Architecture:** Add one shared browser-normalization helper, strengthen Windows metadata extraction in `host_pc/browser_windows.py`, add a Windows-specific browser text helper in `host_pc/web_content_windows.py`, and keep `host_pc/web_content.py` as the public cross-platform dispatcher. Update `spark_app_v2.py` only enough to pass the poll-selected window identity into browser extraction, use explicit usefulness decisions, and preserve persisted `TextSource.WEB_CONTENT` semantics.

**Tech Stack:** Python 3, PyQt6, pywinauto/UIA on Windows, existing `requests` + `trafilatura` fallback path, unittest/pytest.

---

## File Map

- Create: `host_pc/browser_common.py`
  Shared Windows browser-name normalization and support checks.
- Modify: `host_pc/browser.py`
  Dispatch through the shared browser normalization and keep the existing `BrowserTabInfo` surface.
- Modify: `host_pc/browser_windows.py`
  Strengthen address-bar candidate selection and URL validation while binding results to the poll-selected browser window instead of re-sampling foreground state.
- Create: `host_pc/web_content_windows.py`
  Windows live-tab/page-surface extraction, usefulness scoring, browser-noise filtering, and filtered focused/window fallback helpers.
- Modify: `host_pc/web_content.py`
  Extend `BrowserExtractionResult`, dispatch Windows extraction through the new helper, use the shared browser normalizer for Windows support checks, and preserve the cross-platform public API.
- Modify: `spark_app_v2.py`
  Use the shared browser normalizer for poll detection, pass poll-selected window identity into browser extraction, run Windows extraction when `tab` metadata exists even if `url` is empty, and preserve persisted `TextSource.WEB_CONTENT` mapping.
- Modify: `tests/test_browser_windows.py`
  Cover stronger address-bar candidate ranking and browser-name normalization behavior.
- Modify: `tests/test_web_content.py`
  Cover Windows live extraction, usefulness/noise decisions, HTTP fallback, and fail-soft behavior.
- Modify: `tests/test_spark_panel_ui.py`
  Cover Windows poll-loop ordering and filtered fallback decisions.
- Create: `tests/test_web_content_windows.py`
  Focused unit tests for Windows content-region scoring, noise filtering, and fallback helpers.
- Reference: `docs/specs/2026-04-16-windows-browser-extraction-design.md`

## Task 1: Add Shared Browser Normalization And Stronger Windows Metadata Ranking

**Files:**
- Create: `host_pc/browser_common.py`
- Modify: `host_pc/browser_windows.py`
- Modify: `host_pc/browser.py`
- Test: `tests/test_browser_windows.py`

- [ ] **Step 1: Write the failing browser normalization and ranking tests**

```python
def test_normalize_windows_browser_name_accepts_process_and_display_variants():
    from host_pc.browser_common import normalize_windows_browser_name

    assert normalize_windows_browser_name("chrome") == "chrome"
    assert normalize_windows_browser_name("Google Chrome") == "chrome"
    assert normalize_windows_browser_name("msedge") == "msedge"
    assert normalize_windows_browser_name("Microsoft Edge") == "msedge"
    assert normalize_windows_browser_name("Brave Browser") == "brave"


def test_get_browser_tab_prefers_trustworthy_address_candidate_over_first_edit_control():
    fake_window = object()
    weak_candidate = object()
    strong_candidate = object()

    with (
        mock.patch.object(browser_windows, "_connect_to_active_window", return_value=fake_window),
        mock.patch.object(browser_windows, "_find_address_bar_candidates", return_value=[weak_candidate, strong_candidate]),
        mock.patch.object(browser_windows, "_score_address_bar_candidate", side_effect=[10, 100]),
        mock.patch.object(browser_windows, "_read_address_bar_url", side_effect=[None, "https://example.com/watch?v=1"]),
        mock.patch.object(browser_windows, "_read_tab_title", return_value="Theo stream - YouTube - Google Chrome"),
    ):
        result = browser_windows.get_browser_tab("Google Chrome")

    assert result.url == "https://example.com/watch?v=1"


def test_get_browser_tab_rejects_search_like_shell_text_as_url():
    fake_window = object()
    address_bar = object()

    with (
        mock.patch.object(browser_windows, "_connect_to_active_window", return_value=fake_window),
        mock.patch.object(browser_windows, "_select_best_address_bar", return_value=address_bar),
        mock.patch.object(browser_windows, "_read_address_bar_url", return_value=None),
        mock.patch.object(browser_windows, "_read_tab_title", return_value="Theo stream - YouTube - Google Chrome"),
    ):
        result = browser_windows.get_browser_tab("Google Chrome")

    assert result is not None
    assert result.url == ""
    assert result.tab_title == "Theo stream - YouTube - Google Chrome"


def test_browser_address_accepts_expected_schemes_only():
    assert browser_windows._is_browser_address("https://example.com") is True
    assert browser_windows._is_browser_address("chrome://settings") is True
    assert browser_windows._is_browser_address("edge://favorites") is True
    assert browser_windows._is_browser_address("search terms in omnibox") is False
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_browser_windows.py -q`
Expected: FAIL because the shared normalizer and ranked-candidate helpers do not exist yet.

- [ ] **Step 3: Write the minimal shared browser normalizer**

```python
WINDOWS_BROWSER_NAME_MAP = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "msedge": "msedge",
    "microsoft edge": "msedge",
    "brave": "brave",
    "brave browser": "brave",
}


def normalize_windows_browser_name(app_name: str) -> str | None:
    normalized = (app_name or "").strip().lower()
    return WINDOWS_BROWSER_NAME_MAP.get(normalized)
```

- [ ] **Step 4: Refactor Windows metadata helpers to rank candidates explicitly**

Add helpers like:

- `_find_address_bar_candidates(window)`
- `_score_address_bar_candidate(control)`
- `_select_best_address_bar(window)`

Keep the implementation minimal and deterministic:

- explicit address-name or automation-id match scores highest
- valid browser-URL-like control values outrank generic search text
- return the strongest candidate instead of the first `Edit`/`ComboBox`

- [ ] **Step 5: Bind Windows metadata lookup to the poll-selected window target**

Extend the Windows metadata API to accept the already-sampled target identity, for example:

```python
def get_browser_tab(app_name: str, window_target=None) -> Optional[BrowserTabInfo]:
    ...
```

Use the poll-selected target instead of calling foreground-window lookup again when a target is provided.

- [ ] **Step 6: Update `host_pc/browser.py` to use the shared browser normalizer path on Windows**

Make sure Windows browser support checks stop duplicating their own browser-name sets.

Thread the optional `window_target` through the public wrapper as well, for example:

```python
def get_browser_tab(app_name: str, window_target=None) -> Optional[BrowserTabInfo]:
    ...
```

so `spark_app_v2.py` can pass the poll-selected target through the public browser entrypoint instead of relying on a Windows-only helper directly.

- [ ] **Step 7: Replace all duplicated Windows browser support checks with the shared normalizer**

Update both:

- `spark_app_v2._is_browser_app_for_poll`
- `host_pc/web_content.py::_is_supported_windows_browser`
- `host_pc/browser_windows.py` membership gating

to use `normalize_windows_browser_name(...)` instead of their own hardcoded Windows browser sets.

- [ ] **Step 8: Add concrete metadata target-binding regressions**

In `tests/test_browser_windows.py`, add a test proving `get_browser_tab(..., window_target=...)` reads metadata from the passed target rather than re-sampling a different foreground window.

Also add a wrapper-level regression proving `host_pc.browser.get_browser_tab(..., window_target=...)` forwards the target through to the Windows helper.

Add one explicit cross-layer normalization parity test that asserts all supported Windows browser-name variants behave identically across:

- `normalize_windows_browser_name(...)`
- `spark_app_v2._is_browser_app_for_poll(...)`
- `host_pc/web_content.py` Windows support checks
- `host_pc/browser_windows.py` metadata support checks

Add one concrete URL-policy matrix test that verifies, across the shared browser and web-content layers, that:

- metadata accepts intended browser schemes (`http`, `https`, `chrome`, `edge`, `file`) where appropriate
- HTTP extraction still treats localhost, loopback, and `file://` as non-fetchable
- normalized browser names and URL-policy decisions stay consistent across `browser_common`, `browser_windows`, and `web_content`

- [ ] **Step 9: Run the focused browser tests to verify they pass**

Run: `pytest tests/test_browser_windows.py -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add host_pc/browser_common.py host_pc/browser.py host_pc/browser_windows.py tests/test_browser_windows.py
git commit -m "fix: strengthen Windows browser metadata extraction"
```

## Task 2: Add Windows Live-Tab Extraction And Usefulness Scoring

**Files:**
- Create: `host_pc/web_content_windows.py`
- Modify: `host_pc/web_content.py`
- Test: `tests/test_web_content_windows.py`
- Modify: `tests/test_web_content.py`

- [ ] **Step 1: Write the failing Windows extraction tests**

```python
def test_windows_live_candidate_with_document_like_text_is_useful():
    from host_pc import web_content_windows

    candidate = web_content_windows.ScoredTextCandidate(
        text="This is a real page transcript with enough distinct words to count as content.",
        score=0.0,
        source_hint="uia_document",
    )

    result = web_content_windows.evaluate_candidate(candidate)

    assert result.is_useful is True


def test_windows_browser_noise_is_rejected_as_not_useful():
    from host_pc import web_content_windows

    candidate = web_content_windows.ScoredTextCandidate(
        text="Bookmarks Extensions Apps Settings Profile Search Address bar Reload Back Forward",
        score=0.0,
        source_hint="uia_toolbar",
    )

    result = web_content_windows.evaluate_candidate(candidate)

    assert result.is_useful is False
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_web_content_windows.py -q`
Expected: FAIL because the Windows extraction helper module does not exist yet.

- [ ] **Step 3: Create the Windows content helper module with explicit scoring constants**

Include explicit shared constants such as:

- `MIN_CONTENT_LEN`
- `MAX_UI_LABEL_RATIO`
- `MAX_REPEAT_RATIO`
- `MIN_TOKEN_DIVERSITY`
- `BROWSER_NOISE_TOKENS`
- `LIVE_EXTRACT_TIMEOUT_MS`
- `WINDOW_TRAVERSAL_BUDGET_MS`
- `FALLBACK_TRAVERSAL_BUDGET_MS`

Define a small `ScoredTextCandidate` dataclass and one evaluation function that returns:

- cleaned text
- `is_useful`
- `quality_score`
- internal source hint

- [ ] **Step 4: Add a best-effort UIA content-region probe**

Create one bounded entrypoint like `extract_live_browser_text(window_target, app_name)` that:

- inspects likely document/content-bearing descendants first
- gathers candidate text regions
- scores them
- returns the best useful result or a structured failure

Keep timeouts and traversal bounded. Do not overbuild a generalized automation framework.

Add explicit tests for:

- traversal stops once the live extraction time budget is exceeded
- dependency failures return a structured failure without raising
- noisy candidate lists short-circuit once a high-confidence page-content candidate is found

- [ ] **Step 5: Extend `BrowserExtractionResult` with usefulness metadata in `host_pc/web_content.py`**

Add explicit fields like:

- `is_useful: bool = False`
- `quality_score: float = 0.0`

Update the macOS and HTTP paths to set these fields consistently.

- [ ] **Step 6: Dispatch Windows extraction through the new helper**

In `host_pc/web_content.py`, make the Windows flow:

1. try Windows live extraction
2. if not useful and URL is fetchable, try HTTP extraction
3. otherwise return the best structured failure for the poll loop to continue with accessibility fallback

Keep the public API backward-compatible by extending the extraction signature with an optional target argument, for example:

```python
def extract_page(self, url: str, app_name: str, platform: Optional[str] = None, window_target=None) -> BrowserExtractionResult:
    ...
```

Existing two-argument call sites must continue to work unchanged.

Update all affected tests in `tests/test_web_content.py` so the new `is_useful` / `quality_score` contract is asserted explicitly, not inferred from `bool(text)`.

- [ ] **Step 7: Run the focused Windows extraction tests to verify they pass**

Run: `pytest tests/test_web_content_windows.py tests/test_web_content.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add host_pc/web_content.py host_pc/web_content_windows.py tests/test_web_content.py tests/test_web_content_windows.py
git commit -m "feat: add Windows live browser extraction scoring"
```

## Task 3: Add Filtered Focused/Window Fallbacks For Windows Browsers

**Files:**
- Modify: `host_pc/web_content_windows.py`
- Modify: `spark_app_v2.py`
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `tests/test_web_content_windows.py`

- [ ] **Step 1: Write the failing fallback-order and noise-filter tests**

```python
def test_windows_filtered_focused_fallback_rejects_browser_shell_noise():
    from host_pc import web_content_windows

    result = web_content_windows.score_focused_fallback(
        "Bookmarks Extensions Apps Profile Reload Forward Back"
    )

    assert result.is_useful is False


def test_poll_tick_uses_filtered_window_fallback_after_browser_failure(self):
    info = mock.Mock(app_name="chrome", pid=123, bundle_id="chrome.exe", title="Theo stream", process_name="chrome.exe")
    tab = types.SimpleNamespace(tab_title="Theo stream", url="")
    browser_result = BrowserExtractionResult(text="Bookmarks Extensions", source="live_tab", title=None, error=None, is_useful=False)
    # mock the Windows filtered focused fallback to return is_useful=False
    # mock the Windows filtered window fallback to return useful text
    # assert tracker.update gets the useful fallback text only.
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_web_content_windows.py tests/test_spark_panel_ui.py -q`
Expected: FAIL because filtered fallback helpers and poll-loop integration do not exist yet.

- [ ] **Step 3: Add filtered focused/window fallback helpers**

Implement small helpers in `host_pc/web_content_windows.py`, for example:

- `evaluate_focused_fallback(text)`
- `evaluate_window_fallback(text)`

Reuse the same noise/usefulness scoring rules instead of introducing a second incompatible heuristic path.

- [ ] **Step 4: Update the poll loop to use explicit browser usefulness results**

Modify `_on_poll_tick()` in `spark_app_v2.py` so the Windows browser flow:

- runs when `tab` exists even if `tab.url` is empty
- passes the poll-selected window identity into browser extraction
- treats browser text as accepted only when `browser_result.is_useful`
- runs the Windows filtered focused/window fallback helpers before persisting text
- still persists browser-derived text as `TextSource.WEB_CONTENT`

Make this an explicit hard switch from the current text-truthy behavior: noisy non-empty browser text must still fall through to the next fallback if `is_useful` is `False`.

- [ ] **Step 5: Add a concrete empty-URL browser poll regression**

In `tests/test_spark_panel_ui.py`, add a test where:

- `get_browser_tab(...)` returns metadata with `url=""`
- the active app is a supported Windows browser
- `web_extractor.extract_page(..., window_target=...)` is invoked anyway before any accessibility fallback
- if the live result is not useful, filtered fallback proceeds in order

This test must verify the full `extractor -> fallback` decision path for URL-less browser cases.

- [ ] **Step 6: Keep the source adapter boundary strict and test-locked**

Do not persist Windows internal extraction sub-sources into tracker/DB payloads. Map all browser-derived text back to the existing web/browser `TextSource` enum value.

Add an explicit regression proving persisted tracker-bound payloads still use canonical `TextSource.WEB_CONTENT` even if internal Windows extraction sources are `live_tab`, `uia_document`, or similar.

Also add a panel-level regression where the extractor returns non-empty but noisy text with `is_useful=False` and verify that polling continues into filtered fallback instead of accepting the noisy browser text.

- [ ] **Step 7: Run the focused fallback-order tests to verify they pass**

Run: `pytest tests/test_web_content_windows.py tests/test_spark_panel_ui.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add host_pc/web_content_windows.py spark_app_v2.py tests/test_spark_panel_ui.py tests/test_web_content_windows.py
git commit -m "fix: filter noisy Windows browser fallback text"
```

## Task 4: Add Poll-Target Binding And Final Regression Coverage

**Files:**
- Modify: `spark_app_v2.py`
- Modify: `host_pc/browser_windows.py`
- Modify: `host_pc/web_content.py`
- Modify: `tests/test_spark_panel_ui.py`
- Modify: `tests/test_web_content.py`

- [ ] **Step 1: Write the failing target-binding regression tests**

```python
def test_windows_browser_extraction_receives_selected_poll_target_identity(self):
    # assert the poll-selected window identity is passed into browser extraction


def test_poll_tick_drops_result_when_window_changes_before_browser_commit(self):
    # assert wrong-window browser content is never committed if the target changes mid-poll


def test_windows_browser_source_is_persisted_as_web_content_not_internal_source(self):
    # assert tracker/update payloads still use TextSource.WEB_CONTENT even when extractor returns source='uia_document'
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_spark_panel_ui.py tests/test_web_content.py -q`
Expected: FAIL because browser extraction is not yet bound to the selected poll target identity.

- [ ] **Step 3: Thread poll-selected window identity through the browser extraction path**

Update the relevant browser extraction entrypoint to accept the selected target identity explicitly, such as `WindowInfo` or equivalent lightweight poll target data. Keep this addition minimal and local to the Windows path.

- [ ] **Step 4: Re-verify fail-soft behavior and poll latency constraints**

Add tests proving:

- missing optional Windows UI libraries fail soft
- browser extraction timeouts/failures do not crash polling
- URL-less supported browser windows still attempt Windows live extraction when metadata exists
- content-region traversal respects time budgets and short-circuits under noisy UI trees

Lock these down with concrete tests in `tests/test_web_content_windows.py` rather than broad manual assertions.

Also add one focused panel-level regression in `tests/test_spark_panel_ui.py` that simulates a slow or hanging `web_extractor.extract_page(...)` call for a Windows browser window and asserts the poll loop still fails soft within its expected cadence, continuing to fallback or skip persistence safely without crashing.

- [ ] **Step 5: Run the full targeted regression set**

Run: `pytest tests/test_browser_windows.py tests/test_web_content.py tests/test_web_content_windows.py tests/test_spark_panel_ui.py -q`
Expected: PASS

- [ ] **Step 6: Manual smoke check on Windows browsers**

Run:

```powershell
.\.venv\Scripts\python.exe .\spark_app_v2.py
```

Manual checks:

- Chrome/Edge/Brave populate `url` more reliably than before
- authenticated or dynamic pages produce better browser rows when page content is available
- when live extraction fails, fallback rows no longer default to bookmark/plugin/browser-shell noise
- browser rows still reach the tracker and Jetson with the existing source semantics

- [ ] **Step 7: Commit**

```bash
git add host_pc/browser.py host_pc/browser_windows.py host_pc/browser_common.py host_pc/web_content.py host_pc/web_content_windows.py spark_app_v2.py tests/test_browser_windows.py tests/test_web_content.py tests/test_web_content_windows.py tests/test_spark_panel_ui.py
git commit -m "feat: improve Windows browser context extraction"
```
