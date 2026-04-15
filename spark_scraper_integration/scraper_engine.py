"""
scraper_engine.py — Unified content extraction hub.

Owns all routing and extraction so callers (spark_app_local, Spark UDFs, etc.)
only need to call extract() and get a consistent result dict back.

Routing strategy
────────────────
  URL                              Extractor
  ───────────────────────────────  ────────────────────────────────────────────
  docs.google.com/document/  +    Google Docs API  (structured, authoritative)
    credentials_json supplied
  docs.google.com/document/  +    AppleScript JS   (reads live DOM in browser)
    no credentials
  docs.google.com/spreadsheets/   AppleScript JS   (reads live Sheets grid)
  External http/https URL          trafilatura      (clean article extraction)
  localhost / file:// / no URL    AppleScript JS   (reads current browser tab)
  Native app (Word, Pages, …)     AppleScript JS   (best-effort DOM read)

AppleScript extraction works on macOS only and requires the content to be
open in a supported browser (Safari, Chrome, Chrome Canary).  It is
intentionally not called in Spark worker context — pure http/https URLs
always land on trafilatura.

Output schema (every call returns this shape)
─────────────────────────────────────────────
    {
        "url":     str,           # original input URL (or app_name for native)
        "source":  str,           # see SOURCE_* constants below
        "title":   str | None,
        "text":    str | None,    # None on failure
        "success": bool,
        "error":   str | None,    # None on success
    }
"""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── User-Agent rotation ───────────────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def _random_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }


# ── Source labels ─────────────────────────────────────────────────────────────

SOURCE_TRAFILATURA      = "trafilatura"
SOURCE_GOOGLE_DOCS_API  = "google_docs_api"
SOURCE_APPLESCRIPT_DOCS = "applescript_docs"
SOURCE_APPLESCRIPT_SHEETS = "applescript_sheets"
SOURCE_APPLESCRIPT_WEB  = "applescript_web"

SUPPORTED_BROWSERS = {"Safari", "Google Chrome", "Google Chrome Canary"}


# ── URL classifiers ───────────────────────────────────────────────────────────

_GDOC_PATTERN = re.compile(
    r"https://docs\.google\.com/document/d/(?P<doc_id>[A-Za-z0-9_\-]+)"
)


def _is_google_doc(url: str) -> bool:
    return bool(_GDOC_PATTERN.search(url))


def _is_google_sheets(url: str) -> bool:
    return "docs.google.com/spreadsheets/" in url


def _is_external_web(url: str) -> bool:
    """True for external http/https — excludes localhost and file:// URLs."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    local = ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    return not any(h in url for h in local)


def _extract_doc_id(url: str) -> str | None:
    m = _GDOC_PATTERN.search(url)
    return m.group("doc_id") if m else None


def route_url(url: str) -> str:
    """
    Classify a URL into an extraction route.

    Returns one of:
        "google_docs"    — docs.google.com/document (caller picks API vs AppleScript)
        "google_sheets"  — docs.google.com/spreadsheets → AppleScript
        "web"            — external http/https → trafilatura
        "local"          — everything else → AppleScript / native fallback
    """
    if not url:
        return "local"
    if _is_google_doc(url):
        return "google_docs"
    if _is_google_sheets(url):
        return "google_sheets"
    if _is_external_web(url):
        return "web"
    return "local"


# ── Result helpers ────────────────────────────────────────────────────────────

def _ok(url: str, source: str, text: str, title: str | None = None) -> dict[str, Any]:
    return {"url": url, "source": source, "title": title,
            "text": text, "success": True, "error": None}


def _err(url: str, source: str, message: str) -> dict[str, Any]:
    return {"url": url, "source": source, "title": None,
            "text": None, "success": False, "error": message}


# ── AppleScript / JS injection (macOS, live browser content) ──────────────────

# Google Docs: try multiple selectors in priority order.
# Primary strategy: same-origin XHR to the /export?format=txt endpoint.
# This works even when Docs uses canvas rendering (2023+), because the export
# URL is served from the same origin (docs.google.com) and the browser already
# holds the user's session cookies.  Synchronous XHR is deprecated but still
# supported in all major browsers for injected-script use.
# DOM selector strategies are kept as fallbacks for older Docs layouts.
_JS_GOOGLE_DOCS = (
    "(function(){"
    # 1. Same-origin export — works regardless of canvas vs DOM rendering mode
    "var m = window.location.pathname.match(/\\/d\\/([A-Za-z0-9_\\-]+)/);"
    "if (m) {"
    "  try {"
    "    var xhr = new XMLHttpRequest();"
    "    xhr.open('GET', 'https://docs.google.com/document/d/' + m[1] + '/export?format=txt', false);"
    "    xhr.send();"
    "    if (xhr.status === 200) {"
    "      var body = xhr.responseText.replace(/^\\uFEFF/, '').trim();"
    "      if (body.length > 0 && body.indexOf('<!DOCTYPE') !== 0) {"
    "        return body.slice(0, 8000);"
    "      }"
    "    }"
    "  } catch(e) {}"
    "}"
    # 2. Standard kix editor paragraphs (older / non-canvas layout)
    "var blocks = document.querySelectorAll('.kix-lineview-text-block');"
    "if (blocks.length > 0) {"
    "  return Array.from(blocks)"
    "    .map(function(el){return el.innerText;})"
    "    .filter(function(t){return t.trim().length > 0;})"
    "    .join('\\n');"
    "}"
    # 3. Screen-reader / accessibility mode
    "var srBlocks = document.querySelectorAll('[role=\"paragraph\"]');"
    "if (srBlocks.length > 0) {"
    "  return Array.from(srBlocks)"
    "    .map(function(el){return el.innerText;})"
    "    .filter(function(t){return t.trim().length > 0;})"
    "    .join('\\n');"
    "}"
    # 4. Paragraph renderer divs
    "var prBlocks = document.querySelectorAll('.kix-paragraphrenderer');"
    "if (prBlocks.length > 0) {"
    "  return Array.from(prBlocks)"
    "    .map(function(el){return el.innerText;})"
    "    .filter(function(t){return t.trim().length > 0;})"
    "    .join('\\n');"
    "}"
    # 5. Main content iframe
    "var iframe = document.querySelector('.docs-texteventtarget-iframe');"
    "if (iframe && iframe.contentDocument) {"
    "  return iframe.contentDocument.body.innerText || '';"
    "}"
    # 6. Named editor containers
    "var editor = document.querySelector('#kix-appview') || document.querySelector('#docs-editor') || document.querySelector('[data-doc-id]');"
    "if (editor) { return editor.innerText || ''; }"
    "return '';"
    "})()"
)

# Google Sheets: rendered cell grid
_JS_GOOGLE_SHEETS = (
    "(function(){"
    "var rows = Array.from(document.querySelectorAll('.waffle td'));"
    "return rows.map(function(td){return td.innerText;}).filter(Boolean).join(' | ');"
    "})()"
)

# General web / local app: strip to visible body text (capped at 8 KB)
_JS_GENERAL = (
    "(function(){"
    "var el = document.body;"
    "if (!el) return '';"
    "var text = el.innerText || el.textContent || '';"
    "return text.replace(/\\s{3,}/g, '\\n').trim().slice(0, 8000);"
    "})()"
)


def _escape_as(js: str) -> str:
    return js.replace("\\", "\\\\").replace('"', '\\"')


def _run_applescript(script: str, timeout: float = 3.0) -> Optional[str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return out if out else None
        logger.debug("[AS] error: %s", result.stderr.strip())
    except subprocess.TimeoutExpired:
        logger.warning("[AS] JS injection timed out (%.1fs)", timeout)
    except Exception as exc:
        logger.debug("[AS] failed: %s", exc)
    return None


def _run_js_in_browser(js: str, app_name: str) -> Optional[str]:
    """Inject JS into the frontmost tab of app_name via AppleScript."""
    if app_name == "Safari":
        script = (
            f'tell application "Safari" to '
            f'do JavaScript "{_escape_as(js)}" in current tab of front window'
        )
    else:
        script = (
            f'tell application "{app_name}" to '
            f'execute front window\'s active tab javascript "{_escape_as(js)}"'
        )
    return _run_applescript(script)


def extract_applescript(url: str, app_name: str) -> dict[str, Any]:
    """
    Extract content from the live browser tab using JavaScript injection.

    Best for:
      • Google Docs / Sheets open in a browser (reads live rendered DOM)
      • Local web apps (localhost, file://)
      • Native macOS apps with browser-based UI (Word Online, Notion, etc.)

    Requires app_name to be a supported browser and that content is
    currently open/visible in the frontmost tab.
    """
    if app_name not in SUPPORTED_BROWSERS:
        return _err(url or app_name, SOURCE_APPLESCRIPT_WEB,
                    f"{app_name!r} is not a supported browser for AppleScript injection")

    if _is_google_doc(url):
        js = _JS_GOOGLE_DOCS
        source = SOURCE_APPLESCRIPT_DOCS
    elif _is_google_sheets(url):
        js = _JS_GOOGLE_SHEETS
        source = SOURCE_APPLESCRIPT_SHEETS
    else:
        js = _JS_GENERAL
        source = SOURCE_APPLESCRIPT_WEB

    text = _run_js_in_browser(js, app_name)

    if not text or not text.strip():
        hint = ""
        if app_name == "Safari":
            hint = (
                " — to enable: Safari > Settings > Advanced > check "
                "'Show features for web developers', then Develop > "
                "'Allow JavaScript from Apple Events'"
            )
        logger.warning("[SCRAPER] AppleScript JS returned no text for %s%s", app_name, hint)
        return _err(url or app_name, source,
                    f"AppleScript JS injection returned no text{hint}")

    return _ok(url or app_name, source, text.strip())


# ── trafilatura (external web pages) ─────────────────────────────────────────

def extract_web(url: str) -> dict[str, Any]:
    """
    Fetch url and extract clean body text using trafilatura.

    Uses a random User-Agent to avoid simple bot-blocking, favor_precision=True
    to reduce noise, and checks HTTP status codes before attempting extraction.
    Strips headers, footers, nav menus, and boilerplate automatically.
    """
    try:
        import trafilatura
    except ImportError:
        return _err(url, SOURCE_TRAFILATURA, "trafilatura is not installed")

    # ── Fetch with requests so we control headers and can inspect status ──
    try:
        import requests
        resp = requests.get(url, headers=_random_headers(), timeout=15, allow_redirects=True)
    except requests.exceptions.Timeout:
        return _err(url, SOURCE_TRAFILATURA, "Request timed out (15 s)")
    except requests.exceptions.ConnectionError as exc:
        return _err(url, SOURCE_TRAFILATURA, f"Connection error: {exc}")
    except Exception as exc:
        return _err(url, SOURCE_TRAFILATURA, f"Fetch failed: {exc}")

    if resp.status_code == 404:
        return _err(url, SOURCE_TRAFILATURA, "Page not found (404)")
    if resp.status_code == 403:
        return _err(url, SOURCE_TRAFILATURA, "Access forbidden (403)")
    if resp.status_code >= 400:
        return _err(url, SOURCE_TRAFILATURA, f"HTTP error {resp.status_code}")

    resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text
    if not html:
        return _err(url, SOURCE_TRAFILATURA, "Page returned empty response")

    # ── Extract with precision settings ──────────────────────────────────
    try:
        text = trafilatura.extract(
            html,
            url=url,
            favor_precision=True,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        meta  = trafilatura.extract_metadata(html)
        title = meta.title if (text and meta) else None
    except Exception as exc:
        return _err(url, SOURCE_TRAFILATURA, f"Extraction failed: {exc}")

    if not text or not text.strip():
        return _err(url, SOURCE_TRAFILATURA, "Extraction returned no usable text")

    return _ok(url, SOURCE_TRAFILATURA, text.strip(), title)


# ── Google Docs API (structured, authoritative) ───────────────────────────────

def _parse_doc_body(body: dict) -> str:
    """Walk the Docs API response body and return plain text."""
    parts: list[str] = []

    def _visit(elements: list[dict]) -> None:
        for el in elements:
            if "paragraph" in el:
                line = "".join(
                    pe.get("textRun", {}).get("content", "")
                    for pe in el["paragraph"].get("elements", [])
                )
                if line.strip():
                    parts.append(line.rstrip("\n"))
            elif "table" in el:
                for row in el["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        _visit(cell.get("content", []))
            elif "tableOfContents" in el:
                _visit(el["tableOfContents"].get("content", []))

    _visit(body.get("content", []))
    return "\n".join(parts)


def extract_google_doc(url: str, credentials_json: str) -> dict[str, Any]:
    """
    Pull text from a Google Docs document using the official Docs API.

    credentials_json must be a JSON *string* (json.dumps of a service-account
    dict) so it stays serialisable across Spark workers.
    """
    doc_id = _extract_doc_id(url)
    if not doc_id:
        return _err(url, SOURCE_GOOGLE_DOCS_API,
                    f"Could not parse document ID from URL: {url}")

    try:
        import google.oauth2.service_account as sa
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        return _err(url, SOURCE_GOOGLE_DOCS_API,
                    "google-api-python-client / google-auth are not installed")

    try:
        creds_dict = json.loads(credentials_json)
        cred_type  = creds_dict.get("type", "")

        if cred_type == "authorized_user":
            from google.oauth2.credentials import Credentials as UserCredentials
            credentials = UserCredentials.from_authorized_user_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/documents.readonly"],
            )
        elif cred_type == "service_account":
            credentials = sa.Credentials.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/documents.readonly"],
            )
        else:
            return _err(url, SOURCE_GOOGLE_DOCS_API,
                        f"Unknown credential type: {cred_type!r}")
    except Exception as exc:
        return _err(url, SOURCE_GOOGLE_DOCS_API, f"Credentials error: {exc}")

    try:
        service = build("docs", "v1", credentials=credentials,
                        cache_discovery=False)
        doc = service.documents().get(documentId=doc_id).execute()
    except Exception as exc:   # catches HttpError + network errors
        msg = str(exc)
        if "403" in msg:
            msg = "Access denied — document is private or service account lacks permission"
        elif "404" in msg:
            msg = "Document not found (404)"
        return _err(url, SOURCE_GOOGLE_DOCS_API, msg)

    try:
        title = doc.get("title")
        text  = _parse_doc_body(doc.get("body", {}))
    except Exception as exc:
        return _err(url, SOURCE_GOOGLE_DOCS_API,
                    f"Failed to parse document body: {exc}")

    if not text.strip():
        return _err(url, SOURCE_GOOGLE_DOCS_API, "Document appears to be empty")

    return _ok(url, SOURCE_GOOGLE_DOCS_API, text.strip(), title)


# ── Browser extraction with HTTP fallback ────────────────────────────────────

def extract_with_fallback(
    url: str,
    app_name: str = "",
    credentials_json: str | None = None,
) -> dict[str, Any]:
    """
    Primary extraction for the SPARK app poll tick.

    Strategy:
        1. Try browser-based extraction (AppleScript/XHR injection or Docs API).
        2. If that fails and the URL is an external web page, fall back to a
           pure HTTP fetch via route_and_extract (random UA + trafilatura).
        3. Return the original error if both paths fail.

    Returns the same schema as extract():
        {url, source, title, text, success, error}
    """
    result = extract(url, app_name=app_name, credentials_json=credentials_json)

    if result["success"] and result["text"]:
        return result

    if route_url(url) == "web":
        logger.info("[SCRAPER] browser extraction failed, trying HTTP fallback for %s", url)
        fb = route_and_extract(url)
        if fb["status"] == "success" and fb["content"]:
            logger.info("[SCRAPER] HTTP fallback succeeded (%d chars)", len(fb["content"]))
            return _ok(url, SOURCE_TRAFILATURA, fb["content"], fb.get("title"))
        if fb["error"]:
            return _err(url, SOURCE_TRAFILATURA, f"HTTP fallback: {fb['error']}")

    return result


# ── Spark-compatible entry point ─────────────────────────────────────────────

def route_and_extract(url: str) -> dict[str, Any]:
    """
    Stateless, pure extraction function safe to use as a Spark UDF.

    Routes:
        docs.google.com/document  →  placeholder (API not yet integrated)
        all other http/https      →  trafilatura (high-precision extraction)
        empty / non-http          →  error

    Output schema:
        {
            "url":     str,
            "content": str | None,
            "title":   str | None,
            "status":  "success" | "error",
            "engine":  "trafilatura" | "placeholder",
            "error":   str | None,
        }
    """
    def _out(content, title, status, engine, error=None):
        return {"url": url, "content": content, "title": title,
                "status": status, "engine": engine, "error": error}

    if not url or not url.strip():
        return _out(None, None, "error", "none", "Empty URL")

    if _is_google_doc(url) or _is_google_sheets(url):
        return _out(
            None, None, "error", "placeholder",
            "[Google Docs/Sheets API not yet integrated]",
        )

    if not _is_external_web(url):
        return _out(None, None, "error", "none",
                    "URL is not a fetchable http/https address")

    result = extract_web(url)
    return _out(
        content=result["text"],
        title=result.get("title"),
        status="success" if result["success"] else "error",
        engine="trafilatura",
        error=result["error"],
    )


# ── Main entry point (SPARK app) ──────────────────────────────────────────────

def extract(
    url: str,
    app_name: str = "",
    credentials_json: str | None = None,
) -> dict[str, Any]:
    """
    Extract text from url, routing to the highest-quality extractor.

    Args:
        url:              The URL to extract from.
        app_name:         Active browser/app name (e.g. "Google Chrome").
                          Required for AppleScript routes; ignored for
                          trafilatura and Google Docs API routes.
        credentials_json: Service-account credentials as a JSON string.
                          Required only for Google Docs API route.
                          If omitted for a Google Docs URL, falls back to
                          AppleScript DOM extraction.

    Returns:
        Dict with keys: url, source, title, text, success, error.

    Routing summary:
        google_docs URL + credentials  → Google Docs API
        google_docs URL, no creds      → AppleScript (live browser DOM)
        google_sheets URL              → AppleScript (live Sheets grid)
        external http/https            → trafilatura
        localhost / file:// / native   → AppleScript (live browser DOM)
    """
    if not url or not url.strip():
        return _err(url or app_name or "", "none", "Empty URL")

    route = route_url(url)

    if route == "google_docs":
        if credentials_json:
            return extract_google_doc(url, credentials_json)
        # No credentials — fall back to live DOM via AppleScript
        return extract_applescript(url, app_name)

    if route == "google_sheets":
        return extract_applescript(url, app_name)

    if route == "web":
        return extract_web(url)

    # "local" — localhost, file://, no URL, native app
    return extract_applescript(url, app_name)
