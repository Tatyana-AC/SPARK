"""
SPARK Jetson Brain — session-aware database manager.

INSERT on WINDOW_NEW (0x01), UPDATE on WINDOW_UPDATE (0x02).
This keeps one live row per window visit instead of inserting a new row
for every 8 Hz poll tick.
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class JetsonDB:
    """
    Session-aware SQLite layer for the Jetson Brain node.

    One session = one contiguous visit to a window.
    • on_window_new   → INSERT a new session row, set it as active.
    • on_window_update → UPDATE the active session's text (no new row).
    • on_button_press  → INSERT a button_events row linked to active session.
    """

    def __init__(self, db_path: str = "jetson_spark.db"):
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._active_session_id: Optional[int] = None
        self._create_tables()
        logger.info(f"JetsonDB opened at {self._path.resolve()}")

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name    TEXT    NOT NULL,
                title       TEXT    NOT NULL,
                text        TEXT    NOT NULL DEFAULT '',
                started_at  REAL    NOT NULL,
                updated_at  REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS button_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                button_id   INTEGER NOT NULL,
                session_id  INTEGER,
                timestamp   REAL    NOT NULL
            );
        """)
        self._conn.commit()

    # ── Packet handlers ──────────────────────────────────────────

    def on_window_new(self, app_name: str, title: str, text: str) -> None:
        """INSERT a new session and make it active."""
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO sessions (app_name, title, text, started_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (app_name, title, text, now, now),
        )
        self._conn.commit()
        self._active_session_id = cur.lastrowid
        logger.info(
            f"Session #{self._active_session_id} started: "
            f"{app_name} — {title!r} ({len(text)} chars)"
        )

    def on_window_update(self, text: str) -> None:
        """UPDATE the active session's text (no INSERT)."""
        if self._active_session_id is None:
            logger.warning("WINDOW_UPDATE with no active session — ignored")
            return
        self._conn.execute(
            "UPDATE sessions SET text = ?, updated_at = ? WHERE id = ?",
            (text, time.time(), self._active_session_id),
        )
        self._conn.commit()

    def on_button_press(self, button_id: int) -> None:
        """Log a physical button press."""
        self._conn.execute(
            "INSERT INTO button_events (button_id, session_id, timestamp) "
            "VALUES (?, ?, ?)",
            (button_id, self._active_session_id, time.time()),
        )
        self._conn.commit()
        logger.info(
            f"Button {button_id} pressed "
            f"(session #{self._active_session_id})"
        )

    # ── Queries ──────────────────────────────────────────────────

    def get_recent_sessions(self, limit: int = 20):
        """Return the most recent sessions, newest first."""
        return self._conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def close(self) -> None:
        self._conn.close()
        logger.info("JetsonDB closed")
