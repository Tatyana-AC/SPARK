"""Browser tab text extraction helpers for host-side capture.

The extractor keeps a single API surface in this module and returns either a
structured result or just text via the backward-compatible wrapper.
"""

import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class BrowserExtractionResult:
    text: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    is_useful: bool = False
    quality_score: float = 0.0


SOURCE_GOOGLE_DOCS_LIVE = "google_docs_live"
SOURCE_GOOGLE_SHEETS_LIVE = "google_sheets_live"
SOURCE_LIVE_TAB = "live_tab"
SOURCE_HTTP_FALLBACK = "http_fallback"
SOURCE_NON_FETCHABLE = "non_fetchable"
SOURCE_UNSUPPORTED = "unsupported"
SUPPORTED_BROWSERS = {"Safari", "Google Chrome", "Google Chrome Canary"}


# ── JavaScript payloads ───────────────────────────────────────────────────────

_JS_GOOGLE_DOCS_EXPORT = (
    "(function(){"
    "var m = window.location.pathname.match(/\\/d\\/([A-Za-z0-9_-]+)/);"
    "if (m) {"
    "  try {"
    "    var xhr = new XMLHttpRequest();"
    "    xhr.open('GET', 'https://docs.google.com/document/d/' + m[1] + '/export?format=txt', false);"
    "    xhr.send();"
    "    if (xhr.status === 200) {"
    "      return (xhr.responseText || '').replace(/^\\uFEFF/, '').trim();"
    "    }"
    "  } catch (e) {}"
    "}"
    "return '';"
    "})()"
)

_JS_GOOGLE_DOCS_DOM_FALLBACK = (
    "(function(){"
    "var blocks = document.querySelectorAll('.kix-lineview-text-block');"
    "if (blocks.length > 0) {"
    "  return Array.from(blocks)"
    "    .map(function(el){return el.innerText;})"
    "    .filter(function(t){return t.trim().length > 0;})"
    "    .join('\\n');"
    "}"
    "var sr = document.querySelectorAll('[role=\"paragraph\"]');"
    "if (sr.length > 0) {"
    "  return Array.from(sr)"
    "    .map(function(el){return el.innerText;})"
    "    .filter(function(t){return t.trim().length > 0;})"
    "    .join('\\n');"
    "}"
    "var iframe = document.querySelector('.docs-texteventtarget-iframe');"
    "if (iframe && iframe.contentDocument) {"
    "  return iframe.contentDocument.body.innerText || '';"
    "}"
    "var editor = document.querySelector('#kix-appview') || document.querySelector('#docs-editor') || document.querySelector('[data-doc-id]');"
    "if (editor) { return editor.innerText || ''; }"
    "return '';"
    "})()"
)

_JS_GOOGLE_SHEETS = (
    "(function(){"
    "var rows = Array.from(document.querySelectorAll('.waffle td'));"
    "return rows.map(function(td){return td.innerText;}).filter(Boolean).join(' | ');"
    "})()"
)

_JS_GENERAL = (
    "(function(){"
    "var el = document.body;"
    "if (!el) return '';"
    "var text = el.innerText || el.textContent || '';"
    "return text.replace(/\\s{3,}/g, '\\n').trim().slice(0, 8000);"
    "})()"
)


# ── URL classifiers ───────────────────────────────────────────────────────────


def _is_google_docs(url: str) -> bool:
    return "docs.google.com/document/" in url


def _is_google_sheets(url: str) -> bool:
    return "docs.google.com/spreadsheets/" in url


def _is_external_web(url: str) -> bool:
    """Return True for fetchable web URLs and exclude localhost/loopback/file."""
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return False
    if host.startswith("127."):
        return False
    return True


def _is_supported_windows_browser(app_name: str) -> bool:
    try:
        from .browser_windows import _is_supported_browser
    except Exception:
        normalized = (app_name or "").strip().lower()
        if normalized.endswith(".exe"):
            normalized = normalized[:-4]
        return normalized in {"chrome", "msedge", "brave", "google chrome", "microsoft edge", "brave browser"}

    return _is_supported_browser(app_name)


def _is_supported_macos_browser(app_name: str) -> bool:
    return app_name in {"Safari", "Google Chrome", "Google Chrome Canary"}


def _prefer_http_article_text(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("wikipedia.org")


# ── Shared transport and helpers ─────────────────────────────────────────────


def _extract_http_text(url: str) -> BrowserExtractionResult:
    """Fetch and extract text from a normal external page using trafilatura."""
    try:
        import trafilatura
    except ImportError:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="trafilatura is not installed",
            is_useful=False,
            quality_score=0.0,
        )

    try:
        import requests
    except ModuleNotFoundError:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="requests is not installed",
            is_useful=False,
            quality_score=0.0,
        )

    try:
        response = requests.get(
            url,
            timeout=15,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
    except requests.exceptions.Timeout:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="Request timed out (15 s)",
            is_useful=False,
            quality_score=0.0,
        )
    except requests.exceptions.ConnectionError as exc:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error=f"Connection error: {exc}",
            is_useful=False,
            quality_score=0.0,
        )
    except Exception as exc:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error=f"Fetch failed: {exc}",
            is_useful=False,
            quality_score=0.0,
        )

    if response.status_code == 404:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="Page not found (404)",
            is_useful=False,
            quality_score=0.0,
        )
    if response.status_code == 403:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="Access forbidden (403)",
            is_useful=False,
            quality_score=0.0,
        )
    if response.status_code >= 400:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error=f"HTTP error {response.status_code}",
            is_useful=False,
            quality_score=0.0,
        )

    html = response.text or ""
    if not html:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="Page returned empty response",
            is_useful=False,
            quality_score=0.0,
        )

    try:
        text = trafilatura.extract(
            html,
            url=url,
            favor_precision=True,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
    except Exception as exc:
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error=f"Extraction failed: {exc}",
            is_useful=False,
            quality_score=0.0,
        )

    if not text or not text.strip():
        return BrowserExtractionResult(
            text=None,
            source=SOURCE_HTTP_FALLBACK,
            title=None,
            error="Extraction returned no usable text",
            is_useful=False,
            quality_score=0.0,
        )

    return BrowserExtractionResult(
        text=text.strip(),
        source=SOURCE_HTTP_FALLBACK,
        title=None,
        error=None,
        is_useful=True,
        quality_score=0.72,
    )


def _run_applescript(script: str, timeout: float) -> Optional[str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return out if out else None
        logger.debug("[WEB] AppleScript error: %s", result.stderr.strip())
    except subprocess.TimeoutExpired:
        logger.warning("[WEB] JS injection timed out (%.1fs)", timeout)
    except Exception as exc:
        logger.debug("[WEB] AppleScript failed: %s", exc)
    return None


def _escape_as(js: str) -> str:
    """Escape JavaScript text for AppleScript string embedding."""
    return js.replace("\\", "\\\\").replace('"', '\\"')


def _run_js_chrome(js: str, app_name: str, timeout: float = 3.0) -> Optional[str]:
    """Execute JS in the frontmost Chrome-family tab via AppleScript."""
    script = (
        f'tell application "{app_name}" to '
        f'execute front window\'s active tab javascript "{_escape_as(js)}"'
    )
    return _run_applescript(script, timeout)


def _run_js_safari(js: str, timeout: float = 3.0) -> Optional[str]:
    """Execute JS in the frontmost Safari tab via AppleScript."""
    script = (
        'tell application "Safari" to '
        'do JavaScript "' + _escape_as(js) + '" in current tab of front window'
    )
    return _run_applescript(script, timeout)


def _run_js_with_browser(js: str, app_name: str) -> Optional[str]:
    if app_name == "Safari":
        return _run_js_safari(js)
    return _run_js_chrome(js, app_name)


# ── Extractors ───────────────────────────────────────────────────────────────


def _has_useful_text(text: Optional[str]) -> bool:
    return bool(text and text.strip())


class WebContentExtractor:
    """Browser content extractor for live tabs and HTTP fallback."""

    def extract_page(
        self,
        url: str,
        app_name: str,
        platform: Optional[str] = None,
        window_target: Optional[int] = None,
    ) -> BrowserExtractionResult:
        if platform is None:
            platform = sys.platform

        if platform == "darwin":
            return self._extract_macos(url, app_name)
        if platform == "win32":
            return self._extract_windows(url, app_name, window_target=window_target)

        return BrowserExtractionResult(
            text=None,
            source=SOURCE_UNSUPPORTED,
            title=None,
            error=f"Browser text extraction is unsupported on platform {platform}",
            is_useful=False,
            quality_score=0.0,
        )

    def get_page_text(
        self,
        url: str,
        app_name: str,
        window_target: Optional[int] = None,
    ) -> Optional[str]:
        """Backward-compatible API returning only extracted text."""
        return self.extract_page(
            url,
            app_name,
            window_target=window_target,
        ).text

    def _extract_google_docs_live_text(
        self, url: str, app_name: str
    ) -> BrowserExtractionResult:
        export_result = self._run_js(_JS_GOOGLE_DOCS_EXPORT, app_name)
        if _has_useful_text(export_result):
            return BrowserExtractionResult(
                text=export_result.strip(),
                source=SOURCE_GOOGLE_DOCS_LIVE,
                title=None,
                error=None,
                is_useful=True,
                quality_score=0.95,
            )

        fallback_result = self._run_js(_JS_GOOGLE_DOCS_DOM_FALLBACK, app_name)
        if _has_useful_text(fallback_result):
            return BrowserExtractionResult(
                text=fallback_result.strip(),
                source=SOURCE_GOOGLE_DOCS_LIVE,
                title=None,
                error=None,
                is_useful=True,
                quality_score=0.86,
            )

        return BrowserExtractionResult(
            text=None,
            source=SOURCE_GOOGLE_DOCS_LIVE,
            title=None,
            error="Google Docs live extraction returned no usable text",
            is_useful=False,
            quality_score=0.0,
        )

    def _extract_macos(self, url: str, app_name: str) -> BrowserExtractionResult:
        if not _is_supported_macos_browser(app_name):
            return BrowserExtractionResult(
                text=None,
                source=SOURCE_UNSUPPORTED,
                title=None,
                error=f"{app_name!r} is not a supported browser for macOS extraction",
                is_useful=False,
                quality_score=0.0,
            )

        if _is_google_docs(url):
            return self._extract_google_docs_live_text(url, app_name)

        if _is_google_sheets(url):
            text = self._run_js(_JS_GOOGLE_SHEETS, app_name)
            if _has_useful_text(text):
                return BrowserExtractionResult(
                    text=text.strip(),
                    source=SOURCE_GOOGLE_SHEETS_LIVE,
                    title=None,
                    error=None,
                    is_useful=True,
                    quality_score=0.8,
                )
            return BrowserExtractionResult(
                text=None,
                source=SOURCE_GOOGLE_SHEETS_LIVE,
                title=None,
                error="Google Sheets live extraction returned no usable text",
                is_useful=False,
                quality_score=0.0,
            )

        live_text = self._run_js(_JS_GENERAL, app_name)
        if _has_useful_text(live_text):
            if _is_external_web(url):
                return BrowserExtractionResult(
                    text=live_text.strip(),
                    source=SOURCE_LIVE_TAB,
                    title=None,
                    error=None,
                    is_useful=True,
                    quality_score=0.76,
                )
            return BrowserExtractionResult(
                text=live_text.strip(),
                source=SOURCE_LIVE_TAB,
                title=None,
                error=None,
                is_useful=True,
                quality_score=0.76,
            )

        if _is_external_web(url):
            return _extract_http_text(url)

        return BrowserExtractionResult(
            text=live_text,
            source=SOURCE_LIVE_TAB,
            title=None,
            error="Live browser extraction returned no usable text",
            is_useful=False,
            quality_score=0.0,
        )

    def _extract_windows(
        self, url: str, app_name: str, window_target: Optional[int] = None
    ) -> BrowserExtractionResult:
        url = url or ""
        if not _is_supported_windows_browser(app_name):
            return BrowserExtractionResult(
                text=None,
                source=SOURCE_UNSUPPORTED,
                title=None,
                error=(
                    f"Windows browser extraction does not support "
                    f"app_name={app_name!r}"
                ),
                is_useful=False,
                quality_score=0.0,
            )

        from . import web_content_windows

        is_url_fetchable = _is_external_web(url)

        if not is_url_fetchable and url:
            return BrowserExtractionResult(
                text=None,
                source=SOURCE_NON_FETCHABLE,
                title=None,
                error=(
                    "Windows browser extraction does not fetch localhost, "
                    "loopback, or file URLs"
                ),
                is_useful=False,
                quality_score=0.0,
            )

        live_result = web_content_windows.extract_windows_live_tab_text(
            url,
            app_name,
            window_target=window_target,
        )

        if _prefer_http_article_text(url):
            http_result = _extract_http_text(url)
            if http_result and http_result.text and _has_useful_text(http_result.text):
                return http_result

        if not is_url_fetchable:
            if live_result and live_result.is_useful and live_result.text:
                return BrowserExtractionResult(
                    text=live_result.text,
                    source=live_result.source or SOURCE_LIVE_TAB,
                    title=None,
                    error=live_result.error,
                    is_useful=True,
                    quality_score=live_result.quality_score,
                )

            return BrowserExtractionResult(
                text=live_result.text if live_result else None,
                source=live_result.source if live_result else SOURCE_LIVE_TAB,
                title=None,
                error=live_result.error if live_result else None,
                is_useful=False,
                quality_score=(live_result.quality_score if live_result else 0.0),
            )

        if live_result and live_result.is_useful and live_result.text:
            return BrowserExtractionResult(
                text=live_result.text,
                source=live_result.source or SOURCE_LIVE_TAB,
                title=None,
                error=live_result.error,
                is_useful=True,
                quality_score=live_result.quality_score,
            )

        http_result = _extract_http_text(url)
        if http_result and http_result.text and _has_useful_text(http_result.text):
            return http_result

        return BrowserExtractionResult(
            text=live_result.text,
            source=live_result.source or SOURCE_LIVE_TAB,
            title=None,
            error=live_result.error,
            is_useful=False,
            quality_score=(
                live_result.quality_score if live_result else 0.0
            ),
        )

    def _run_js(self, js: str, app_name: str) -> Optional[str]:
        return _run_js_with_browser(js, app_name)


def extract_page(
    url: str,
    app_name: str,
    platform: Optional[str] = None,
    window_target: Optional[int] = None,
) -> BrowserExtractionResult:
    """Module-level API for one-shot extraction with optional platform override."""
    return WebContentExtractor().extract_page(
        url,
        app_name,
        platform=platform,
        window_target=window_target,
    )


def get_page_text(
    url: str,
    app_name: str,
    platform: Optional[str] = None,
    window_target: Optional[int] = None,
) -> Optional[str]:
    """Backward-compatible wrapper returning only extracted text."""
    return extract_page(
        url,
        app_name,
        platform=platform,
        window_target=window_target,
    ).text
