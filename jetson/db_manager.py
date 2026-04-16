"""
SPARK Jetson Brain - authoritative rich context store.

The Jetson owns durable persistence for captured context sessions plus button
events linked to the active session.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_SESSION_RECENCY_ORDER = "COALESCE(host_observed_at, updated_at) DESC, id DESC"


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip().lower()


def build_context_key(payload: dict) -> str:
    app_name = payload.get("app_name", "")
    url = payload.get("url")
    window_title = payload.get("window_title", "")
    if url:
        return f"{app_name}|{url}"
    return f"{app_name}|{window_title}"


def build_content_fingerprint(payload: dict) -> str:
    body = "|".join(
        (
            _normalize(payload.get("app_name")),
            _normalize(payload.get("url")) or _normalize(payload.get("window_title")),
            _normalize(payload.get("text")),
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class JetsonDB:
    """Session-oriented SQLite store for the Jetson Brain node."""

    def __init__(self, db_path: str = "jetson_spark.db"):
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._active_session_id: Optional[int] = None
        self._active_context_key: Optional[str] = None
        self._create_tables()
        self._restore_active_session()
        logger.info("JetsonDB opened at %s", self._path.resolve())

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                context_key         TEXT    NOT NULL,
                content_fingerprint TEXT    NOT NULL,
                app_name            TEXT    NOT NULL,
                window_title        TEXT    NOT NULL,
                process_name        TEXT    NOT NULL,
                pid                 INTEGER NOT NULL,
                source              TEXT    NOT NULL,
                tab_title           TEXT,
                url                 TEXT,
                text                TEXT    NOT NULL DEFAULT '',
                host_observed_at    REAL,
                started_at          REAL    NOT NULL,
                updated_at          REAL    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_context_key
            ON sessions (context_key);

            CREATE INDEX IF NOT EXISTS idx_sessions_fingerprint
            ON sessions (content_fingerprint);

            CREATE TABLE IF NOT EXISTS button_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                button_id   INTEGER NOT NULL,
                session_id  INTEGER,
                timestamp   REAL    NOT NULL
            );
        """
        )
        self._conn.commit()

    def _restore_active_session(self) -> None:
        row = self._conn.execute(
            f"SELECT id, context_key FROM sessions ORDER BY {_SESSION_RECENCY_ORDER} LIMIT 1"
        ).fetchone()
        if row is None:
            return
        self._active_session_id = int(row["id"])
        self._active_context_key = row["context_key"]

    def on_context_new(self, payload: dict) -> int:
        now = time.time()
        context_key = build_context_key(payload)
        fingerprint = build_content_fingerprint(payload)
        host_observed_at = payload.get("timestamp")
        cur = self._conn.execute(
            """
            INSERT INTO sessions (
                context_key,
                content_fingerprint,
                app_name,
                window_title,
                process_name,
                pid,
                source,
                tab_title,
                url,
                text,
                host_observed_at,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context_key,
                fingerprint,
                payload.get("app_name", ""),
                payload.get("window_title", ""),
                payload.get("process_name", ""),
                int(payload.get("pid", 0)),
                payload.get("source", ""),
                payload.get("tab_title"),
                payload.get("url"),
                payload.get("text", ""),
                host_observed_at,
                now,
                now,
            ),
        )
        self._conn.commit()
        self._active_session_id = int(cur.lastrowid)
        self._active_context_key = context_key
        return self._active_session_id

    def on_context_update(self, payload: dict) -> None:
        context_key = build_context_key(payload)
        if self._active_session_id is None or self._active_context_key != context_key:
            logger.warning("CONTEXT_UPDATE with no matching active session - promoting to CONTEXT_NEW")
            self.on_context_new(payload)
            return

        now = time.time()
        fingerprint = build_content_fingerprint(payload)
        self._conn.execute(
            """
            UPDATE sessions
            SET content_fingerprint = ?,
                app_name = ?,
                window_title = ?,
                process_name = ?,
                pid = ?,
                source = ?,
                tab_title = ?,
                url = ?,
                text = ?,
                host_observed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                fingerprint,
                payload.get("app_name", ""),
                payload.get("window_title", ""),
                payload.get("process_name", ""),
                int(payload.get("pid", 0)),
                payload.get("source", ""),
                payload.get("tab_title"),
                payload.get("url"),
                payload.get("text", ""),
                payload.get("timestamp"),
                now,
                self._active_session_id,
            ),
        )
        self._conn.commit()

    def on_button_press(self, button_id: int) -> None:
        self._conn.execute(
            """
            INSERT INTO button_events (button_id, session_id, timestamp)
            VALUES (?, ?, ?)
            """,
            (button_id, self._active_session_id, time.time()),
        )
        self._conn.commit()

    def get_active_session(self) -> Optional[sqlite3.Row]:
        """Return the most recently updated session, or None."""
        if self._active_session_id is None:
            return None
        return self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (self._active_session_id,),
        ).fetchone()

    def get_recent_sessions(self, limit: int = 20):
        return self._conn.execute(
            f"SELECT * FROM sessions ORDER BY {_SESSION_RECENCY_ORDER} LIMIT ?",
            (limit,),
        ).fetchall()

    def close(self) -> None:
        self._conn.close()
        logger.info("JetsonDB closed")
