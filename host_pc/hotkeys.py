"""
Global hotkey manager for SPARK.

Listens for system-wide keyboard shortcuts using pynput and bridges
them to Qt signals so the main UI can react.
"""

import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard

logger = logging.getLogger(__name__)


class HotkeySignals(QObject):
    """Qt signal bridge — emitted from the pynput listener thread."""
    capture_triggered = pyqtSignal()
    release_triggered = pyqtSignal()
    toggle_triggered = pyqtSignal()


class GlobalHotkeyManager:
    """
    Manages global hotkeys via pynput and emits Qt signals.

    Default bindings:
        Cmd+Ctrl+C  →  capture_triggered
        Cmd+Ctrl+R  →  release_triggered
    """

    def __init__(self):
        self.signals = HotkeySignals()
        self._listener = None

    def start(self) -> None:
        """Start listening for global hotkeys in a daemon thread."""
        if self._listener is not None:
            return

        hotkeys = keyboard.GlobalHotKeys({
            '<cmd>+<ctrl>+c': self._on_capture,
            '<cmd>+<ctrl>+r': self._on_release,
            '<cmd>+<ctrl>+<space>': self._on_toggle,
        })
        hotkeys.daemon = True
        hotkeys.start()
        self._listener = hotkeys
        logger.info("Global hotkeys active  (Cmd+Ctrl+C = capture, Cmd+Ctrl+R = release, Cmd+Ctrl+Space = toggle)")

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("Global hotkeys stopped")

    # ── callbacks (run on pynput thread → emit Qt signal) ────

    def _on_capture(self) -> None:
        logger.debug("Hotkey: capture triggered")
        self.signals.capture_triggered.emit()

    def _on_release(self) -> None:
        logger.debug("Hotkey: release triggered")
        self.signals.release_triggered.emit()

    def _on_toggle(self) -> None:
        logger.debug("Hotkey: toggle triggered")
        self.signals.toggle_triggered.emit()
