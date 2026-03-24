"""
SPARK — Full Pipeline Application (v2: SPARK Panel UI)

Capture text from any application, process it, and paste it back.

Hotkeys (global, work from any app):
    macOS: Cmd+Ctrl+C / Cmd+Ctrl+R
    Windows: Win+Alt+C / Win+Alt+V
"""

import os
import sys
import logging
import threading
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QWidget, QFrame,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QSizePolicy,
    QSystemTrayIcon, QMenu,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPainter, QPainterPath, QCursor, QIcon, QPixmap

sys.path.insert(0, '/Users/tatyanacruz/Documents/Spring 26/SPARK')

from host_pc.accessibility import AccessibilityManager
from host_pc.accessibility.base import TextSource
from host_pc.accessibility.tracker import WindowContextTracker
from host_pc.browser import get_browser_tab
from host_pc.db import SparkDB
from host_pc.hotkeys import GlobalHotkeyManager, get_hotkey_config
from host_pc.raw_hid import SparkHIDClient, AppCommand, SparkProtocolError
from host_pc.release_output import format_release_output
from host_pc.serial_sender import SerialSender
from host_pc.live_capture import LiveCaptureFeed

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

HOTKEY_CONFIG = get_hotkey_config()
CAPTURE_HOTKEY_LABEL = HOTKEY_CONFIG["capture_label"]
RELEASE_HOTKEY_LABEL = HOTKEY_CONFIG["release_label"]

# ── Palette (matches your existing palette) ───────────────────
BG           = "#111827"
SURFACE      = "#1A2234"
SURFACE_ALT  = "#0F172A"
BORDER       = "#1F2D42"
BORDER_LIT   = "#334155"
TEXT         = "#F9FAFB"
TEXT_DIM     = "#6B7280"
TEXT_MID     = "#D1D5DB"
ACCENT       = "#7aa2f7"
GREEN        = "#10B981"
GREEN_DIM    = "rgba(16,185,129,0.15)"
GREEN_BORDER = "rgba(16,185,129,0.35)"
CAPTURE_BG   = "#0A1A12"
CAPTURE_BORDER = "#14532D"
ORANGE       = "#e0af68"
RED          = "#f7768e"
PURPLE       = "#bb9af7"


# ── Stylesheet ────────────────────────────────────────────────
QSS = f"""
QWidget#root {{
    background-color: {BG};
    border-radius: 18px;
}}
QWidget {{
    font-family: 'SF Pro Text', -apple-system, 'Helvetica Neue', sans-serif;
}}
QLabel#section_label {{
    color: {TEXT_DIM};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    background: transparent;
}}
QLabel#app_title {{
    color: {TEXT};
    font-size: 22px;
    font-weight: 800;
    background: transparent;
}}
QLabel#app_subtitle {{
    color: {TEXT_DIM};
    font-size: 12px;
    background: transparent;
}}
QFrame#divider {{
    background-color: {SURFACE};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QFrame#context_card {{
    background-color: {SURFACE};
    border-radius: 10px;
    border: 1px solid {BORDER};
}}
QFrame#context_card:hover {{
    background-color: #1E293B;
    border: 1px solid {BORDER_LIT};
}}
QLabel#card_title {{
    color: {TEXT_MID};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
QLabel#card_title_active {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}
QLabel#card_subtitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    background: transparent;
}}
QLabel#active_badge {{
    background-color: {GREEN_DIM};
    color: {GREEN};
    font-size: 10px;
    font-weight: 700;
    border-radius: 8px;
    padding: 2px 9px;
    border: 1px solid {GREEN_BORDER};
}}
QFrame#capture_frame {{
    background-color: {CAPTURE_BG};
    border-radius: 10px;
    border: 1px solid {CAPTURE_BORDER};
}}
QLabel#capture_text {{
    color: #22C55E;
    font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
    font-size: 11px;
    background: transparent;
    padding: 4px;
}}
QLabel#live_dot {{
    color: {GREEN};
    font-size: 11px;
    font-weight: 700;
    background: transparent;
}}
QLabel#status_label {{
    color: {TEXT_DIM};
    font-size: 11px;
    background: transparent;
    padding: 2px;
}}
QPushButton#action_btn {{
    background-color: {SURFACE};
    border-radius: 10px;
    border: 1px solid {BORDER};
    text-align: left;
    padding: 12px 14px;
    color: {TEXT};
}}
QPushButton#action_btn:hover {{
    background-color: #1E293B;
    border: 1px solid {BORDER_LIT};
}}
QPushButton#action_btn:pressed {{
    background-color: {SURFACE_ALT};
}}
QPushButton#action_btn:disabled {{
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
}}
QLabel#btn_title {{
    color: {TEXT_MID};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}
QLabel#btn_subtitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    background: transparent;
}}
QLabel#close_btn {{
    color: #374151;
    font-size: 14px;
    background: transparent;
    padding: 2px 6px;
}}
QLabel#close_btn:hover {{
    color: #9CA3AF;
}}
QLabel#device_dot {{
    font-size: 10px;
    font-weight: 700;
    background: transparent;
    padding: 2px 6px;
}}
QPushButton#poll_toggle {{
    background-color: transparent;
    color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 10px;
    font-size: 10px;
    font-weight: 700;
    padding: 3px 12px;
}}
QPushButton#poll_toggle:hover {{
    background-color: {ACCENT};
    color: {BG};
}}
QPushButton#poll_toggle[active="true"] {{
    color: {RED};
    border-color: {RED};
}}
QPushButton#poll_toggle[active="true"]:hover {{
    background-color: {RED};
    color: {BG};
}}
"""


# ── Reusable widgets ──────────────────────────────────────────

class ContextCard(QFrame):
    def __init__(self, title="—", subtitle="", active=False, parent=None):
        super().__init__(parent)
        self.setObjectName("context_card")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        col = QVBoxLayout()
        col.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("card_title_active" if active else "card_title")
        row.addWidget(self.title_lbl)

        self.badge = QLabel("Active")
        self.badge.setObjectName("active_badge")
        self.badge.setVisible(active)
        row.addWidget(self.badge)
        row.addStretch()
        col.addLayout(row)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setObjectName("card_subtitle")
        col.addWidget(self.sub_lbl)
        lay.addLayout(col)

    def update_data(self, title: str, subtitle: str, active: bool = False):
        self.title_lbl.setText(title)
        self.title_lbl.setObjectName("card_title_active" if active else "card_title")
        self.title_lbl.setStyle(self.title_lbl.style())  # force QSS refresh
        self.sub_lbl.setText(subtitle)
        self.badge.setVisible(active)


class ActionButton(QPushButton):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("action_btn")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(68)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("btn_title")
        self._title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(subtitle)
        self._sub_lbl.setObjectName("btn_subtitle")
        self._sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._sub_lbl)

    def set_subtitle(self, text: str):
        self._sub_lbl.setText(text)

class HIDSignals(QObject):
    """Qt signal bridge for HID thread → main thread."""
    device_connected = pyqtSignal(bool)  # True=connected, False=disconnected
    release_succeeded = pyqtSignal(str)
    release_failed = pyqtSignal(str)
    release_finished = pyqtSignal()


# --Sensitive content guard  ─────────────────────────
class PrivacyGuard:
    def __init__(self):
        # 1. Block by Bundle ID (App-level)
        self.blocked_bundles = {
            "com.apple.KeychainAccess",  # Passwords
            "com.agilebits.onepassword", # 1Password
            "com.apple.systempreferences", # System Settings
            "com.microsoft.authenticator", # 2FA
            "com.apple.AddressBook"        # Contacts
        }

        # 2. Block by Window Title Keywords (Content-level)
        self.sensitive_keywords = [
            "bank", "incognito", "private", "checkout", 
            "payment", "credit card", "password", "vault"
        ]

    def is_safe(self, app_bundle, window_title):
        # Check if the app itself is forbidden
        if app_bundle in self.blocked_bundles:
            return False
            
        # Check if the window title suggests sensitive activity
        title_lower = window_title.lower()
        if any(key in title_lower for key in self.sensitive_keywords):
            return False
            
        return True


class DatabaseViewerWindow(QWidget):
    """Read-only live view of the local SQLite snapshot table."""

    REFRESH_INTERVAL_MS = 250
    COLUMN_HEADERS = [
        "ID",
        "App",
        "Window",
        "Last Seen",
        "Preview",
        "Fingerprint",
    ]

    def __init__(self, db: SparkDB, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("SPARK Database Viewer")
        self.resize(1480, 760)
        self.setStyleSheet(
            f"""
            QWidget {{
                background-color: {BG};
                color: {TEXT};
                font-family: 'SF Pro Text', -apple-system, 'Helvetica Neue', sans-serif;
            }}
            QLabel#db_title {{
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel#db_subtitle {{
                color: {TEXT_DIM};
                font-size: 11px;
            }}
            QTableWidget {{
                background-color: {SURFACE};
                alternate-background-color: {SURFACE_ALT};
                border: 1px solid {BORDER};
                border-radius: 10px;
                gridline-color: {BORDER};
            }}
            QHeaderView::section {{
                background-color: {SURFACE_ALT};
                color: {TEXT_MID};
                border: none;
                border-bottom: 1px solid {BORDER};
                padding: 6px;
                font-size: 11px;
                font-weight: 700;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Database Viewer")
        title.setObjectName("db_title")
        layout.addWidget(title)

        self.subtitle_lbl = QLabel("Live snapshot rows from spark.db • newest last_seen first")
        self.subtitle_lbl.setObjectName("db_subtitle")
        layout.addWidget(self.subtitle_lbl)

        self.table = QTableWidget(0, len(self.COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(self.COLUMN_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(2, 420)
        self.table.setColumnWidth(5, 150)
        layout.addWidget(self.table)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        self.refresh()
        self.refresh_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.refresh_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.refresh_timer.stop()
        super().closeEvent(event)

    def refresh(self):
        rows = self.db.get_debug_rows()
        self.table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            values = [
                str(row["id"]),
                row["app_name"] or "",
                row["window_title"] or "",
                self._format_ts(row["last_seen"]),
                row["text_preview"] or "",
                (row["content_fingerprint"] or "")[:16],
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col_idx in (0, 3, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeRowsToContents()
        self.subtitle_lbl.setText(
            f"Live snapshot rows from spark.db • newest last_seen first • {len(rows)} visible"
        )

    @staticmethod
    def _format_ts(value) -> str:
        if not value:
            return ""
        return datetime.fromtimestamp(float(value)).strftime("%H:%M:%S")

# ── Main panel ────────────────────────────────────────────────

class SparkPanel(QWidget):
    """
    Frameless floating SPARK panel — replaces SparkPipeline window.
    Wires directly into AccessibilityManager, WindowContextTracker,
    GlobalHotkeyManager, and SparkDB from your existing architecture.
    """

    POLL_INTERVAL = 125   # ms
    MAX_CAPTURE_LINES = 6

    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        
        self.privacy_guard = PrivacyGuard()

        # ── Window flags: frameless, always-on-top ──
        # NOTE: Do NOT use Qt.WindowType.Tool — on macOS it hides the
        # window whenever another application receives focus.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(440)
        self.setStyleSheet(QSS)

        # ── Backend (same objects as SparkPipeline) ──────────────
        self.manager = AccessibilityManager()
        self.hotkeys = GlobalHotkeyManager()

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spark.db")
        self.db = SparkDB(db_path)
        self.tracker = WindowContextTracker(db=self.db)
        self.db_viewer = DatabaseViewerWindow(self.db)

        # ── HID device ───────────────────────────────────────────
        self.hid_signals = HIDSignals()
        self.hid_client  = SparkHIDClient()

        # ── Serial sender (Host → Pico Hub) ──────────────────────
        self.serial_sender = SerialSender()
        self.serial_sender.connect()   # best-effort; silently skipped if no Pico
        self._last_serial_key: str | None = None

        self.captured_text: str = ""
        self.processed_text: str = ""
        self.is_polling = False
        self._capture_feed = LiveCaptureFeed(max_lines=self.MAX_CAPTURE_LINES)
        self._drag_pos: QPoint | None = None

        self._build_ui()
        self._connect_hotkeys()
        self.hotkeys.start()
        self._connect_hid()

        self.poll_timer = QTimer()
        self.poll_timer.setInterval(self.POLL_INTERVAL)
        self.poll_timer.timeout.connect(self._on_poll_tick)

        self._blink_timer = QTimer()
        self._blink_timer.timeout.connect(self._blink_live)
        self._blink_state = True

        # Restore saved position (or default to bottom-right)
        self._restore_position()

    # ─────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        inner.setObjectName("root")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(22, 20, 22, 22)
        lay.setSpacing(0)

        # ── Header ───────────────────────────────────────────
        hdr = QHBoxLayout()

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("SPARK")
        t.setObjectName("app_title")
        s = QLabel("AI Desktop Assistant")
        s.setObjectName("app_subtitle")
        title_col.addWidget(t)
        title_col.addWidget(s)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.device_dot = QLabel("● DEVICE DISCONNECTED")
        self.device_dot.setObjectName("device_dot")
        self.device_dot.setStyleSheet(f"color: #374151;")  # grey = disconnected
        hdr.addWidget(self.device_dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        close = QLabel("✕")
        close.setObjectName("close_btn")
        close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close.mousePressEvent = lambda _: self.hide()
        hdr.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)

        lay.addLayout(hdr)
        lay.addSpacing(14)
        lay.addWidget(self._divider())
        lay.addSpacing(14)

        # ── Live Context ──────────────────────────────────────
        ctx_hdr = QHBoxLayout()
        ctx_lbl = QLabel("LIVE CONTEXT")
        ctx_lbl.setObjectName("section_label")
        ctx_hdr.addWidget(ctx_lbl)
        ctx_hdr.addStretch()

        self.poll_btn = QPushButton("Start Polling")
        self.poll_btn.setObjectName("poll_toggle")
        self.poll_btn.setProperty("active", "false")
        self.poll_btn.setFixedHeight(24)
        self.poll_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.poll_btn.clicked.connect(self._on_toggle_polling)
        ctx_hdr.addWidget(self.poll_btn)
        lay.addLayout(ctx_hdr)
        lay.addSpacing(10)

        # 3 context cards (active + 2 history)
        self.ctx_card_active = ContextCard("—", "No window detected", active=True)
        self.ctx_card_prev1  = ContextCard("—", "")
        self.ctx_card_prev2  = ContextCard("—", "")
        for card in (self.ctx_card_active, self.ctx_card_prev1, self.ctx_card_prev2):
            lay.addWidget(card)
            lay.addSpacing(6)

        lay.addSpacing(10)
        lay.addWidget(self._divider())
        lay.addSpacing(14)

        # ── Live Capture ──────────────────────────────────────
        cap_hdr = QHBoxLayout()
        cap_sec = QLabel("LIVE CAPTURE")
        cap_sec.setObjectName("section_label")
        cap_hdr.addWidget(cap_sec)
        cap_hdr.addStretch()

        self.live_dot = QLabel("● Live")
        self.live_dot.setObjectName("live_dot")
        cap_hdr.addWidget(self.live_dot)
        lay.addLayout(cap_hdr)
        lay.addSpacing(10)

        cap_frame = QFrame()
        cap_frame.setObjectName("capture_frame")
        cap_inner = QVBoxLayout(cap_frame)
        cap_inner.setContentsMargins(14, 12, 14, 12)

        self.capture_lbl = QLabel("Polling not started…")
        self.capture_lbl.setObjectName("capture_text")
        self.capture_lbl.setWordWrap(True)
        self.capture_lbl.setMinimumHeight(60)
        cap_inner.addWidget(self.capture_lbl)
        lay.addWidget(cap_frame)
        lay.addSpacing(10)

        out_hdr = QHBoxLayout()
        out_sec = QLabel("RELEASE OUTPUT")
        out_sec.setObjectName("section_label")
        out_hdr.addWidget(out_sec)
        out_hdr.addStretch()
        lay.addLayout(out_hdr)
        lay.addSpacing(10)

        out_frame = QFrame()
        out_frame.setObjectName("capture_frame")
        out_inner = QVBoxLayout(out_frame)
        out_inner.setContentsMargins(14, 12, 14, 12)

        self.release_output_lbl = QLabel("No released text yet…")
        self.release_output_lbl.setObjectName("capture_text")
        self.release_output_lbl.setWordWrap(True)
        self.release_output_lbl.setMinimumHeight(60)
        out_inner.addWidget(self.release_output_lbl)
        lay.addWidget(out_frame)
        lay.addSpacing(10)

        # Status line
        self.status_lbl = QLabel(f"Ready - select text in any app, then {CAPTURE_HOTKEY_LABEL}")
        self.status_lbl.setObjectName("status_label")
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)
        lay.addSpacing(14)

        lay.addWidget(self._divider())
        lay.addSpacing(14)

        # ── Suggested Actions ─────────────────────────────────
        act_lbl = QLabel("SUGGESTED ACTIONS")
        act_lbl.setObjectName("section_label")
        lay.addWidget(act_lbl)
        lay.addSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(8)

        self.btn_capture  = ActionButton("Capture Text", f"{CAPTURE_HOTKEY_LABEL} - grab selection")
        self.btn_release  = ActionButton("Release Text", f"{RELEASE_HOTKEY_LABEL} - send to SPARK")
        self.btn_summarize = ActionButton("Summarize Window", "Quick overview of visible text")
        self.btn_history  = ActionButton("Show History", "View previous window contexts")
        self.btn_database = ActionButton("Show Database", "Debug live snapshot rows")

        self.btn_release.setEnabled(False)

        self.btn_capture.clicked.connect(self._on_capture)
        self.btn_release.clicked.connect(self._on_release)
        self.btn_summarize.clicked.connect(self._on_summarize)
        self.btn_history.clicked.connect(self._on_show_history)
        self.btn_database.clicked.connect(self._on_show_database)

        grid.addWidget(self.btn_capture,  0, 0)
        grid.addWidget(self.btn_release,  0, 1)
        grid.addWidget(self.btn_summarize, 1, 0)
        grid.addWidget(self.btn_history,  1, 1)
        grid.addWidget(self.btn_database, 2, 0, 1, 2)
        lay.addLayout(grid)

        outer.addWidget(inner)

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("divider")
        return d

    # ─────────────────────────────────────────────────────────────
    # Hotkeys — same signals as SparkPipeline
    # ─────────────────────────────────────────────────────────────

    def _connect_hotkeys(self):
        self.hotkeys.signals.capture_triggered.connect(self._on_capture)
        self.hotkeys.signals.release_triggered.connect(self._on_release)
        self.hotkeys.signals.toggle_triggered.connect(self.toggle)

    # ─────────────────────────────────────────────────────────────
    # HID device
    # ─────────────────────────────────────────────────────────────

    def _connect_hid(self):
        """Start a 2-second connection poll and wire the device_connected signal."""
        self.hid_signals.device_connected.connect(self._on_hid_connected)
        self.hid_signals.release_succeeded.connect(self._on_release_succeeded)
        self.hid_signals.release_failed.connect(self._on_release_failed)
        self.hid_signals.release_finished.connect(self._on_release_finished)
        self._hid_poll_timer = QTimer()
        self._hid_poll_timer.setInterval(2000)
        self._hid_poll_timer.timeout.connect(self._poll_hid_connection)
        self._hid_poll_timer.start()

    def _poll_hid_connection(self):
        """Check USB connection and emit signal if state changed."""
        connected = self.hid_client.is_connected()
        if connected != getattr(self, "_hid_connected", None):
            self._hid_connected = connected
            self.hid_signals.device_connected.emit(connected)

    def _on_hid_connected(self, connected: bool):
        """Update the device status dot in the header."""
        if connected:
            self.device_dot.setText("● DEVICE CONNECTED")
            self.device_dot.setStyleSheet(f"color: {GREEN};")
            self.device_dot.setToolTip("SPARK device connected")
        else:
            self.device_dot.setText("● DEVICE DISCONNECTED")
            self.device_dot.setStyleSheet("color: #374151;")
            self.device_dot.setToolTip("SPARK device disconnected")

    def _on_release_succeeded(self, text: str):
        self.release_output_lbl.setText(format_release_output(text) if text else "No released text yet…")
        self._set_status("Sent to SPARK — output updated ✓", GREEN)

    def _on_release_failed(self, message: str):
        self._set_status(message, RED)

    def _on_release_finished(self):
        self.btn_release.setEnabled(True)

    # ─────────────────────────────────────────────────────────────
    # Polling — identical logic to SparkPipeline._on_poll_tick
    # ─────────────────────────────────────────────────────────────

    def _on_toggle_polling(self):
        if self.is_polling:
            self.poll_timer.stop()
            self._blink_timer.stop()
            self.is_polling = False
            self.poll_btn.setText("Start Polling")
            self.poll_btn.setProperty("active", "false")
            self.poll_btn.setStyle(self.poll_btn.style())
            self.live_dot.setText("● Live")
        else:
            self.is_polling = True
            self.poll_btn.setText("Stop Polling")
            self.poll_btn.setProperty("active", "true")
            self.poll_btn.setStyle(self.poll_btn.style())
            self.poll_timer.start()
            self._blink_timer.start(800)
            self._on_poll_tick()

    def _on_poll_tick(self):
        info = self.manager.get_active_window_info()
        if not info:
            self.ctx_card_active.update_data("—", "No window detected", active=True)
            self._push_poll_capture_line("No active window detected")
            if self.db_viewer.isVisible():
                self.db_viewer.refresh()
            return
        # Ignore the SPARK panel itself
        if info.pid == os.getpid():
            return
        # --- PRIVACY CHECK ---
        if not self.privacy_guard.is_safe(info.bundle_id, info.title):
            self.ctx_card_active.update_data("PROTECTED", "Privacy Filter Active", active=True)
            self._set_status("🛡️ Privacy Guard: Content Hidden", RED)
            # We stop here so no text is extracted or saved to DB
            if self.db_viewer.isVisible():
                self.db_viewer.refresh()
            return
        # ---------------------

        tab = get_browser_tab(info.app_name)
        detail = f"{tab.tab_title}" if (tab and tab.tab_title) else info.title
        if tab and not self.privacy_guard.is_safe(info.bundle_id, tab.tab_title):
            self.ctx_card_active.update_data(info.app_name, "Protected URL", active=True)
            if self.db_viewer.isVisible():
                self.db_viewer.refresh()
            return
        self.ctx_card_active.update_data(info.app_name, detail, active=True)

        # Try to get text
        text, source = None, None
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

        #Edit 

        if text and text.strip() and source:
            preview = text[:120].replace("\n", " ")
            self._push_poll_capture_line(f"[{info.app_name}] {preview}")
            self.tracker.update(info, text, source, tab=tab)

            # ── Serial → Pico Hub ────────────────────────────────
            current = self.tracker.get_current()
            if current:
                key = current.context_key
                if key != self._last_serial_key:
                    self._last_serial_key = key
                    self.serial_sender.send_window_new(
                        info.app_name, info.title or "", text
                    )
                else:
                    self.serial_sender.send_window_update(text)
        else:
            self._push_poll_capture_line(f"[{info.app_name}] (no text extracted)")

        self._refresh_history_cards()
        if self.db_viewer.isVisible():
            self.db_viewer.refresh()

    def _refresh_history_cards(self):
        previous = self.tracker.get_all_previous()
        cards = [self.ctx_card_prev1, self.ctx_card_prev2]
        for i, card in enumerate(cards):
            if i < len(previous):
                snap = previous[i]
                subtitle = snap.url or snap.window_info.title
                card.update_data(snap.window_info.app_name, subtitle or "", active=False)
            else:
                card.update_data("—", "", active=False)

    def _push_poll_capture_line(self, line: str):
        self._capture_feed.push_poll_line(line)
        self._refresh_capture_label()

    def _push_capture_line(self, line: str):
        self._capture_feed.push_event_line(line)
        self._refresh_capture_label()

    def _refresh_capture_label(self):
        self.capture_lbl.setText("\n".join(self._capture_feed.lines))

    def _blink_live(self):
        self._blink_state = not self._blink_state
        self.live_dot.setText("● Live" if self._blink_state else "  Live")

    # ─────────────────────────────────────────────────────────────
    # Actions — same logic as SparkPipeline
    # ─────────────────────────────────────────────────────────────

    def _on_capture(self):
        self._set_status("Capturing selection…", ORANGE)
        QTimer.singleShot(200, self._do_capture)

    def _do_capture(self):
        info = self.manager.get_active_window_info()
        if info and not self.privacy_guard.is_safe(info.bundle_id, info.title):
            self._set_status("Cannot capture: Sensitive window detected", RED)
            return
        text = self.manager.get_selected_text()
        if text and text.strip():
            self.captured_text = text
            # TODO: Replace with your AI/LLM call. Example:
            #   self._set_status("Processing with AI…", ORANGE)
            #   QTimer.singleShot(0, lambda: self._run_ai(text))
            # where _run_ai runs the model in a thread and sets self.processed_text.
            self.processed_text = text
            self.btn_release.setEnabled(True)
            self.btn_release.set_subtitle(f"{len(self.processed_text)} chars ready")
            self._set_status(
                f"Captured {len(text)} chars - {RELEASE_HOTKEY_LABEL} to send to SPARK", GREEN
            )
            self._push_capture_line(f"[CAPTURED] {text[:80].replace(chr(10),' ')}…")
        else:
            self._set_status("No text selected — highlight text first, then capture", RED)

    def _on_release(self):
        if not self.processed_text:
            self._set_status("Nothing to release — capture text first", RED)
            return
        if not self.hid_client.is_connected():
            self._set_status("SPARK device not connected", RED)
            return
        self._set_status("Sending to device…", ORANGE)
        self.btn_release.setEnabled(False)
        text = self.processed_text
        threading.Thread(target=self._do_release, args=(text,), daemon=True).start()

    def _do_release(self, text: str):
        """Upload text to the device (runs in background thread)."""
        try:
            status = self.hid_client.upload(AppCommand.SUBMIT_TEXT, text)
            if status.ok:
                self.hid_signals.device_connected.emit(True)  # reuse signal to confirm alive
                self.hid_signals.release_succeeded.emit(text)
            else:
                self.hid_signals.release_failed.emit(f"Device error: {status.code.name}")
        except SparkProtocolError as exc:
            self.hid_signals.release_failed.emit(f"HID error: {exc}")
        finally:
            self.hid_signals.release_finished.emit()

    def _on_summarize(self):
        """Summarize whatever is currently visible in the active window."""
        info = self.manager.get_active_window_info()
        if not info:
            self._set_status("No active window to summarize", RED)
            return
        try:
            text = self.manager.get_window_text() or ""
            if not text.strip():
                self._set_status("No text found in active window", RED)
                return
            # TODO: Replace preview with an actual LLM summarization call.
            # Run it in a thread to avoid blocking the Qt event loop, e.g.:
            #   threading.Thread(target=self._summarize_async, args=(text,)).start()
            preview = text[:200].replace("\n", " ")
            self._push_capture_line(f"[SUMMARY] {preview}…")
            self._set_status("Summary captured to Live Capture", GREEN)
        except Exception as e:
            self._set_status(f"Summarize failed: {e}", RED)

    def _on_show_history(self):
        """Flash history into the capture box."""
        previous = self.tracker.get_all_previous()
        if not previous:
            self._set_status("No history yet — start polling first", ORANGE)
            return
        for snap in previous:
            line = f"[HIST] {snap.window_info.app_name} — {(snap.url or snap.window_info.title or '')[:60]}"
            self._push_capture_line(line)
        self._set_status(f"Showing {len(previous)} history entries", GREEN)

    def _on_show_database(self):
        """Open the live database viewer window."""
        self.db_viewer.show()
        self.db_viewer.raise_()
        self.db_viewer.activateWindow()
        self.db_viewer.refresh()
        self._set_status("Database viewer opened", GREEN)

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = TEXT_DIM):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")

    # ─────────────────────────────────────────────────────────────
    # Frameless window painting + drag
    # ─────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            float(self.rect().x()), float(self.rect().y()),
            float(self.rect().width()), float(self.rect().height()),
            18.0, 18.0
        )
        p.fillPath(path, QColor(BG))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self.db.set_pref("panel_x", str(self.pos().x()))
            self.db.set_pref("panel_y", str(self.pos().y()))
        self._drag_pos = None

    # ─────────────────────────────────────────────────────────────
    # Toggle show/hide (call from hotkey or tray icon)
    # ─────────────────────────────────────────────────────────────

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def _restore_position(self):
        """Move to saved position, or default to bottom-right."""
        saved_x = self.db.get_pref("panel_x")
        saved_y = self.db.get_pref("panel_y")
        if saved_x is not None and saved_y is not None:
            self.move(int(saved_x), int(saved_y))
        else:
            self._position_bottom_right()

    def _position_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = screen.right() - self.width() - 20
        y = screen.bottom() - self.height() - 20
        self.move(x, y)

    # ─────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self.poll_timer.stop()
        self._blink_timer.stop()
        self._hid_poll_timer.stop()
        self.db_viewer.close()
        self.hotkeys.stop()
        self.hid_client.close()
        self.serial_sender.close()
        self.db.close()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────

def _make_tray_icon() -> QIcon:
    """Create a simple 32x32 tray icon (blue spark dot)."""
    px = QPixmap(32, 32)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(px)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    panel = SparkPanel()

    # ── System tray ──────────────────────────────────────────
    tray = QSystemTrayIcon(_make_tray_icon(), app)
    tray_menu = QMenu()
    show_action = tray_menu.addAction("Show / Hide")
    show_action.triggered.connect(panel.toggle)
    tray_menu.addSeparator()
    quit_action = tray_menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: panel.toggle()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    panel.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

