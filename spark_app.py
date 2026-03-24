"""
SPARK — Full Pipeline Application

Capture text from any application, process it, and paste it back.

Hotkeys (global, work from any app):
    macOS: Cmd+Ctrl+C / Cmd+Ctrl+R
    Windows: Win+Alt+C / Win+Alt+V
"""

import os
import sys
import time
import logging

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame,
    QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

sys.path.insert(0, '/Users/tatyanacruz/Documents/Spring 26/SPARK')

from host_pc.accessibility import AccessibilityManager
from host_pc.accessibility.base import TextSource
from host_pc.accessibility.tracker import WindowContextTracker
from host_pc.browser import get_browser_tab
from host_pc.db import SparkDB
from host_pc.hotkeys import GlobalHotkeyManager, get_hotkey_config
from host_pc.hid import KeyboardHIDManager
from host_pc.hid.keyboard_hid import STATUS_PROCESSING, STATUS_DONE, STATUS_ERROR

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

HOTKEY_CONFIG = get_hotkey_config()
CAPTURE_HOTKEY_LABEL = HOTKEY_CONFIG["capture_label"]
RELEASE_HOTKEY_LABEL = HOTKEY_CONFIG["release_label"]

# ── Palette ───────────────────────────────────────────────────
BG          = "#1a1b26"   # deep navy
SURFACE     = "#24283b"   # card background
SURFACE_ALT = "#1f2335"   # slightly darker variant
BORDER      = "#3b3f54"   # subtle border
TEXT        = "#c0caf5"   # primary text
TEXT_DIM    = "#565f89"   # muted text
ACCENT      = "#7aa2f7"   # blue accent
ACCENT_HOVER = "#89b4fa"
GREEN       = "#9ece6a"   # success
GREEN_HOVER = "#a9d675"
RED         = "#f7768e"   # error / stop
RED_HOVER   = "#f9899d"
ORANGE      = "#e0af68"   # warning / in-progress
PURPLE      = "#bb9af7"   # capture
PURPLE_HOVER = "#c4a7f7"


def _card(widget: QWidget) -> None:
    """Apply card styling + drop shadow to a QFrame."""
    widget.setStyleSheet(f"""
        QFrame {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 10px;
        }}
    """)
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(18)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(0, 0, 0, 60))
    widget.setGraphicsEffect(shadow)


class SparkPipeline(QMainWindow):
    """Main pipeline window: Capture → Process → Release."""

    POLL_INTERVAL = 2000  # ms

    def __init__(self):
        super().__init__()
        self.manager      = AccessibilityManager()
        self.hotkeys      = GlobalHotkeyManager()
        self.keyboard_hid = KeyboardHIDManager()

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spark.db")
        self.db = SparkDB(db_path)
        self.tracker = WindowContextTracker(db=self.db)

        self.captured_text: str = ""
        self.processed_text: str = ""
        self.is_polling = False

        self._init_ui()
        self._connect_hotkeys()
        self._connect_keyboard_hid()
        self.hotkeys.start()
        self.keyboard_hid.start()

        self.poll_timer = QTimer()
        self.poll_timer.setInterval(self.POLL_INTERVAL)
        self.poll_timer.timeout.connect(self._on_poll_tick)

    # ── UI ────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        self.setWindowTitle("SPARK")
        self.setGeometry(200, 80, 660, 960)

        central = QWidget()
        central.setStyleSheet(f"background-color: {BG};")
        root = QVBoxLayout()
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(16)

        # ── Header ───────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("SPARK")
        title.setFont(self._font(20, bold=True))
        title.setStyleSheet(f"color: {ACCENT}; letter-spacing: 3px;")
        header.addWidget(title)

        subtitle = QLabel("Capture  /  Process  /  Release")
        subtitle.setFont(self._font(10))
        subtitle.setStyleSheet(f"color: {TEXT_DIM};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignBottom)
        header.addWidget(subtitle)
        header.addStretch()
        root.addLayout(header)

        # Status pill
        self.status_label = QLabel(f"Ready - select text in any app, then {CAPTURE_HOTKEY_LABEL}")
        self.status_label.setFont(self._font(9))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_DIM};
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 6px 12px;
            }}
        """)
        root.addWidget(self.status_label)

        # HID connection pill
        self.hid_status_label = QLabel("● Keyboard  disconnected")
        self.hid_status_label.setFont(self._font(9))
        self.hid_status_label.setStyleSheet(f"""
            QLabel {{
                color: {RED};
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 6px 12px;
            }}
        """)
        root.addWidget(self.hid_status_label)

        # ── Live Context card ────────────────────────────────
        poll_card = QFrame()
        _card(poll_card)
        poll_lay = QVBoxLayout()
        poll_lay.setContentsMargins(14, 12, 14, 12)
        poll_lay.setSpacing(8)

        poll_header = QHBoxLayout()
        poll_title = QLabel("LIVE CONTEXT")
        poll_title.setFont(self._font(9, bold=True))
        poll_title.setStyleSheet(f"color: {TEXT_DIM}; letter-spacing: 1.5px; border: none;")
        poll_header.addWidget(poll_title)
        poll_header.addStretch()

        self.poll_toggle_btn = QPushButton("Start Polling")
        self._style_pill_button(self.poll_toggle_btn, ACCENT, ACCENT_HOVER)
        self.poll_toggle_btn.clicked.connect(self._on_toggle_polling)
        poll_header.addWidget(self.poll_toggle_btn)
        poll_lay.addLayout(poll_header)

        # Info row
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        for label_text, attr in [("App", "app_name_label"), ("Source", "source_label")]:
            prefix = QLabel(label_text)
            prefix.setFont(self._font(8))
            prefix.setStyleSheet(f"color: {TEXT_DIM}; border: none;")
            value = QLabel("—")
            value.setFont(self._font(9, bold=True))
            value.setStyleSheet(f"color: {TEXT}; border: none;")
            setattr(self, attr, value)
            info_row.addWidget(prefix)
            info_row.addWidget(value)
        info_row.addStretch()
        poll_lay.addLayout(info_row)

        win_row = QHBoxLayout()
        win_prefix = QLabel("Window")
        win_prefix.setFont(self._font(8))
        win_prefix.setStyleSheet(f"color: {TEXT_DIM}; border: none;")
        self.window_title_label = QLabel("—")
        self.window_title_label.setFont(self._font(9))
        self.window_title_label.setStyleSheet(f"color: {TEXT}; border: none;")
        self.window_title_label.setWordWrap(True)
        win_row.addWidget(win_prefix)
        win_row.addWidget(self.window_title_label, 1)
        poll_lay.addLayout(win_row)

        self.poll_preview = QTextEdit()
        self.poll_preview.setReadOnly(True)
        self.poll_preview.setPlaceholderText("Start polling to see live text…")
        self.poll_preview.setMinimumHeight(50)
        self.poll_preview.setMaximumHeight(100)
        self.poll_preview.setFont(self._font(9))
        self.poll_preview.setStyleSheet(self._textedit_style(SURFACE_ALT))
        poll_lay.addWidget(self.poll_preview)

        poll_card.setLayout(poll_lay)
        root.addWidget(poll_card)

        # ── Window History card ─────────────────────────────
        hist_card = QFrame()
        _card(hist_card)
        hist_lay = QVBoxLayout()
        hist_lay.setContentsMargins(14, 12, 14, 12)
        hist_lay.setSpacing(6)

        hist_title = QLabel("WINDOW HISTORY")
        hist_title.setFont(self._font(9, bold=True))
        hist_title.setStyleSheet(f"color: {TEXT_DIM}; letter-spacing: 1.5px; border: none;")
        hist_lay.addWidget(hist_title)

        # Two slots for previous windows
        self._history_rows = []
        for i in range(2):
            row_frame = QFrame()
            row_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {SURFACE_ALT};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                }}
            """)
            row_lay = QVBoxLayout()
            row_lay.setContentsMargins(10, 8, 10, 8)
            row_lay.setSpacing(4)

            app_label = QLabel("—")
            app_label.setFont(self._font(9, bold=True))
            app_label.setStyleSheet(f"color: {TEXT_DIM}; border: none;")
            row_lay.addWidget(app_label)

            win_label = QLabel("")
            win_label.setFont(self._font(8))
            win_label.setStyleSheet(f"color: {TEXT_DIM}; border: none;")
            win_label.setWordWrap(True)
            row_lay.addWidget(win_label)

            preview_label = QLabel("")
            preview_label.setFont(self._font(8))
            preview_label.setStyleSheet(f"color: {TEXT_DIM}; border: none;")
            preview_label.setWordWrap(True)
            preview_label.setMaximumHeight(36)
            row_lay.addWidget(preview_label)

            row_frame.setLayout(row_lay)
            hist_lay.addWidget(row_frame)
            self._history_rows.append({
                "frame": row_frame,
                "app": app_label,
                "window": win_label,
                "preview": preview_label,
            })

        hist_card.setLayout(hist_lay)
        root.addWidget(hist_card)

        # ── Captured Text card ───────────────────────────────
        cap_card = QFrame()
        _card(cap_card)
        cap_lay = QVBoxLayout()
        cap_lay.setContentsMargins(14, 12, 14, 12)
        cap_lay.setSpacing(8)

        cap_label = QLabel("CAPTURED TEXT")
        cap_label.setFont(self._font(9, bold=True))
        cap_label.setStyleSheet(f"color: {TEXT_DIM}; letter-spacing: 1.5px; border: none;")
        cap_lay.addWidget(cap_label)

        self.captured_display = QTextEdit()
        self.captured_display.setReadOnly(True)
        self.captured_display.setPlaceholderText("Text captured from another app will appear here…")
        self.captured_display.setMinimumHeight(80)
        self.captured_display.setMaximumHeight(140)
        self.captured_display.setFont(self._font(10))
        self.captured_display.setStyleSheet(self._textedit_style(SURFACE_ALT))
        cap_lay.addWidget(self.captured_display)

        cap_card.setLayout(cap_lay)
        root.addWidget(cap_card)

        # ── Processed Text card ──────────────────────────────
        proc_card = QFrame()
        _card(proc_card)
        proc_lay = QVBoxLayout()
        proc_lay.setContentsMargins(14, 12, 14, 12)
        proc_lay.setSpacing(8)

        proc_label = QLabel("PROCESSED TEXT")
        proc_label.setFont(self._font(9, bold=True))
        proc_label.setStyleSheet(f"color: {TEXT_DIM}; letter-spacing: 1.5px; border: none;")
        proc_lay.addWidget(proc_label)

        self.processed_display = QTextEdit()
        self.processed_display.setReadOnly(True)
        self.processed_display.setPlaceholderText("Processed result will appear here…")
        self.processed_display.setMinimumHeight(80)
        self.processed_display.setMaximumHeight(140)
        self.processed_display.setFont(self._font(10))
        self.processed_display.setStyleSheet(self._textedit_style(SURFACE_ALT))
        proc_lay.addWidget(self.processed_display)

        proc_card.setLayout(proc_lay)
        root.addWidget(proc_card)

        # ── Action buttons ───────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.capture_btn = QPushButton(f"Capture   {CAPTURE_HOTKEY_LABEL}")
        self._style_action_button(self.capture_btn, PURPLE, PURPLE_HOVER)
        self.capture_btn.clicked.connect(self._on_capture)
        btn_row.addWidget(self.capture_btn)

        self.release_btn = QPushButton(f"Release   {RELEASE_HOTKEY_LABEL}")
        self.release_btn.setEnabled(False)
        self._style_action_button(self.release_btn, GREEN, GREEN_HOVER)
        self.release_btn.clicked.connect(self._on_release)
        btn_row.addWidget(self.release_btn)

        root.addLayout(btn_row)

        # ── Hotkey hint ──────────────────────────────────────
        hint = QLabel("Hotkeys work globally — even when SPARK is in the background")
        hint.setFont(self._font(8))
        hint.setStyleSheet(f"color: {TEXT_DIM};")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hint)

        root.addStretch()
        central.setLayout(root)
        self.setCentralWidget(central)

    # ── Hotkey wiring ─────────────────────────────────────────

    def _connect_hotkeys(self) -> None:
        self.hotkeys.signals.capture_triggered.connect(self._on_capture)
        self.hotkeys.signals.release_triggered.connect(self._on_release)

    # ── Keyboard HID wiring ───────────────────────────────────

    def _connect_keyboard_hid(self) -> None:
        self.keyboard_hid.signals.capture_triggered.connect(self._on_capture)
        self.keyboard_hid.signals.release_triggered.connect(self._on_release)
        self.keyboard_hid.signals.connected_changed.connect(self._on_hid_connected)

    def _on_hid_connected(self, connected: bool) -> None:
        if connected:
            self.hid_status_label.setText("● Keyboard  connected")
            self.hid_status_label.setStyleSheet(f"""
                QLabel {{
                    color: {GREEN};
                    background-color: {SURFACE};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    padding: 6px 12px;
                }}
            """)
        else:
            self.hid_status_label.setText("● Keyboard  disconnected")
            self.hid_status_label.setStyleSheet(f"""
                QLabel {{
                    color: {RED};
                    background-color: {SURFACE};
                    border: 1px solid {BORDER};
                    border-radius: 6px;
                    padding: 6px 12px;
                }}
            """)

    # ── Polling ────────────────────────────────────────────────

    def _on_toggle_polling(self) -> None:
        if self.is_polling:
            self.poll_timer.stop()
            self.is_polling = False
            self.poll_toggle_btn.setText("Start Polling")
            self._style_pill_button(self.poll_toggle_btn, ACCENT, ACCENT_HOVER)
        else:
            self.is_polling = True
            self.poll_toggle_btn.setText("Stop Polling")
            self._style_pill_button(self.poll_toggle_btn, RED, RED_HOVER)
            self.poll_timer.start()
            self._on_poll_tick()

    def _on_poll_tick(self) -> None:
        info = self.manager.get_active_window_info()
        if not info:
            self.app_name_label.setText("—")
            self.window_title_label.setText("—")
            self.source_label.setText("—")
            self.poll_preview.clear()
            return

        # Browser tab detection
        tab = get_browser_tab(info.app_name)

        self.app_name_label.setText(info.app_name)
        if tab and tab.tab_title:
            self.window_title_label.setText(f"{tab.tab_title}\n{tab.url}")
        else:
            self.window_title_label.setText(info.title)

        text = None
        source = None
        try:
            text = self.manager.get_focused_element_text()
            if text:
                source = TextSource.FOCUSED_ELEMENT
        except Exception:
            pass

        if not text:
            try:
                text = self.manager.get_window_text()
                if text:
                    source = TextSource.FULL_WINDOW
            except Exception:
                pass

        if text and text.strip() and source:
            self.source_label.setText(source.value.replace("_", " ").title())
            preview = text[:4000] + ("…" if len(text) > 4000 else "")
            self.poll_preview.setPlainText(preview)
            self.tracker.update(info, text, source, tab=tab)
        else:
            self.source_label.setText("—")
            self.poll_preview.clear()

        self._refresh_history_ui()

    def _refresh_history_ui(self) -> None:
        """Update the WINDOW HISTORY card with previous window snapshots."""
        previous = self.tracker.get_all_previous()
        for i, row in enumerate(self._history_rows):
            if i < len(previous):
                snap = previous[i]
                row["app"].setText(snap.window_info.app_name)
                if snap.url:
                    row["window"].setText(snap.url)
                else:
                    row["window"].setText(snap.window_info.title)
                text_preview = snap.text[:120] + ("…" if len(snap.text) > 120 else "")
                row["preview"].setText(text_preview)
                row["app"].setStyleSheet(f"color: {TEXT}; border: none;")
            else:
                row["app"].setText("—")
                row["window"].setText("")
                row["preview"].setText("")
                row["app"].setStyleSheet(f"color: {TEXT_DIM}; border: none;")

    # ── Actions ───────────────────────────────────────────────

    def _on_capture(self) -> None:
        self._set_status("Capturing selection…", ORANGE)
        QTimer.singleShot(200, self._do_capture)

    def _do_capture(self) -> None:
        self.keyboard_hid.send_status(STATUS_PROCESSING)
        text = self.manager.get_selected_text()
        if text and text.strip():
            self.captured_text = text
            self.captured_display.setPlainText(text)

            self.processed_text = "Hello World " + text
            self.processed_display.setPlainText(self.processed_text)
            self.release_btn.setEnabled(True)

            self._set_status(
                f"Captured {len(text)} chars - {RELEASE_HOTKEY_LABEL} to paste back",
                GREEN,
            )
            self.keyboard_hid.send_status(STATUS_DONE)
        else:
            self._set_status("No text selected — highlight text first, then capture", RED)
            self.keyboard_hid.send_status(STATUS_ERROR)

    def _on_release(self) -> None:
        if not self.processed_text:
            self._set_status("Nothing to release — capture text first", RED)
            return
        self._set_status("Releasing text…", ORANGE)
        QTimer.singleShot(200, self._do_release)

    def _do_release(self) -> None:
        self.keyboard_hid.send_status(STATUS_PROCESSING)
        ok = self.manager.paste_text(self.processed_text)
        if ok:
            self._set_status("Text pasted back into application", GREEN)
            self.keyboard_hid.send_status(STATUS_DONE)
        else:
            self._set_status("Paste failed — make sure a text field is focused", RED)
            self.keyboard_hid.send_status(STATUS_ERROR)

    # ── Helpers ───────────────────────────────────────────────

    def _set_status(self, text: str, color: str = TEXT_DIM) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 6px 12px;
            }}
        """)

    @staticmethod
    def _font(size: int, bold: bool = False) -> QFont:
        f = QFont("SF Pro Text", size)
        if bold:
            f.setWeight(QFont.Weight.DemiBold)
        return f

    @staticmethod
    def _style_pill_button(btn: QPushButton, color: str, hover: str) -> None:
        btn.setFixedHeight(26)
        btn.setMaximumWidth(120)
        btn.setFont(QFont("SF Pro Text", 8, QFont.Weight.DemiBold))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {color};
                border: 1px solid {color};
                border-radius: 13px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                background-color: {color};
                color: {BG};
            }}
        """)

    @staticmethod
    def _style_action_button(btn: QPushButton, color: str, hover: str) -> None:
        btn.setMinimumHeight(42)
        btn.setFont(QFont("SF Pro Text", 10, QFont.Weight.DemiBold))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: {BG};
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:disabled {{
                background-color: {BORDER};
                color: {TEXT_DIM};
            }}
        """)

    @staticmethod
    def _textedit_style(bg: str) -> str:
        return f"""
            QTextEdit {{
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px;
                background-color: {bg};
                color: {TEXT};
                selection-background-color: {ACCENT};
                selection-color: {BG};
            }}
            QTextEdit[readOnly="true"] {{
                border: 1px solid {BORDER};
            }}
        """

    # ── Cleanup ───────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self.poll_timer.stop()
        self.hotkeys.stop()
        self.keyboard_hid.stop()
        self.db.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = SparkPipeline()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

