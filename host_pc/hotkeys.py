"""
Global hotkey manager for SPARK.

Listens for system-wide keyboard shortcuts using pynput and bridges
them to Qt signals so the main UI can react.
"""

import logging
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard

logger = logging.getLogger(__name__)


def get_hotkey_config(platform: str | None = None) -> dict[str, str]:
    """Return default hotkeys for the current platform."""
    platform = platform or sys.platform

    if platform.startswith("win"):
        return {
            "capture_combo": "<cmd>+<alt>+c",
            "release_combo": "<cmd>+<alt>+v",
            "toggle_combo": "<cmd>+<alt>+<space>",
            "capture_label": "Win+Alt+C",
            "release_label": "Win+Alt+V",
            "toggle_label": "Win+Alt+Space",
        }

    return {
        "capture_combo": "<cmd>+<ctrl>+c",
        "release_combo": "<cmd>+<ctrl>+r",
        "toggle_combo": "<cmd>+<ctrl>+<space>",
        "capture_label": "Cmd+Ctrl+C",
        "release_label": "Cmd+Ctrl+R",
        "toggle_label": "Cmd+Ctrl+Space",
    }


class HotkeySignals(QObject):
    """Qt signal bridge emitted from the pynput listener thread."""

    capture_triggered = pyqtSignal()
    release_triggered = pyqtSignal()
    toggle_triggered = pyqtSignal()


class GlobalHotkeyManager:
    """
    Manages global hotkeys via pynput and emits Qt signals.

    Default bindings vary by platform:
        macOS: Cmd+Ctrl+C / Cmd+Ctrl+R / Cmd+Ctrl+Space
        Windows: Win+Alt+C / Win+Alt+V / Win+Alt+Space
    """

    def __init__(self):
        self.signals = HotkeySignals()
        self._listener = None
        self._hotkey_config = get_hotkey_config()

    def start(self) -> None:
        """Start listening for global hotkeys in a daemon thread."""
        if self._listener is not None:
            return

        hotkeys = keyboard.GlobalHotKeys(
            {
                self._hotkey_config["capture_combo"]: self._on_capture,
                self._hotkey_config["release_combo"]: self._on_release,
                self._hotkey_config["toggle_combo"]: self._on_toggle,
            }
        )
        hotkeys.daemon = True
        hotkeys.start()
        self._listener = hotkeys
        logger.info(
            "Global hotkeys active (%s = capture, %s = release, %s = toggle)",
            self._hotkey_config["capture_label"],
            self._hotkey_config["release_label"],
            self._hotkey_config["toggle_label"],
        )

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("Global hotkeys stopped")

    def _on_capture(self) -> None:
        logger.debug("Hotkey: capture triggered")
        self.signals.capture_triggered.emit()

    def _on_release(self) -> None:
        logger.debug("Hotkey: release triggered")
        self.signals.release_triggered.emit()

    def _on_toggle(self) -> None:
        logger.debug("Hotkey: toggle triggered")
        self.signals.toggle_triggered.emit()
