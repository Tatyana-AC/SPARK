"""Windows browser metadata helpers.

Extracts lightweight browser metadata (tab title + URL) from the active window.
All Windows-specific imports are lazy so this module stays import-safe on
non-Windows environments.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


WINDOWS_BROWSER_ALIASES = {
    "chrome": "chrome",
    "msedge": "msedge",
    "brave": "brave",
}


def _load_windows_libraries() -> tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """Load Windows libraries on demand.

    Returns a tuple of (win32gui, win32process, Application), or None for any
    unavailable dependency.
    """

    try:
        import win32gui
        import win32process
        from pywinauto import Application

        return win32gui, win32process, Application
    except Exception as exc:  # pragma: no cover - exercised by unit tests
        logger.debug("Windows browser libraries unavailable: %s", exc)
        return None, None, None


def _connect_to_active_window():
    """Connect to the active window using pywinauto and return a wrapper."""

    win32gui, _, Application = _load_windows_libraries()
    if not win32gui or not Application:
        return None

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            logger.debug("No active window handle for browser metadata")
            return None

        app = Application(backend="uia")
        app.connect(handle=hwnd)
        window = app.window(handle=hwnd)
        if not window.exists():
            logger.debug("Active window disappeared while connecting for browser metadata")
            return None

        return window
    except Exception as exc:
        logger.debug("Failed to connect to active window: %s", exc)
        return None


def _control_text(control: Any) -> str:
    """Extract a short text value from a control if possible."""

    try:
        if hasattr(control, "get_value"):
            value = control.get_value()
            if isinstance(value, str):
                return value.strip()
    except Exception:
        pass

    try:
        value = control.window_text()
        if isinstance(value, str):
            return value.strip()
    except Exception:
        pass

    try:
        text_candidates = control.texts()
        if text_candidates:
            return text_candidates[0].strip()
    except Exception:
        pass

    return ""


def _is_browser_address(value: str) -> bool:
    lower = value.lower()
    return lower.startswith(
        ("http://", "https://", "file://", "chrome://", "edge://")
    )


def _find_address_bar(window: Any) -> Any:
    """Heuristically locate the browser address/search control."""

    if not window or not hasattr(window, "descendants"):
        return None

    candidate_controls = []
    try:
        candidate_controls.extend(window.descendants(control_type="Edit"))
    except Exception:
        pass
    try:
        candidate_controls.extend(window.descendants(control_type="ComboBox"))
    except Exception:
        pass

    if not candidate_controls:
        return None

    def name_like_address(control: Any) -> bool:
        try:
            name = ""
            raw_name = control.window_text()
            if isinstance(raw_name, str):
                name = raw_name.lower()
            if any(token in name for token in ("address", "search", "url")):
                return True
        except Exception:
            pass

        try:
            auto_id = ""
            element = control.element_info
            if element and hasattr(element, "automation_id"):
                auto_id = (element.automation_id() if callable(element.automation_id) else element.automation_id)
                if isinstance(auto_id, str) and any(
                    token in auto_id.lower() for token in ("address", "search", "url")
                ):
                    return True
        except Exception:
            pass

        control_value = _control_text(control)
        return _is_browser_address(control_value)

    for control in candidate_controls:
        if name_like_address(control):
            return control

    return candidate_controls[0] if candidate_controls else None


def _read_address_bar_url(address_bar: Any) -> Optional[str]:
    """Read URL text from an address-bar control."""

    if not address_bar:
        return None

    value = _control_text(address_bar)
    if value and _is_browser_address(value):
        return value

    return None


def _read_tab_title(window: Any) -> Optional[str]:
    """Read the active tab or window title from the wrapper."""

    if not window:
        return None

    try:
        return window.window_text().strip() or None
    except Exception:
        return None


def get_browser_tab(app_name: str) -> Optional["BrowserTabInfo"]:
    """Return active browser metadata for supported Windows browser processes."""

    normalized = (app_name or "").strip().lower()
    if normalized not in WINDOWS_BROWSER_ALIASES:
        return None

    window = _connect_to_active_window()
    if not window:
        return None

    url = None
    address_bar = _find_address_bar(window)
    if address_bar is not None:
        url = _read_address_bar_url(address_bar)

    tab_title = _read_tab_title(window)
    if not tab_title and not url:
        return None

    from .browser import BrowserTabInfo

    return BrowserTabInfo(tab_title=tab_title or "", url=url or "")
