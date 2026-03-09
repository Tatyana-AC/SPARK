"""
Browser tab detection via AppleScript.

Queries Safari and Google Chrome for the active tab's title and URL
using osascript subprocess calls.
"""

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

BROWSER_APPS = {"Safari", "Google Chrome", "Google Chrome Canary"}


@dataclass
class BrowserTabInfo:
    """Active browser tab metadata."""
    tab_title: str
    url: str


def _run_applescript(script: str, timeout: float = 2.0) -> Optional[str]:
    """Run an AppleScript and return its stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.debug("AppleScript timed out")
    except Exception as e:
        logger.debug(f"AppleScript failed: {e}")
    return None


def get_browser_tab(app_name: str) -> Optional[BrowserTabInfo]:
    """
    Get the active tab's title and URL for a supported browser.

    Args:
        app_name: The name of the active application (e.g. "Safari").

    Returns:
        BrowserTabInfo with tab_title and url, or None if the app
        is not a supported browser, has no open tabs, or isn't responding.
    """
    if app_name not in BROWSER_APPS:
        return None

    if app_name == "Safari":
        title = _run_applescript(
            'tell application "Safari" to get name of current tab of front window'
        )
        url = _run_applescript(
            'tell application "Safari" to get URL of current tab of front window'
        )
    else:
        # Google Chrome / Google Chrome Canary
        title = _run_applescript(
            f'tell application "{app_name}" to get title of active tab of front window'
        )
        url = _run_applescript(
            f'tell application "{app_name}" to get URL of active tab of front window'
        )

    if not title and not url:
        return None
    if app_name == "Google Chrome":
            url=url[:60]

    return BrowserTabInfo(
        tab_title=title or "",
        
        url=url or "",
    )
