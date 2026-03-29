"""
Web content extractor for browser tabs.

Uses AppleScript to inject JavaScript into the active Safari or Chrome tab,
bypassing the AX accessibility tree which returns almost nothing for web pages.

Supported targets:
  - Google Docs  (docs.google.com/document/)
  - Google Sheets (docs.google.com/spreadsheets/)
  - General websites (document.body.innerText fallback)

Usage:
    from host_pc.web_content import WebContentExtractor
    extractor = WebContentExtractor()
    text = extractor.get_page_text(url="https://docs.google.com/...", app_name="Google Chrome")
"""

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# ── JavaScript payloads ───────────────────────────────────────────────────────

# Google Docs: paragraph text lives in .kix-lineview-text-block elements.
# Joining with \n preserves document structure.
_JS_GOOGLE_DOCS = (
    "Array.from(document.querySelectorAll('.kix-lineview-text-block'))"
    ".map(function(el){return el.innerText;})"
    ".filter(function(t){return t.trim().length > 0;})"
    ".join('\\n')"
)

# Google Sheets: visible cell values in the formula bar + rendered grid.
# Best effort — reads the active sheet's rendered text rows.
_JS_GOOGLE_SHEETS = (
    "(function(){"
    "var rows = Array.from(document.querySelectorAll('.waffle td'));"
    "return rows.map(function(td){return td.innerText;}).filter(Boolean).join(' | ');"
    "})()"
)

# General web page: strip to visible body text, collapse whitespace.
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


# ── AppleScript runners ───────────────────────────────────────────────────────

def _run_js_chrome(js: str, app_name: str, timeout: float = 3.0) -> Optional[str]:
    """Execute JS in the frontmost Chrome/Chromium tab via AppleScript."""
    script = (
        f'tell application "{app_name}" to '
        f'execute front window\'s active tab javascript "{_escape_as(js)}"'
    )
    return _run_applescript(script, timeout)


def _run_js_safari(js: str, timeout: float = 3.0) -> Optional[str]:
    """Execute JS in the frontmost Safari tab via AppleScript."""
    script = (
        f'tell application "Safari" to '
        f'do JavaScript "{_escape_as(js)}" in current tab of front window'
    )
    return _run_applescript(script, timeout)


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
    """Escape a JS string for embedding inside an AppleScript double-quoted string."""
    return js.replace("\\", "\\\\").replace('"', '\\"')


# ── Public interface ──────────────────────────────────────────────────────────

SUPPORTED_BROWSERS = {"Safari", "Google Chrome", "Google Chrome Canary"}


class WebContentExtractor:
    """
    Extracts page text from browser tabs via JavaScript injection.

    Call get_page_text() during the poll tick when the active app is a browser.
    Returns None if the app is not a supported browser or extraction fails.
    """

    def get_page_text(self, url: str, app_name: str) -> Optional[str]:
        """
        Extract visible text from the active browser tab.

        Args:
            url:      URL of the active tab (from BrowserTabInfo).
            app_name: Name of the browser app (e.g. "Google Chrome").

        Returns:
            Extracted text string, or None on failure.
        """
        if app_name not in SUPPORTED_BROWSERS:
            return None

        js = self._pick_js(url)
        text = self._run_js(js, app_name)

        if text:
            source_label = self._source_label(url)
            logger.debug("[WEB] %s — %d chars from %s", app_name, len(text), source_label)
        else:
            logger.debug("[WEB] No text returned for %s in %s", url[:60], app_name)

        return text

    # ── internals ────────────────────────────────────────────────────────────

    def _pick_js(self, url: str) -> str:
        if _is_google_docs(url):
            return _JS_GOOGLE_DOCS
        if _is_google_sheets(url):
            return _JS_GOOGLE_SHEETS
        return _JS_GENERAL

    def _run_js(self, js: str, app_name: str) -> Optional[str]:
        if app_name == "Safari":
            return _run_js_safari(js)
        return _run_js_chrome(js, app_name)

    def _source_label(self, url: str) -> str:
        if _is_google_docs(url):
            return "Google Docs"
        if _is_google_sheets(url):
            return "Google Sheets"
        return "web page"
