"""
SPARK — Full Pipeline Application (v2: SPARK Panel UI)

Capture text from any application, process it, and paste it back.

Hotkeys (global, work from any app):
    macOS: Cmd+Ctrl+C / Cmd+Ctrl+R
    Windows: Win+Alt+C / Win+Alt+V
"""

import os
import sys
import signal
import datetime as dt
import logging
import logging.handlers
import threading
import time
from pathlib import Path

from app_log_contract import APP_LOG_FILE_FORMAT

from PyQt6.QtWidgets import (
     QApplication, QWidget, QFrame,
     QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
     QGridLayout, QSizePolicy,
     QSystemTrayIcon, QMenu,
     QDialog, QDialogButtonBox, QLineEdit, QTextEdit, QComboBox,
     QTableWidget, QTableWidgetItem, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QColor, QPainter, QPainterPath, QCursor, QIcon, QPixmap

sys.path.insert(0, '/Users/tatyanacruz/Documents/Spring 26/SPARK')

from host_pc.accessibility import AccessibilityManager
from host_pc.accessibility.base import TextSource
from host_pc.accessibility.tracker import WindowContextTracker
from host_pc.browser import get_browser_tab
from host_pc.hotkeys import GlobalHotkeyManager, get_hotkey_config
from host_pc.raw_hid import SparkHIDClient, AppCommand, SparkProtocolError
from host_pc.release_output import format_release_output
from host_pc.serial_sender import SerialSender
from host_pc.live_capture import LiveCaptureFeed
from host_pc.snapshot_policy import is_relevant_snapshot, snapshot_fingerprint
from host_pc.summarize_stream import (
     build_respond_request,
     build_reformat_request,
     build_summary_request,
     build_summarize_command,
     build_test_summary_request,
)
from host_pc.single_instance import SingleInstanceGuard
from host_pc.web_content import WebContentExtractor
from host_pc.web_content import _is_supported_macos_browser, _is_supported_windows_browser
from host_pc.jetson_db_snapshot import (
    SnapshotHandle,
    TablePage,
    create_snapshot_with_retry,
    list_user_tables,
    load_table_rows,
    delete_snapshot,
)

APP_LOG_FORMAT = APP_LOG_FILE_FORMAT
DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "spark_app_v2.log"
APP_LOG_MAX_BYTES = 512_000
APP_LOG_BACKUP_COUNT = 3


def configure_app_logging(log_path=DEFAULT_LOG_PATH):
    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_log_path = log_path.resolve()
        root = logging.getLogger()
        matching_handlers = []

        for handler in root.handlers:
            if not isinstance(handler, logging.FileHandler):
                continue
            if Path(handler.baseFilename).resolve() != resolved_log_path:
                continue
            matching_handlers.append(handler)

        if len(matching_handlers) == 1:
            handler = matching_handlers[0]
            if (
                isinstance(handler, logging.handlers.RotatingFileHandler)
                and handler.maxBytes == APP_LOG_MAX_BYTES
                and handler.backupCount == APP_LOG_BACKUP_COUNT
            ):
                handler.setFormatter(logging.Formatter(APP_LOG_FORMAT))
                return handler

        for handler in matching_handlers:
            root.removeHandler(handler)
            handler.close()

        file_handler = logging.handlers.RotatingFileHandler(
            resolved_log_path,
            maxBytes=APP_LOG_MAX_BYTES,
            backupCount=APP_LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(logging.Formatter(APP_LOG_FORMAT))
        root.addHandler(file_handler)
        return file_handler
    except OSError as exc:
        logging.warning("[LOGGING] File logging could not be configured for %s: %s", log_path, exc)
        return None


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s")
configure_app_logging()
logger = logging.getLogger(__name__)

_IGNORED_POLL_WINDOW_TITLES = {
    "spark app",
    "spark full debug watcher",
    "jetson db viewer",
}


def _same_poll_target(first, second) -> bool:
    if first is None or second is None:
        return False
    return (
        getattr(first, "pid", None) == getattr(second, "pid", None)
        and getattr(first, "app_name", None) == getattr(second, "app_name", None)
        and getattr(first, "title", None) == getattr(second, "title", None)
    )


def _is_ignored_poll_window(info) -> bool:
    title = (getattr(info, "title", "") or "").strip().lower()
    return title in _IGNORED_POLL_WINDOW_TITLES

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
    font-size: 18px;
    background: transparent;
    padding: 4px;
}}
QTextEdit#release_output_text {{
    color: #22C55E;
    font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
    font-size: 18px;
    background: transparent;
    border: none;
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
        self.sub_lbl.setWordWrap(True)
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
    summarize_progress = pyqtSignal(str)
    summarize_succeeded = pyqtSignal(str)
    summarize_failed = pyqtSignal(str)
    summarize_finished = pyqtSignal()
    pico_debug = pyqtSignal(str)


class JetsonDbRefreshSignals(QObject):
    refresh_succeeded = pyqtSignal(int, object, list, object)
    refresh_failed = pyqtSignal(int, str)


class CustomContextDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Context")
        self.setModal(True)
        self.resize(520, 420)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {BG};
                color: {TEXT};
            }}
            QLabel {{
                color: {TEXT_MID};
                font-size: 12px;
                font-weight: 600;
            }}
            QLineEdit, QTextEdit {{
                background-color: {SURFACE};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px;
            }}
            QPushButton {{
                background-color: {SURFACE};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px 14px;
            }}
            QPushButton:hover {{
                background-color: #1E293B;
                border: 1px solid {BORDER_LIT};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        app_label = QLabel("App Name")
        layout.addWidget(app_label)
        self.app_name_edit = QLineEdit("Cursor")
        layout.addWidget(self.app_name_edit)

        title_label = QLabel("Window Title")
        layout.addWidget(title_label)
        self.window_title_edit = QLineEdit("Transport debug session")
        layout.addWidget(self.window_title_edit)

        text_label = QLabel("Visible Text")
        layout.addWidget(text_label)
        self.window_text_edit = QTextEdit()
        self.window_text_edit.setPlainText(
            "The user is testing a custom SPARK context payload from the visible app. "
            "The goal is to stream the Jetson-generated result into RELEASE OUTPUT."
        )
        layout.addWidget(self.window_text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return (
            self.app_name_edit.text(),
            self.window_title_edit.text(),
            self.window_text_edit.toPlainText(),
        )


class JetsonDbViewerDialog(QDialog):
    _HIDDEN_SESSION_COLUMNS = {
        "id",
        "context_key",
        "content_fingerprint",
        "process_name",
        "pid",
        "source",
        "tab_title",
        "started_at",
        "updated_at",
    }
    _TIMESTAMP_COLUMNS = {"host_observed_at", "started_at", "updated_at"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jetson DB Viewer")
        self.setModal(True)
        self.resize(1400, 920)

        self.current_snapshot = None
        self.current_table = ""
        self.row_offset = 0
        self.current_table_has_more = False
        self.refresh_in_flight = False
        self._refresh_request_token = 0
        self._table_load_token = 0
        self._is_closed = False
        self._auto_refresh_pending = True
        self._page_size = 100
        self._current_table_columns: list[str] = []
        self._refresh_signals = JetsonDbRefreshSignals()
        self._refresh_signals.refresh_succeeded.connect(self._on_refresh_succeeded)
        self._refresh_signals.refresh_failed.connect(self._on_refresh_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        self.table_selector = QComboBox(self)
        self.table_selector.currentTextChanged.connect(self._on_table_selected)
        top_row.addWidget(self.table_selector, stretch=1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        top_row.addWidget(self.refresh_btn)

        self.load_more_btn = QPushButton("Load More")
        self.load_more_btn.setEnabled(False)
        self.load_more_btn.clicked.connect(self._on_load_more)
        top_row.addWidget(self.load_more_btn)
        layout.addLayout(top_row)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("status_label")
        self.status_label.setProperty("read_only", True)
        layout.addWidget(self.status_label)

        self.rows_table = QTableWidget(0, 0, self)
        self.rows_table.setWordWrap(True)
        self.rows_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rows_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.rows_table)

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_refresh_pending:
            self._auto_refresh_pending = False
            QTimer.singleShot(0, self._on_refresh_clicked)

    def _on_refresh(self):
        self._on_refresh_clicked()

    def _on_refresh_clicked(self):
        if self._is_closed:
            return
        if self.refresh_in_flight:
            return
        self._start_refresh()

    def _start_refresh(self):
        self._refresh_request_token += 1
        self._table_load_token += 1
        request_token = self._refresh_request_token
        self.refresh_in_flight = True
        self.refresh_btn.setEnabled(False)
        self.load_more_btn.setEnabled(False)
        self.status_label.setText("Refreshing Jetson DB snapshot…")
        threading.Thread(
            target=self._fetch_snapshot_and_table_data,
            args=(request_token,),
            daemon=True,
        ).start()

    def _fetch_snapshot_and_table_data(self, request_token: int):
        snapshot = None
        try:
            snapshot = create_snapshot_with_retry()
            tables = list_user_tables(snapshot.path)
            page = None
            if tables:
                page = load_table_rows(
                    snapshot.path,
                    tables[0],
                    limit=self._page_size,
                    offset=0,
                )
            self._refresh_signals.refresh_succeeded.emit(request_token, snapshot, tables, page)
        except Exception as exc:
            if snapshot is not None:
                delete_snapshot(snapshot)
            self._refresh_signals.refresh_failed.emit(request_token, f"{exc}")

    def _on_refresh_succeeded(
        self,
        request_token: int,
        snapshot: SnapshotHandle,
        table_names: list[str],
        table_page: TablePage | None,
    ):
        if self._is_closed or request_token != self._refresh_request_token:
            if snapshot is not None:
                delete_snapshot(snapshot)
            return

        prior_snapshot = self.current_snapshot
        selected_table = self.current_table if self.current_table in table_names else (table_names[0] if table_names else "")
        self.current_snapshot = snapshot
        self.current_table = selected_table
        self.current_table_has_more = False
        self._current_table_columns = []
        self.row_offset = 0

        self._populate_table_selector(table_names, selected_table)
        display_page = table_page
        if selected_table and table_page is not None and table_page.table_name != selected_table:
            display_page = load_table_rows(
                snapshot.path,
                selected_table,
                limit=self._page_size,
                offset=0,
            )

        if display_page is not None:
            self._render_table_page(display_page)
            self.current_table_has_more = bool(display_page.has_more)
            self.row_offset = len(display_page.rows)
            self.status_label.setText(
                f"Loaded {len(display_page.rows)} rows from {display_page.table_name}"
            )
        else:
            self.rows_table.clearContents()
            self.rows_table.setRowCount(0)
            self.rows_table.setColumnCount(0)
            self.rows_table.setHorizontalHeaderLabels([])
            if self.current_table:
                self.status_label.setText(f"No rows in table '{self.current_table}'")
            else:
                self.status_label.setText("No user tables in snapshot")
            self.current_table_has_more = False
            self._current_table_columns = []

        self.load_more_btn.setEnabled(bool(self.current_table and self.current_table_has_more))

        if prior_snapshot is not None:
            delete_snapshot(prior_snapshot)
        self.refresh_in_flight = False
        self.refresh_btn.setEnabled(True)

    def _on_refresh_failed(self, request_token: int, error_text: str):
        if self._is_closed or request_token != self._refresh_request_token:
            return

        self.status_label.setText(f"Refresh failed: {error_text}")
        self.refresh_in_flight = False
        self.refresh_btn.setEnabled(True)
        self.load_more_btn.setEnabled(bool(self.current_table and self.current_table_has_more))

    def _populate_table_selector(self, table_names: list[str], selected_table: str | None = None):
        self.table_selector.blockSignals(True)
        self.table_selector.clear()
        if table_names:
            self.table_selector.addItems(table_names)
            self.table_selector.setCurrentText(selected_table or table_names[0])
        self.table_selector.blockSignals(False)
        if not table_names:
            self.load_more_btn.setEnabled(False)

    def _on_table_selected(self, table_name: str):
        if self._is_closed:
            return
        if not table_name or not self.current_snapshot:
            return

        self._table_load_token += 1
        load_token = self._table_load_token
        prior_table = self.current_table
        prior_row_offset = self.row_offset

        try:
            table_page = load_table_rows(
                self.current_snapshot.path,
                table_name,
                limit=self._page_size,
                offset=0,
            )
        except Exception as exc:
            if load_token != self._table_load_token:
                return
            self.status_label.setText(f"Failed to load table '{table_name}': {exc}")
            if prior_table:
                self.table_selector.blockSignals(True)
                self.table_selector.setCurrentText(prior_table)
                self.table_selector.blockSignals(False)
            self.row_offset = prior_row_offset
            return

        if load_token != self._table_load_token:
            return

        try:
            self.current_table = table_name
            self.row_offset = 0
            self._render_table_page(table_page)
            self.current_table_has_more = bool(table_page.has_more)
            self.row_offset = len(table_page.rows)
            self.status_label.setText(
                f"Loaded {len(table_page.rows)} rows from {table_page.table_name}"
            )
            self._current_table_columns = list(table_page.rows[0].keys()) if table_page.rows else []
            self.load_more_btn.setEnabled(bool(self.current_table_has_more))
            return
        except Exception as exc:
            if load_token != self._table_load_token:
                return
            self.status_label.setText(f"Failed to render table '{table_name}': {exc}")
            self.current_table = prior_table
            self.row_offset = prior_row_offset
            self.current_table_has_more = False
            if prior_table:
                self.table_selector.blockSignals(True)
                self.table_selector.setCurrentText(prior_table)
                self.table_selector.blockSignals(False)
                self.load_more_btn.setEnabled(bool(prior_table) and self.current_table_has_more)
            else:
                self.load_more_btn.setEnabled(False)

    def _on_load_more(self):
        if self._is_closed or self.refresh_in_flight:
            return
        if not self.current_snapshot or not self.current_table:
            return
        if not self.current_table_has_more:
            return

        try:
            table_page = load_table_rows(
                self.current_snapshot.path,
                self.current_table,
                limit=self._page_size,
                offset=self.row_offset,
            )
        except Exception as exc:
            self.status_label.setText(f"Failed to load more rows from '{self.current_table}': {exc}")
            return

        if table_page.rows:
            self._append_table_page(table_page)
            self.status_label.setText(
                f"Loaded {len(table_page.rows)} more rows from {table_page.table_name}"
            )
        else:
            self.status_label.setText(f"No more rows from {table_page.table_name}")

        self.current_table_has_more = bool(table_page.has_more)
        self.row_offset += len(table_page.rows)
        self.load_more_btn.setEnabled(self.current_table_has_more)

    def _render_table_page(self, table_page: TablePage):
        rows = self._display_rows_for_table(table_page.table_name, table_page.rows)
        if not rows:
            self.rows_table.clearContents()
            self.rows_table.setRowCount(0)
            self.rows_table.setColumnCount(0)
            self.rows_table.setHorizontalHeaderLabels([])
            self._current_table_columns = []
            return

        columns = list(rows[0].keys())
        self._current_table_columns = columns
        self.rows_table.setColumnCount(len(columns))
        self.rows_table.setRowCount(len(rows))
        self.rows_table.setHorizontalHeaderLabels(columns)

        for row_i, row in enumerate(rows):
            for col_i, key in enumerate(columns):
                item = QTableWidgetItem(str(row.get(key, "")))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.rows_table.setItem(row_i, col_i, item)

        self.rows_table.clearSelection()
        self.rows_table.setCurrentCell(-1, -1)
        self._resize_rows_for_content(columns)

    def _append_table_page(self, table_page: TablePage):
        rows = self._display_rows_for_table(table_page.table_name, table_page.rows)
        if not rows:
            return

        columns = list(rows[0].keys())
        if self._current_table_columns != columns and self.rows_table.columnCount() > 0:
            self._render_table_page(table_page)
            return

        start_row = self.rows_table.rowCount()
        self.rows_table.setRowCount(start_row + len(rows))

        for row_i, row in enumerate(rows):
            for col_i, key in enumerate(columns):
                item = QTableWidgetItem(str(row.get(key, "")))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.rows_table.setItem(start_row + row_i, col_i, item)

        self.rows_table.clearSelection()
        self.rows_table.setCurrentCell(-1, -1)
        self._resize_rows_for_content(columns)

    @classmethod
    def _format_viewer_timestamp(cls, value):
        if value in (None, ""):
            return ""
        try:
            return dt.datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError, OverflowError):
            return str(value)

    @classmethod
    def _display_rows_for_table(cls, table_name: str, rows: list[dict]) -> list[dict]:
        display_rows = []
        for row in rows:
            display_row = {}
            for key, value in row.items():
                if table_name == "sessions" and key in cls._HIDDEN_SESSION_COLUMNS:
                    continue
                if key in cls._TIMESTAMP_COLUMNS:
                    display_row[key] = cls._format_viewer_timestamp(value)
                else:
                    display_row[key] = value
            display_rows.append(display_row)
        return display_rows

    def _resize_rows_for_content(self, columns: list[str]) -> None:
        if not columns:
            return
        if "text" in columns:
            self.rows_table.setColumnWidth(columns.index("text"), 420)
        self.rows_table.resizeRowsToContents()

    def closeEvent(self, event):
        self._is_closed = True
        self._refresh_request_token += 1
        self._table_load_token += 1
        self.refresh_in_flight = False
        self.load_more_btn.setEnabled(False)

        if self.current_snapshot is not None:
            delete_snapshot(self.current_snapshot)
            self.current_snapshot = None

        if event is not None:
            event.accept()


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


# ── Main panel ────────────────────────────────────────────────

class SparkPanel(QWidget):
    """
    Frameless floating SPARK panel — replaces SparkPipeline window.
    Wires directly into AccessibilityManager, WindowContextTracker,
    GlobalHotkeyManager, and Jetson-bound transport from your existing architecture.
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
        self.setFixedWidth(1500)
        self.setStyleSheet(QSS)

        # ── Backend (same objects as SparkPipeline) ──────────────
        self.manager = AccessibilityManager()
        self.web_extractor = WebContentExtractor()
        self.hotkeys = GlobalHotkeyManager()
        self.settings = QSettings("SPARK", "SPARK")
        self.tracker = WindowContextTracker()

        # ── HID device ───────────────────────────────────────────
        self.hid_signals = HIDSignals()
        self.hid_client  = SparkHIDClient()

        # ── Serial sender (Host → Pico Hub) ──────────────────────
        self.serial_sender = SerialSender()
        self.serial_sender.set_packet_callback(self._handle_serial_packet)
        self.serial_sender.connect()   # best-effort; silently skipped if no Pico
        self._last_serial_key: str | None = None
        self._last_serial_fingerprint: str | None = None

        self.captured_text: str = ""
        self.processed_text: str = ""
        self.is_polling = False
        self._release_in_progress = False
        self._summary_request_in_flight = False
        self._active_feature_command: AppCommand | None = None
        self._last_device_response_signature = (0, False, False)
        self._device_response_poll_deadline = 0.0
        self._last_physical_reformat_trigger_at = 0.0
        self._last_physical_respond_trigger_at = 0.0
        self._last_pico_runtime_text = ""
        self._last_pico_runtime_emitted_at: float | None = None
        self._last_runtime_response_flags = (False, False)
        self._capture_feed = LiveCaptureFeed(max_lines=self.MAX_CAPTURE_LINES)
        self._drag_pos: QPoint | None = None

        self._build_ui()
        self._connect_hotkeys()
        self.hotkeys.start()
        self._connect_hid()

        self.poll_timer = QTimer()
        self.poll_timer.setInterval(self.POLL_INTERVAL)
        self.poll_timer.timeout.connect(self._on_poll_tick)

        self._response_poll_timer = QTimer()
        self._response_poll_timer.setInterval(self.POLL_INTERVAL)
        self._response_poll_timer.timeout.connect(self._poll_device_response)

        self._pico_runtime_timer = QTimer()
        self._pico_runtime_timer.setInterval(1000)
        self._pico_runtime_timer.timeout.connect(self._poll_pico_runtime_status)
        self._pico_runtime_timer.start()

        self._blink_timer = QTimer()
        self._blink_timer.timeout.connect(self._blink_live)
        self._blink_state = True

        self._serial_poll_timer = QTimer()
        self._serial_poll_timer.setInterval(2000)
        self._serial_poll_timer.timeout.connect(self._poll_serial_connection)
        self._serial_poll_timer.start()

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
        top_lay = QVBoxLayout(inner)
        top_lay.setContentsMargins(22, 20, 22, 22)
        top_lay.setSpacing(0)

        # ── Header (full width) ──────────────────────────────
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
        close.mousePressEvent = lambda _: QApplication.instance().quit()
        hdr.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)

        top_lay.addLayout(hdr)
        top_lay.addSpacing(14)
        top_lay.addWidget(self._divider())
        top_lay.addSpacing(14)

        # ── Two-column body ──────────────────────────────────
        columns = QHBoxLayout()
        columns.setSpacing(20)

        # ── LEFT COLUMN: context cards + status + actions ────
        left = QVBoxLayout()
        left.setSpacing(0)

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
        left.addLayout(ctx_hdr)
        left.addSpacing(10)

        # 3 context cards (active + 2 history)
        self.ctx_card_active = ContextCard("—", "No window detected", active=True)
        self.ctx_card_prev1  = ContextCard("—", "")
        self.ctx_card_prev2  = ContextCard("—", "")
        for card in (self.ctx_card_active, self.ctx_card_prev1, self.ctx_card_prev2):
            left.addWidget(card)
            left.addSpacing(6)

        left.addSpacing(10)
        left.addWidget(self._divider())
        left.addSpacing(14)

        # Status line
        self.status_lbl = QLabel(f"Ready - select text in any app, then {CAPTURE_HOTKEY_LABEL}")
        self.status_lbl.setObjectName("status_label")
        self.status_lbl.setWordWrap(True)
        left.addWidget(self.status_lbl)
        left.addSpacing(14)

        left.addWidget(self._divider())
        left.addSpacing(14)

        # ── Suggested Actions ─────────────────────────────────
        act_lbl = QLabel("SUGGESTED ACTIONS")
        act_lbl.setObjectName("section_label")
        left.addWidget(act_lbl)
        left.addSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(8)

        self.btn_capture  = ActionButton("Capture Text", f"{CAPTURE_HOTKEY_LABEL} - grab selection", self)
        self.btn_release  = ActionButton("Release Text", f"{RELEASE_HOTKEY_LABEL} - send to SPARK", self)
        self.btn_summarize = ActionButton("Summarize Window", "Quick overview of visible text", self)
        self.btn_reformat = ActionButton("Reformat Selection", "Reformat highlighted text")
        self.btn_reformat.setProperty("test_id", "btn_reformat")
        self.btn_test_context = ActionButton("Test Context", "Send a fixed fake app context")
        self.btn_custom_context = ActionButton("Custom Context", "Edit and send a fake app context")
        self.btn_view_jetson_db = ActionButton("View Jetson DB", "Browse snapshot tables")
        self.btn_history  = ActionButton("Show History", "View previous window contexts", self)

        self.btn_release.setEnabled(False)
        self.btn_capture.hide()
        self.btn_release.hide()
        self.btn_summarize.hide()
        self.btn_history.hide()

        self.btn_capture.clicked.connect(self._on_capture)
        self.btn_release.clicked.connect(self._on_release)
        self.btn_summarize.clicked.connect(self._on_summarize)
        self.btn_reformat.clicked.connect(self._on_reformat)
        self.btn_test_context.clicked.connect(self._on_test_context)
        self.btn_custom_context.clicked.connect(self._on_custom_context)
        self.btn_view_jetson_db.clicked.connect(self._on_view_jetson_db)
        self.btn_history.clicked.connect(self._on_show_history)

        grid.addWidget(self.btn_reformat, 0, 0)
        grid.addWidget(self.btn_test_context, 0, 1)
        grid.addWidget(self.btn_custom_context, 1, 0)
        grid.addWidget(self.btn_view_jetson_db, 1, 1)
        left.addLayout(grid)
        left.addStretch()

        # ── RIGHT COLUMN: live capture + release output ──────
        right = QVBoxLayout()
        right.setSpacing(0)

        cap_hdr = QHBoxLayout()
        cap_sec = QLabel("LIVE CAPTURE")
        cap_sec.setObjectName("section_label")
        cap_hdr.addWidget(cap_sec)
        cap_hdr.addStretch()

        self.live_dot = QLabel("● Live")
        self.live_dot.setObjectName("live_dot")
        cap_hdr.addWidget(self.live_dot)
        right.addLayout(cap_hdr)
        right.addSpacing(10)

        cap_frame = QFrame()
        cap_frame.setObjectName("capture_frame")
        cap_inner = QVBoxLayout(cap_frame)
        cap_inner.setContentsMargins(14, 12, 14, 12)

        self.capture_lbl = QLabel("Polling not started…")
        self.capture_lbl.setObjectName("capture_text")
        self.capture_lbl.setWordWrap(True)
        self.capture_lbl.setMinimumHeight(120)
        self.capture_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cap_inner.addWidget(self.capture_lbl)
        cap_frame.setMinimumHeight(180)
        right.addWidget(cap_frame)
        right.addSpacing(14)

        right.addWidget(self._divider())
        right.addSpacing(14)

        out_hdr = QHBoxLayout()
        out_sec = QLabel("RELEASE OUTPUT")
        out_sec.setObjectName("section_label")
        out_hdr.addWidget(out_sec)
        out_hdr.addStretch()
        right.addLayout(out_hdr)
        right.addSpacing(10)

        out_frame = QFrame()
        out_frame.setObjectName("capture_frame")
        out_inner = QVBoxLayout(out_frame)
        out_inner.setContentsMargins(14, 12, 14, 12)

        self.release_output_lbl = QTextEdit("No released text yet…")
        self.release_output_lbl.setObjectName("release_output_text")
        self.release_output_lbl.setReadOnly(True)
        self.release_output_lbl.setFrameStyle(QFrame.Shape.NoFrame)
        self.release_output_lbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.release_output_lbl.setMinimumHeight(320)
        self.release_output_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        out_inner.addWidget(self.release_output_lbl)
        out_frame.setMinimumHeight(380)
        right.addWidget(out_frame)

        # ── Assemble columns (1:2 ratio) ─────────────────────
        left_wrapper = QWidget()
        left_wrapper.setLayout(left)
        left_wrapper.setFixedWidth(440)

        right_wrapper = QWidget()
        right_wrapper.setLayout(right)

        columns.addWidget(left_wrapper)
        columns.addWidget(self._vdivider())
        columns.addWidget(right_wrapper, stretch=1)

        top_lay.addLayout(columns)

        outer.addWidget(inner)

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("divider")
        return d

    def _vdivider(self) -> QFrame:
        d = QFrame()
        d.setStyleSheet(f"background-color: {SURFACE}; max-width: 1px;")
        d.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
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
        self.hid_signals.summarize_progress.connect(self._on_summarize_progress)
        self.hid_signals.summarize_succeeded.connect(self._on_summarize_succeeded)
        self.hid_signals.summarize_failed.connect(self._on_summarize_failed)
        self.hid_signals.summarize_finished.connect(self._on_summarize_finished)
        self.hid_signals.pico_debug.connect(self._on_pico_debug_message)
        self._hid_poll_timer = QTimer()
        self._hid_poll_timer.setInterval(2000)
        self._hid_poll_timer.timeout.connect(self._poll_hid_connection)
        self._hid_poll_timer.start()
        # Fire initial poll immediately so UI shows correct device state at startup
        self._poll_hid_connection()

    def _poll_hid_connection(self):
        """Check USB connection and emit signal if state changed."""
        try:
            connected = self.hid_client.poll_connected()
        except Exception as exc:
            logger.error("[HID] poll_connected() raised unexpectedly: %s", exc)
            connected = False
        previous = getattr(self, "_hid_connected", None)
        if connected != previous:
            self._hid_previous_state = previous
            self._hid_connected = connected
            self.hid_signals.device_connected.emit(connected)

    def _poll_serial_connection(self):
        if self.serial_sender.is_connected():
            return
        self.serial_sender.connect()

    def _poll_pico_runtime_status(self):
        if self._response_poll_timer.isActive() or self._summary_request_in_flight:
            return

        if not self.hid_client.is_connected():
            self._last_pico_runtime_text = ""
            self._last_pico_runtime_emitted_at = None
            self._last_runtime_response_flags = (False, False)
            return

        try:
            status = self.hid_client.get_runtime_status()
        except Exception:
            return

        logger = logging.getLogger("pico.debug")
        drained_debug_events = False
        for _ in range(8):
            try:
                event = self.hid_client.get_debug_event()
            except Exception:
                break
            if not isinstance(event, str) or not event:
                break
            drained_debug_events = True
            logger.info("[PICO] %s", event)
            self.hid_signals.pico_debug.emit(event.split("|", 1)[0])

        runtime_text = getattr(status, "text", "") or ""
        runtime_message = runtime_text.split("|", 1)[0] if runtime_text else ""
        now = time.monotonic()
        should_emit = runtime_text and runtime_text != self._last_pico_runtime_text
        if runtime_message == "heartbeat" and self._last_pico_runtime_emitted_at is not None:
            if (now - self._last_pico_runtime_emitted_at) >= 5.0:
                should_emit = True

        if should_emit and not drained_debug_events:
            self._last_pico_runtime_text = runtime_text
            self._last_pico_runtime_emitted_at = now
            logger.info("[PICO] %s", runtime_text)
            self.hid_signals.pico_debug.emit(runtime_message)

        response_flags = (bool(status.active), bool(status.complete))
        should_start_response_polling = (
            not self._summary_request_in_flight
            and response_flags != self._last_runtime_response_flags
            and (status.active or status.complete)
        )
        self._last_runtime_response_flags = response_flags

        if should_start_response_polling:
            self._start_device_response_polling()

    def _handle_serial_packet(self, pkt: dict):
        if pkt.get("type") == 0x08:
            self.hid_signals.pico_debug.emit(pkt.get("msg", ""))

    def _on_hid_connected(self, connected: bool):
        """Update the device status dot in the header and handle mid-session drops."""
        if connected:
            self.device_dot.setText("● DEVICE CONNECTED")
            self.device_dot.setStyleSheet(f"color: {GREEN};")
            self.device_dot.setToolTip("SPARK device connected")
            logger.info("[HID] Device connected")
            if self.processed_text:
                self.btn_release.setEnabled(True)
        else:
            self.device_dot.setText("● DEVICE DISCONNECTED")
            self.device_dot.setStyleSheet("color: #374151;")
            self.device_dot.setToolTip("SPARK device disconnected")
            self.btn_release.setEnabled(False)
            if getattr(self, "_hid_previous_state", None) is True:
                logger.warning("[HID] Device disconnected mid-session - Release disabled")
                self._set_status("SPARK device disconnected", RED)
                if self._release_in_progress:
                    logger.warning("[HID] Release was in progress when device dropped")
            else:
                logger.warning("[HID] Device not found")

    def _on_release_succeeded(self, text: str):
        self.release_output_lbl.setPlainText(format_release_output(text) if text else "No released text yet…")
        self._set_status("Sent to SPARK — output updated ✓", GREEN)

    def _on_release_failed(self, message: str):
        logger.error("[RELEASE] Failed: %s", message)
        self._set_status(message, RED)

    def _on_release_finished(self):
        self._release_in_progress = False
        if getattr(self, "_hid_connected", False):
            self.btn_release.setEnabled(True)

    def _set_summary_buttons_enabled(self, enabled: bool):
        self.btn_summarize.setEnabled(enabled)
        self.btn_reformat.setEnabled(enabled)
        self.btn_test_context.setEnabled(enabled)
        self.btn_custom_context.setEnabled(enabled)

    def _on_summarize_succeeded(self, text: str):
        if self._active_feature_command == AppCommand.FEATURE_4:
            self.release_output_lbl.setPlainText(text if text else "No response returned.")
            if text:
                QApplication.clipboard().setText(text)
            self._set_status("Jetson response complete — output updated", GREEN)
            return

        self.release_output_lbl.setPlainText(text if text else "No summary returned.")
        if self._active_feature_command == AppCommand.FEATURE_2:
            if text:
                QApplication.clipboard().setText(text)
            self._set_status("Jetson reformat complete — output updated", GREEN)
            return
        self._set_status("Jetson summary complete — output updated", GREEN)

    def _on_summarize_progress(self, text: str):
        self.release_output_lbl.setPlainText(text)
        if self._active_feature_command == AppCommand.FEATURE_4:
            self._set_status("Streaming response from Jetson…", ORANGE)
            return
        if self._active_feature_command == AppCommand.FEATURE_2:
            self._set_status("Streaming reformat from Jetson…", ORANGE)
            return
        self._set_status("Streaming summary from Jetson…", ORANGE)

    def _on_summarize_failed(self, message: str):
        self._set_status(message, RED)

    def _drain_stale_hid_debug_events(self, *, limit: int = 16):
        if not self.hid_client.is_connected():
            return
        for _ in range(limit):
            try:
                event = self.hid_client.get_debug_event()
            except Exception:
                return
            if not isinstance(event, str) or not event:
                return

    def _on_summarize_finished(self):
        self._summary_request_in_flight = False
        self._active_feature_command = None
        self._drain_stale_hid_debug_events()
        self._set_summary_buttons_enabled(True)

    def _on_pico_debug_message(self, message: str):
        if message == "button:1" and not self._summary_request_in_flight:
            self._start_device_response_polling()
            return
        if message == "post_press:2" and not self._summary_request_in_flight:
            now = time.monotonic()
            if (now - self._last_physical_reformat_trigger_at) < 1.0:
                return
            self._last_physical_reformat_trigger_at = now
            self._on_reformat()
            return
        if message == "post_press:4" and not self._summary_request_in_flight:
            now = time.monotonic()
            if (now - self._last_physical_respond_trigger_at) < 1.0:
                return
            self._last_physical_respond_trigger_at = now
            self._on_respond()

    def _start_device_response_polling(self):
        self._device_response_poll_deadline = time.monotonic() + 30.0
        self._last_device_response_signature = (0, False, False)
        if not self._response_poll_timer.isActive():
            self._response_poll_timer.start()

    def _stop_device_response_polling(self):
        self._device_response_poll_deadline = 0.0
        self._last_device_response_signature = (0, False, False)
        self._response_poll_timer.stop()

    def _poll_device_response(self):
        if self._summary_request_in_flight:
            self._stop_device_response_polling()
            return

        if self._device_response_poll_deadline and time.monotonic() >= self._device_response_poll_deadline:
            self._stop_device_response_polling()
            return

        connected = getattr(self, "_hid_connected", None)
        if connected is False:
            self._stop_device_response_polling()
            return
        if connected is None and not self.hid_client.is_connected():
            self._stop_device_response_polling()
            return

        try:
            info = self.hid_client.get_response_info()
        except Exception:
            return

        signature = (info.total_len, info.complete, info.active)
        if signature == self._last_device_response_signature:
            return
        self._last_device_response_signature = signature

        if info.total_len == 0 and not info.active and not info.complete:
            return

        if info.total_len > 0:
            try:
                text = self.hid_client.fetch_response(info)
            except Exception:
                return
            self.release_output_lbl.setPlainText(text if text else "No summary returned.")

        if info.complete:
            self._set_status("Jetson summary complete — output updated", GREEN)
            self._stop_device_response_polling()
        else:
            self._set_status("Streaming summary from Jetson…", ORANGE)

    # ─────────────────────────────────────────────────────────────
    # Polling — identical logic to SparkPipeline._on_poll_tick
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_browser_app_for_poll(app_name: str) -> bool:
        normalized = (app_name or "").strip().lower()
        if normalized.endswith(".exe"):
            normalized = normalized[:-4]
        return _is_supported_windows_browser(normalized) or _is_supported_macos_browser(app_name)

    def _extract_web_fallback_text_for_windows_browser(self, app_name: str):
        from host_pc import web_content_windows

        try:
            focused_text = self.manager.get_focused_element_text()
            focused_eval = web_content_windows.evaluate_focused_fallback(focused_text)
            if focused_eval and focused_eval.is_useful and focused_eval.text:
                logger.debug("[POLL] accepted focused fallback for %s", app_name)
                return focused_eval.text, TextSource.WEB_CONTENT
        except Exception as exc:
            logger.warning(
                "[POLL] focused fallback extraction failed for %s: %s",
                app_name,
                exc,
            )

        try:
            window_text = self.manager.get_window_text()
            window_eval = web_content_windows.evaluate_window_fallback(window_text)
            if window_eval and window_eval.is_useful and window_eval.text:
                logger.debug("[POLL] accepted window fallback for %s", app_name)
                return window_eval.text, TextSource.WEB_CONTENT
        except Exception as exc:
            logger.warning(
                "[POLL] window fallback extraction failed for %s: %s",
                app_name,
                exc,
            )

        return None, None

    def _extract_accessibility_fallback_text(self, app_name: str):
        try:
            text = self.manager.get_focused_element_text()
            if text:
                return text, TextSource.FOCUSED_ELEMENT
        except Exception as exc:
            logger.warning(
                "[POLL] get_focused_element_text failed for %s: %s",
                app_name,
                exc,
            )

        try:
            text = self.manager.get_window_text()
            if text:
                return text, TextSource.FULL_WINDOW
        except Exception as exc:
            logger.warning(
                "[POLL] get_window_text failed for %s: %s",
                app_name,
                exc,
            )

        return None, None

    @staticmethod
    def _build_context_key(info, tab) -> str:
        url = tab.url if (tab and getattr(tab, "url", None)) else ""
        return f"{info.app_name}|{url}" if url else f"{info.app_name}|{info.title}"

    @staticmethod
    def _build_active_context_subtitle(info, tab) -> str:
        detail = tab.tab_title if (tab and tab.tab_title) else info.title
        if not tab:
            return detail

        url = tab.url or ""
        context_key = SparkPanel._build_context_key(info, tab)
        url_display = url or "(missing)"
        return f"{detail}\nURL: {url_display}\nKey: {context_key}"

    def _on_toggle_polling(self):
        if self.is_polling:
            self.poll_timer.stop()
            self._blink_timer.stop()
            self.is_polling = False
            logger.info("[POLL] Stopped live context polling")
            self.poll_btn.setText("Start Polling")
            self.poll_btn.setProperty("active", "false")
            self.poll_btn.setStyle(self.poll_btn.style())
            self.live_dot.setText("● Live")
        else:
            self.is_polling = True
            logger.info("[POLL] Started live context polling")
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
            return
        # Ignore the SPARK panel itself
        if info.pid == os.getpid() or _is_ignored_poll_window(info):
            return
        # --- PRIVACY CHECK ---
        if not self.privacy_guard.is_safe(info.bundle_id, info.title):
            self.ctx_card_active.update_data("PROTECTED", "Privacy Filter Active", active=True)
            self._set_status("🛡️ Privacy Guard: Content Hidden", RED)
            # We stop here so no text is extracted or sent downstream.
            return
        # ---------------------

        window_target = getattr(info, "window_handle", None)
        if not isinstance(window_target, int) or isinstance(window_target, bool):
            window_target = None

        tab = get_browser_tab(info.app_name, window_target=window_target)
        detail = self._build_active_context_subtitle(info, tab)
        if tab and not self.privacy_guard.is_safe(info.bundle_id, tab.tab_title):
            self.ctx_card_active.update_data(info.app_name, "Protected URL", active=True)
            return
        self.ctx_card_active.update_data(info.app_name, detail, active=True)

        # Try to get text
        text, source = None, None
        browser_result = None
        current_snapshot = self.tracker.get_current()
        next_context_key = self._build_context_key(info, tab) if tab else None

        if tab and self._is_browser_app_for_poll(info.app_name):
            try:
                browser_result = self.web_extractor.extract_page(
                    tab.url or "",
                    info.app_name,
                    window_target=window_target,
                )
                if (
                    browser_result
                    and browser_result.is_useful
                    and browser_result.text
                    and browser_result.text.strip()
                ):
                    text = browser_result.text
                    source = TextSource.WEB_CONTENT
            except Exception as exc:
                logger.warning("[POLL] web extraction failed for %s: %s", info.app_name, exc)
                browser_result = None

            if text is None and browser_result is not None:
                # Windows browser paths should reject noisy browser output and try
                # accessibility fallbacks in a filtered order.
                if sys.platform == "win32":
                    if browser_result.text and not browser_result.is_useful:
                        logger.debug(
                            "[POLL] rejected noisy browser output for %s from source=%s",
                            info.app_name,
                            browser_result.source,
                        )
                    fallback_text, fallback_source = self._extract_web_fallback_text_for_windows_browser(
                        info.app_name
                    )
                    if fallback_text:
                        text = fallback_text
                        source = fallback_source

        if not text and not (sys.platform == "win32" and tab and browser_result is not None):
            fallback_text, fallback_source = self._extract_accessibility_fallback_text(
                info.app_name
            )
            if fallback_text:
                text = fallback_text
                source = fallback_source

        metadata_only_browser_switch = bool(
            tab
            and self._is_browser_app_for_poll(info.app_name)
            and not (text and text.strip())
            and next_context_key
            and (current_snapshot is None or current_snapshot.context_key != next_context_key)
        )

        #Edit 

        if (text and text.strip() and source) or metadata_only_browser_switch:
            latest_info = self.manager.get_active_window_info()
            browser_bound_sample = bool(tab and self._is_browser_app_for_poll(info.app_name))
            if not browser_bound_sample and not _same_poll_target(info, latest_info):
                logger.info(
                    "[POLL] Dropped stale context sample because active window changed before commit"
                )
                return
            committed_text = text if (text and text.strip()) else ""
            committed_source = source if source else TextSource.WEB_CONTENT
            if committed_text:
                preview = committed_text[:120].replace("\n", " ")
                self._push_poll_capture_line(f"[{info.app_name}] {preview}")
            else:
                self._push_poll_capture_line(f"[{info.app_name}] (browser metadata only)")

            self.tracker.update(info, committed_text, committed_source, tab=tab)
            current = self.tracker.get_current()
            if current and (is_relevant_snapshot(current) or metadata_only_browser_switch):
                if not self.serial_sender.is_connected():
                    self.serial_sender.connect()
                key = current.context_key
                fingerprint = snapshot_fingerprint(current)
                if key != self._last_serial_key:
                    if self.serial_sender.send_context_new(current):
                        self._last_serial_key = key
                        self._last_serial_fingerprint = fingerprint
                else:
                    if fingerprint != self._last_serial_fingerprint:
                        if self.serial_sender.send_context_update(current):
                            self._last_serial_fingerprint = fingerprint
                        else:
                            self._last_serial_key = None
                            self._last_serial_fingerprint = None
        else:
            self._push_poll_capture_line(f"[{info.app_name}] (no text extracted)")

        self._refresh_history_cards()

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
            if getattr(self, "_hid_connected", False):
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
        self._release_in_progress = True
        text = self.processed_text
        threading.Thread(target=self._do_release, args=(text,), daemon=True).start()

    def _do_release(self, text: str):
        """Upload text to the device (runs in background thread)."""
        self.serial_sender.pause()
        try:
            status = self.hid_client.upload(AppCommand.SUBMIT_TEXT, text)
            if status.ok:
                logger.info("[RELEASE] Upload acknowledged by device (%d chars)", len(text))
                try:
                    echo = self.hid_client.fetch_response()
                    if echo:
                        logger.info("[PICO ECHO] %s", echo)
                    else:
                        logger.info("[PICO ECHO] (empty response buffer)")
                except Exception as exc:
                    logger.warning("[PICO ECHO] Could not read response: %s", exc)
                self.hid_signals.device_connected.emit(True)  # reuse signal to confirm alive
                self.hid_signals.release_succeeded.emit(text)
            else:
                logger.error("[RELEASE] Device rejected upload: %s", status.code.name)
                self.hid_signals.release_failed.emit(f"Device error: {status.code.name}")
        except SparkProtocolError as exc:
            logger.error("[RELEASE] SparkProtocolError: %s", exc)
            self.hid_signals.release_failed.emit(f"HID error: {exc}")
        except Exception as exc:
            logger.exception("[RELEASE] Unexpected error during upload")
            self.hid_signals.release_failed.emit(f"Unexpected error: {exc}")
        finally:
            self.serial_sender.resume()
            self.hid_signals.release_finished.emit()

    def _on_summarize(self):
        """Send lightweight summarize signal — Jetson reads context from its own DB."""
        request = build_summarize_command()
        self._start_feature_request(
            AppCommand.FEATURE_1,
            request=request,
            capture_label="[SUMMARY REQUEST] Summarize active context",
            status_text="Sending summarize command to Jetson…",
        )

    def _on_test_context(self):
        request = build_test_summary_request()
        self._start_feature_request(
            AppCommand.FEATURE_1,
            request=request,
            capture_label="[TEST CONTEXT] Fixed sample context",
            status_text="Sending fixed test context to Jetson…",
        )

    def _on_custom_context(self):
        dialog = CustomContextDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        app_name, window_title, window_text = dialog.get_values()
        request = build_summary_request(app_name, window_title, window_text)
        self._start_feature_request(
            AppCommand.FEATURE_1,
            request=request,
            capture_label=f"[CUSTOM CONTEXT] {app_name or '(unknown app)'} — {(window_title or '')[:60]}",
            status_text="Sending custom context to Jetson…",
        )

    def _on_reformat(self):
        info = self.manager.get_active_window_info()
        if info and not self.privacy_guard.is_safe(info.bundle_id, info.title):
            self._set_status("Cannot reformat: Sensitive window detected", RED)
            return

        selected = self.manager.get_selected_text()
        if not (selected and selected.strip()):
            self._set_status("No text selected — highlight text first", RED)
            return

        request = build_reformat_request(selected)
        self._start_feature_request(
            AppCommand.FEATURE_2,
            request=request,
            capture_label="[REFORMAT] Reformat selected text",
            status_text="Sending reformat request to Jetson…",
        )

    def _on_respond(self):
        info = self.manager.get_active_window_info()
        if info and not self.privacy_guard.is_safe(info.bundle_id, info.title):
            self._set_status("Cannot respond: Sensitive window detected", RED)
            return

        draft_text = self.manager.get_focused_element_text()
        if not (draft_text and draft_text.strip()):
            draft_text = self.manager.get_window_text()
        if not (draft_text and draft_text.strip()):
            draft_text = self.processed_text

        if not (draft_text and draft_text.strip()):
            self._set_status("No draft text detected — place the cursor in the text field first", RED)
            return

        request = build_respond_request(draft_text)
        self._start_feature_request(
            AppCommand.FEATURE_4,
            request=request,
            capture_label="[RESPOND] Continue current draft",
            status_text="Sending respond request to Jetson…",
        )

    def _on_view_jetson_db(self):
        dialog = JetsonDbViewerDialog(self)
        dialog.exec()

    def _start_feature_request(self, app_command: AppCommand, request: str, capture_label: str, status_text: str):
        if not self.hid_client.is_connected():
            self._set_status("SPARK device not connected", RED)
            return

        self._stop_device_response_polling()
        self._active_feature_command = app_command
        self._summary_request_in_flight = True
        self._set_summary_buttons_enabled(False)
        self._push_capture_line(capture_label)
        self._set_status(status_text, ORANGE)
        threading.Thread(target=self._do_feature_round_trip, args=(app_command, request), daemon=True).start()

    def _do_feature_round_trip(self, app_command: AppCommand, prompt: str):
        try:
            response = self.hid_client.stream_round_trip_text(
                app_command,
                prompt,
                on_update=self.hid_signals.summarize_progress.emit,
            )
            self.hid_signals.summarize_succeeded.emit(response)
        except SparkProtocolError as exc:
            self.hid_signals.summarize_failed.emit(f"HID error: {exc}")
        except Exception as exc:
            self.hid_signals.summarize_failed.emit(f"Feature request failed: {exc}")
        finally:
            self.hid_signals.summarize_finished.emit()

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
            self.settings.setValue("panel_x", self.pos().x())
            self.settings.setValue("panel_y", self.pos().y())
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
        saved_x = self.settings.value("panel_x")
        saved_y = self.settings.value("panel_y")
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
        logger.info("[APP] Shutting down - cleaning up resources")
        try:
            self.poll_timer.stop()
            self._blink_timer.stop()
            self._hid_poll_timer.stop()
            self._pico_runtime_timer.stop()
            self._serial_poll_timer.stop()
            self._response_poll_timer.stop()
            self.hotkeys.stop()
        except Exception as exc:
            logger.error("[APP] Error stopping timers/hotkeys: %s", exc)
        try:
            self.hid_client.close()
        except Exception as exc:
            logger.error("[APP] Error closing HID client: %s", exc)
        try:
            self.serial_sender.close()
        except Exception as exc:
            logger.error("[APP] Error closing serial sender: %s", exc)
        logger.info("[APP] Shutdown complete")
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

def _install_exception_hooks():
    """Report uncaught exceptions from any thread to the terminal."""
    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("[CRASH] Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _excepthook

    def _thread_excepthook(args):
        logger.critical(
            "[CRASH] Uncaught exception in thread '%s'",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

def main():
    _install_exception_hooks()

    instance_guard = SingleInstanceGuard.for_app("spark_app_v2")
    if not instance_guard.acquire():
        logger.error("Another spark_app_v2.py instance is already running; refusing to start a duplicate")
        return 1

    try:
        app = QApplication(sys.argv)
    except Exception as exc:
        logger.critical("[APP] Failed to create QApplication: %s", exc)
        instance_guard.release()
        return 1

    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    app.aboutToQuit.connect(instance_guard.release)

    signal.signal(signal.SIGINT, lambda *_: (logger.info("[APP] SIGINT received - quitting"), app.quit()))
    signal.signal(signal.SIGTERM, lambda *_: (logger.info("[APP] SIGTERM received - quitting"), app.quit()))
    _sig_timer = QTimer()
    _sig_timer.setInterval(200)
    _sig_timer.timeout.connect(lambda: None)
    _sig_timer.start()

    try:
        panel = SparkPanel()
    except Exception as exc:
        logger.critical("[APP] Failed to initialise SparkPanel: %s", exc, exc_info=True)
        instance_guard.release()
        return 1

    panel._instance_guard = instance_guard

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
    app.aboutToQuit.connect(panel.close)

    panel.show()
    try:
        return app.exec()
    except Exception as exc:
        logger.critical("[APP] Fatal error in event loop: %s", exc, exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
